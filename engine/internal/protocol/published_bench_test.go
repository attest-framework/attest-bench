package protocol

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"testing"

	"github.com/attest-framework/attest-bench/engine/internal/trace"
)

// publishedEngineEnv names the released attest-engine binary under test. The
// benchmarks below skip when it is unset, so the source-built suite is
// unaffected.
const publishedEngineEnv = "ATTEST_BENCH_PUBLISHED_ENGINE"

// publishedEngine is a released attest-engine process speaking the released
// protocol: no subcommand, no ready line, initialize carries protocol_version.
type publishedEngine struct {
	cmd    *exec.Cmd
	stdin  interface{ Write([]byte) (int, error) }
	stdout *bufio.Reader
	close  func()
}

func startPublishedEngine(b *testing.B, binPath string) *publishedEngine {
	b.Helper()
	cmd := exec.Command(binPath)
	// The binary is a downloaded artifact: empty working directory and an
	// allowlisted environment, so it inherits no tokens and sees no checkout.
	cmd.Dir = b.TempDir()
	cmd.Env = []string{"PATH=/usr/bin:/bin", "HOME=" + b.TempDir(), "ATTEST_CACHE_DIR=" + b.TempDir()}
	stdin, err := cmd.StdinPipe()
	if err != nil {
		b.Fatalf("stdin pipe: %v", err)
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		b.Fatalf("stdout pipe: %v", err)
	}
	if err := cmd.Start(); err != nil {
		b.Fatalf("start %s: %v", binPath, err)
	}
	e := &publishedEngine{cmd: cmd, stdin: stdin, stdout: bufio.NewReaderSize(stdout, 1<<20)}
	e.close = func() {
		stdin.Close()
		cmd.Wait() //nolint:errcheck // exit status of a stdin-closed server is not measured
	}
	return e
}

// call sends one NDJSON request and fails the benchmark on any JSON-RPC error.
func (e *publishedEngine) call(b *testing.B, req []byte) {
	b.Helper()
	if _, err := e.stdin.Write(append(bytes.TrimRight(req, "\n"), '\n')); err != nil {
		b.Fatalf("write request: %v", err)
	}
	line, err := e.stdout.ReadBytes('\n')
	if err != nil {
		b.Fatalf("read response: %v", err)
	}
	var resp struct {
		Error *struct {
			Message string `json:"message"`
			Data    struct {
				Detail string `json:"detail"`
			} `json:"data"`
		} `json:"error"`
	}
	if err := json.Unmarshal(line, &resp); err != nil {
		b.Fatalf("unmarshal response: %v", err)
	}
	if resp.Error != nil {
		b.Fatalf("engine error: %q: %q", resp.Error.Message, resp.Error.Data.Detail)
	}
}

func publishedInitializeRequest() []byte {
	return []byte(`{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"sdk_name":"attest-bench","sdk_version":"0.0.0","protocol_version":1,"required_capabilities":["layers_1_4"],"preferred_encoding":"json"}}`)
}

func publishedShutdownRequest() []byte {
	return []byte(`{"jsonrpc":"2.0","id":9,"method":"shutdown","params":{}}`)
}

// publishedEvaluateRequest builds an evaluate_batch request the released
// engine accepts: a synthetic trace plus a required output object, and
// deterministic layer 1-4 assertions that all pass.
func publishedEvaluateRequest(steps, assertions int) []byte {
	raw, err := json.Marshal(trace.GenerateSyntheticTraceN(42, steps))
	if err != nil {
		panic(fmt.Sprintf("marshal synthetic trace: %v", err))
	}
	var tr map[string]any
	if err := json.Unmarshal(raw, &tr); err != nil {
		panic(fmt.Sprintf("unmarshal synthetic trace: %v", err))
	}
	tr["output"] = map[string]any{"message": "benchmark response"}
	// The synthetic generator predates trace-v2 step types.
	releasedStepType := map[string]string{"inference": "llm_call", "workflow": "agent_call"}
	for _, step := range tr["steps"].([]any) {
		m := step.(map[string]any)
		if mapped, ok := releasedStepType[m["type"].(string)]; ok {
			m["type"] = mapped
		}
	}

	specs := []struct {
		kind string
		spec map[string]any
	}{
		{"schema", map[string]any{"target": "output.message", "schema": map[string]any{"type": "string"}}},
		{"content", map[string]any{"target": "output.message", "check": "contains", "value": "benchmark"}},
		{"constraint", map[string]any{"field": "metadata.total_tokens", "operator": "gte", "value": 0}},
		{"trace", map[string]any{"check": "no_duplicate_calls", "tools": []string{"search_code"}, "max_repetitions": 100000}},
	}
	list := make([]map[string]any, assertions)
	for i := range list {
		s := specs[i%len(specs)]
		list[i] = map[string]any{"assertion_id": fmt.Sprintf("assert-%04d", i), "type": s.kind, "spec": s.spec}
	}
	req, err := json.Marshal(map[string]any{
		"jsonrpc": "2.0", "id": 2, "method": "evaluate_batch",
		"params": map[string]any{"trace": tr, "assertions": list},
	})
	if err != nil {
		panic(fmt.Sprintf("marshal evaluate_batch: %v", err))
	}
	return req
}

func publishedBinary(b *testing.B) string {
	b.Helper()
	path := os.Getenv(publishedEngineEnv)
	if path == "" {
		b.Skipf("%s not set", publishedEngineEnv)
	}
	return path
}

// BenchmarkPublishedEngineStartup measures process start through initialize
// and shutdown for a released engine binary.
func BenchmarkPublishedEngineStartup(b *testing.B) {
	binPath := publishedBinary(b)
	b.ReportAllocs()
	for b.Loop() {
		e := startPublishedEngine(b, binPath)
		e.call(b, publishedInitializeRequest())
		e.call(b, publishedShutdownRequest())
		e.close()
	}
}

// BenchmarkPublishedEngineEvaluate measures evaluate_batch roundtrips against
// one live released engine process.
func BenchmarkPublishedEngineEvaluate(b *testing.B) {
	binPath := publishedBinary(b)
	sizes := []struct {
		name    string
		steps   int
		asserts int
	}{
		{"10step_5assert", 10, 5},
		{"100step_10assert", 100, 10},
	}
	for _, tc := range sizes {
		b.Run(tc.name, func(b *testing.B) {
			b.ReportAllocs()
			req := publishedEvaluateRequest(tc.steps, tc.asserts)
			e := startPublishedEngine(b, binPath)
			defer e.close()
			e.call(b, publishedInitializeRequest())
			b.ResetTimer()
			for b.Loop() {
				e.call(b, req)
			}
			b.StopTimer()
			e.call(b, publishedShutdownRequest())
		})
	}
}
