package protocol

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"testing"
	"time"

	"github.com/attest-framework/attest-bench/engine/internal/trace"
)

// publishedEngineEnv names the released attest-engine binary under test. The
// benchmarks below skip when it is unset, so the source-built suite is
// unaffected.
const publishedEngineEnv = "ATTEST_BENCH_PUBLISHED_ENGINE"

// publishedCallTimeout bounds one request/response exchange so a hung engine
// fails the benchmark instead of the job timeout.
const publishedCallTimeout = 30 * time.Second

// engineDirs are the working, home and cache directories handed to the engine.
type engineDirs struct{ work, home, cache string }

func newEngineDirs(b *testing.B) engineDirs {
	b.Helper()
	return engineDirs{work: b.TempDir(), home: b.TempDir(), cache: b.TempDir()}
}

// publishedEngine is a released attest-engine process speaking the released
// protocol: no subcommand, no ready line, initialize carries protocol_version.
type publishedEngine struct {
	cmd   *exec.Cmd
	stdin io.WriteCloser
	lines chan []byte
}

func startPublishedEngine(b *testing.B, binPath string, dirs engineDirs) *publishedEngine {
	b.Helper()
	cmd := exec.Command(binPath)
	// Guard against accidental leaks, not a sandbox: an empty working
	// directory and an allowlisted environment keep tokens and the checkout
	// out of the engine's ordinary inputs. The process still runs as the
	// runner user.
	cmd.Dir = dirs.work
	cmd.Env = []string{"PATH=/usr/bin:/bin", "HOME=" + dirs.home, "ATTEST_CACHE_DIR=" + dirs.cache}
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
	e := &publishedEngine{cmd: cmd, stdin: stdin, lines: make(chan []byte, 1)}
	go func() {
		defer close(e.lines)
		br := bufio.NewReaderSize(stdout, 1<<20)
		for {
			line, err := br.ReadBytes('\n')
			if len(line) > 0 {
				e.lines <- line
			}
			if err != nil {
				return
			}
		}
	}()
	return e
}

func (e *publishedEngine) close() {
	e.stdin.Close()
	done := make(chan struct{})
	go func() { e.cmd.Wait(); close(done) }() //nolint:errcheck // exit status of a stdin-closed server is not measured
	select {
	case <-done:
	case <-time.After(publishedCallTimeout):
		e.cmd.Process.Kill() //nolint:errcheck
		<-done
	}
}

// call sends one NDJSON request and returns the response line, failing the
// benchmark on a write error, a timeout or a JSON-RPC error.
func (e *publishedEngine) call(b *testing.B, req []byte) []byte {
	b.Helper()
	if _, err := e.stdin.Write(append(bytes.TrimRight(req, "\n"), '\n')); err != nil {
		b.Fatalf("write request: %v", err)
	}
	var line []byte
	select {
	case l, ok := <-e.lines:
		if !ok {
			b.Fatalf("engine closed stdout before responding")
		}
		line = l
	case <-time.After(publishedCallTimeout):
		e.cmd.Process.Kill() //nolint:errcheck
		b.Fatalf("no response within %s", publishedCallTimeout)
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
	return line
}

// checkEvaluateResponse fails unless the response carries exactly the
// requested assertion ids (the engine orders results by layer, not by
// request), each once, all with status pass.
func checkEvaluateResponse(b *testing.B, line []byte, want int) {
	b.Helper()
	var resp struct {
		Result struct {
			Results []struct {
				AssertionID string `json:"assertion_id"`
				Status      string `json:"status"`
				Explanation string `json:"explanation"`
			} `json:"results"`
		} `json:"result"`
	}
	if err := json.Unmarshal(line, &resp); err != nil {
		b.Fatalf("unmarshal evaluate_batch response: %v", err)
	}
	if got := len(resp.Result.Results); got != want {
		b.Fatalf("evaluate_batch returned %d results, want %d", got, want)
	}
	seen := make(map[string]bool, want)
	for _, r := range resp.Result.Results {
		var idx int
		if _, err := fmt.Sscanf(r.AssertionID, "assert-%04d", &idx); err != nil || idx < 0 || idx >= want || seen[r.AssertionID] {
			b.Fatalf("unexpected or repeated assertion_id %q", r.AssertionID)
		}
		seen[r.AssertionID] = true
		if r.Status != "pass" {
			b.Fatalf("assertion %s status %q, want pass: %s", r.AssertionID, r.Status, r.Explanation)
		}
	}
}

func publishedInitializeRequest() []byte {
	return []byte(`{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"sdk_name":"attest-bench","sdk_version":"0.0.0","protocol_version":1,"required_capabilities":["layers_1_4"],"preferred_encoding":"json"}}`)
}

func publishedShutdownRequest() []byte {
	return []byte(`{"jsonrpc":"2.0","id":9,"method":"shutdown","params":{}}`)
}

// publishedEvaluateRequest builds an evaluate_batch request the released
// engines (v1.0.0-rc.4 and later) accept: a synthetic trace with unique step
// names and a required output object, plus deterministic layer 1-4
// assertions that all pass on it.
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
	// The synthetic generator predates trace-v2 step types, and its step
	// names repeat; the no_duplicates check needs unique names.
	releasedStepType := map[string]string{"inference": "llm_call", "workflow": "agent_call"}
	for i, step := range tr["steps"].([]any) {
		m := step.(map[string]any)
		if mapped, ok := releasedStepType[m["type"].(string)]; ok {
			m["type"] = mapped
		}
		m["name"] = fmt.Sprintf("step_%d", i)
	}

	specs := []struct {
		kind string
		spec map[string]any
	}{
		{"schema", map[string]any{"target": "output.message", "schema": map[string]any{"type": "string"}}},
		{"content", map[string]any{"target": "output.message", "check": "contains", "value": "benchmark"}},
		{"constraint", map[string]any{"field": "steps.length", "operator": "gte", "value": 0}},
		{"trace", map[string]any{"check": "no_duplicates"}},
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
	dirs := newEngineDirs(b)
	b.ReportAllocs()
	for b.Loop() {
		func() {
			e := startPublishedEngine(b, binPath, dirs)
			defer e.close()
			e.call(b, publishedInitializeRequest())
			e.call(b, publishedShutdownRequest())
		}()
	}
}

// BenchmarkPublishedEngineEvaluate measures evaluate_batch roundtrips against
// one live released engine process. The first response is decoded and checked
// outside the timed loop: every assertion must pass.
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
			e := startPublishedEngine(b, binPath, newEngineDirs(b))
			defer e.close()
			e.call(b, publishedInitializeRequest())
			checkEvaluateResponse(b, e.call(b, req), tc.asserts)
			b.ResetTimer()
			for b.Loop() {
				e.call(b, req)
			}
			b.StopTimer()
			e.call(b, publishedShutdownRequest())
		})
	}
}
