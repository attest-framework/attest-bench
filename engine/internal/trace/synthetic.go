package trace

import (
	"encoding/json"
	"fmt"
	"math/rand"
	"strings"
)

// TraceSize controls the scale of a generated synthetic trace.
type TraceSize int

const (
	Small  TraceSize = iota // ~1 KB : 3–5 steps, 1–2 tool calls
	Medium                  // ~50 KB : 20–50 steps, 10–20 tool calls
	Large                   // ~500 KB : 100–200 steps, 50–100 tool calls
)

var toolNames = []string{
	"search_code",
	"read_file",
	"run_tests",
	"write_file",
	"list_directory",
	"execute_command",
}

var modelNames = []string{
	"claude-opus-4-6",
	"claude-sonnet-4-5",
	"gpt-4.1",
	"gpt-4.1-mini",
}

// sizeParams holds the generation parameters for a given TraceSize.
type sizeParams struct {
	minSteps     int
	maxSteps     int
	minToolCalls int // minimum tool calls per tool_call step
	maxToolCalls int // maximum tool calls per tool_call step
	// textPadding controls how many extra filler sentences are added to
	// result/output strings so Medium and Large traces hit their size targets.
	textPadding int
}

var sizeConfig = map[TraceSize]sizeParams{
	Small:  {3, 5, 1, 2, 0},
	Medium: {20, 50, 1, 2, 8},
	Large:  {100, 200, 1, 2, 30},
}

// GenerateSyntheticTrace produces a deterministic *Trace for the given seed
// and size class. Calling the function twice with the same arguments returns
// bit-for-bit identical results.
func GenerateSyntheticTrace(seed int64, size TraceSize) *Trace {
	rng := rand.New(rand.NewSource(seed)) //nolint:gosec // deterministic, not crypto

	p := sizeConfig[size]
	numSteps := p.minSteps + rng.Intn(p.maxSteps-p.minSteps+1)

	traceID := randomID(rng, "trace")

	steps := make([]Step, numSteps)
	stepIDs := make([]string, numSteps)

	for i := range stepIDs {
		stepIDs[i] = randomID(rng, fmt.Sprintf("step-%d", i))
	}

	// Assign step types: ~40 % workflow, ~30 % tool_call, ~30 % inference.
	stepTypes := make([]StepType, numSteps)
	for i := range stepTypes {
		r := rng.Intn(10)
		switch {
		case r < 4:
			stepTypes[i] = StepTypeWorkflow
		case r < 7:
			stepTypes[i] = StepTypeTool
		default:
			stepTypes[i] = StepTypeInference
		}
	}

	// Guarantee at least one tool_call step.
	hasTool := false
	for _, t := range stepTypes {
		if t == StepTypeTool {
			hasTool = true
			break
		}
	}
	if !hasTool && numSteps > 0 {
		stepTypes[rng.Intn(numSteps)] = StepTypeTool
	}

	baseNs := int64(1_700_000_000_000_000_000)

	for i := range steps {
		startNs := baseNs + int64(i)*int64(5_000_000) + rng.Int63n(1_000_000)
		durationNs := int64(1_000_000) + rng.Int63n(4_000_000)
		endNs := startNs + durationNs

		var parentID string
		if i > 0 {
			parentIdx := rng.Intn(i)
			parentID = stepIDs[parentIdx]
		}

		st := stepTypes[i]
		step := Step{
			ID:       stepIDs[i],
			ParentID: parentID,
			Name:     stepName(rng, st, i),
			Type:     st,
			StartNs:  startNs,
			EndNs:    endNs,
		}

		switch st {
		case StepTypeTool:
			// Every tool_call step gets at least one tool call.
			n := p.minToolCalls + rng.Intn(p.maxToolCalls-p.minToolCalls+1)
			step.ToolCalls = make([]ToolCall, n)
			for j := range step.ToolCalls {
				step.ToolCalls[j] = generateToolCall(rng, i, j, p.textPadding)
			}
			step.Result = generateResultText(rng, p.textPadding)

		case StepTypeInference:
			step.Attrs = map[string]any{
				"model":         modelNames[rng.Intn(len(modelNames))],
				"input_tokens":  100 + rng.Intn(3900),
				"output_tokens": 50 + rng.Intn(950),
				"latency_ms":    200 + rng.Intn(2800),
			}
			step.Result = generateInferenceResult(rng, p.textPadding)

		case StepTypeWorkflow:
			step.Result = generateWorkflowResult(rng, p.textPadding)
		}

		steps[i] = step
	}

	return &Trace{
		ID:    traceID,
		Steps: steps,
		Metadata: map[string]any{
			"generator": "synthetic",
			"seed":      seed,
			"size":      int(size),
			"version":   "1.0",
		},
	}
}

// GenerateSyntheticBatchRequest wraps a generated trace in a JSON-RPC 2.0
// request envelope and returns the marshaled bytes.
func GenerateSyntheticBatchRequest(seed int64, size TraceSize) []byte {
	tr := GenerateSyntheticTrace(seed, size)

	type params struct {
		Trace *Trace `json:"trace"`
	}
	type request struct {
		JSONRPC string `json:"jsonrpc"`
		Method  string `json:"method"`
		Params  params `json:"params"`
		ID      int    `json:"id"`
	}

	req := request{
		JSONRPC: "2.0",
		Method:  "trace.submit",
		Params:  params{Trace: tr},
		ID:      1,
	}

	b, err := json.Marshal(req)
	if err != nil {
		panic(fmt.Sprintf("synthetic: marshal failed: %v", err))
	}
	return b
}

// ── helpers ──────────────────────────────────────────────────────────────────

func randomID(rng *rand.Rand, prefix string) string {
	return fmt.Sprintf("%s-%08x%08x", prefix, rng.Uint32(), rng.Uint32())
}

func generateToolCall(rng *rand.Rand, stepIdx, callIdx, padding int) ToolCall {
	name := toolNames[rng.Intn(len(toolNames))]
	durationNs := int64(500_000) + rng.Int63n(2_000_000)

	return ToolCall{
		ID:         randomID(rng, fmt.Sprintf("tc-%d-%d", stepIdx, callIdx)),
		Name:       name,
		Input:      buildToolInput(rng, name),
		Output:     generateOutputText(rng, name, padding),
		DurationNs: durationNs,
	}
}

func buildToolInput(rng *rand.Rand, toolName string) map[string]any {
	switch toolName {
	case "search_code":
		return map[string]any{
			"query":       randomCodeQuery(rng),
			"file_types":  []string{".go", ".py", ".ts"}[rng.Intn(3)],
			"max_results": 10 + rng.Intn(40),
		}
	case "read_file":
		return map[string]any{
			"path":       randomFilePath(rng),
			"start_line": rng.Intn(100),
			"end_line":   100 + rng.Intn(200),
		}
	case "run_tests":
		return map[string]any{
			"test_pattern": randomTestPattern(rng),
			"timeout_s":    30 + rng.Intn(120),
			"verbose":      rng.Intn(2) == 1,
		}
	case "write_file":
		return map[string]any{
			"path":    randomFilePath(rng),
			"content": generateShortContent(rng),
			"mode":    "overwrite",
		}
	case "list_directory":
		return map[string]any{
			"path":      randomDirPath(rng),
			"recursive": rng.Intn(2) == 1,
			"pattern":   "*.go",
		}
	case "execute_command":
		return map[string]any{
			"command":   randomCommand(rng),
			"timeout_s": 10 + rng.Intn(50),
			"env":       map[string]string{"GOPROXY": "direct"},
		}
	default:
		return map[string]any{"arg": randomID(rng, "v")}
	}
}

// paddedText appends n filler sentences drawn from a pool so that padded
// strings grow linearly with the textPadding parameter.
func paddedText(rng *rand.Rand, base string, n int) string {
	if n == 0 {
		return base
	}
	fillers := []string{
		"Context window usage is within acceptable limits for this operation.",
		"No anomalies detected in the execution trace at this stage.",
		"Memory allocation for intermediate buffers completed successfully.",
		"Cache hit ratio for file reads is 94% over the last 100 operations.",
		"Goroutine pool utilization: 12 of 32 workers active.",
		"Checkpoint verified: SHA-256 hash matches expected digest.",
		"Rate limiter: 0 requests throttled in the last 10 seconds.",
		"Dependency graph resolved with 0 cycles detected.",
		"Input validation passed all 14 schema assertions without error.",
		"Telemetry span flushed to collector at 127.0.0.1:4317.",
	}
	var sb strings.Builder
	sb.WriteString(base)
	for i := 0; i < n; i++ {
		sb.WriteByte(' ')
		sb.WriteString(fillers[rng.Intn(len(fillers))])
	}
	return sb.String()
}

func stepName(rng *rand.Rand, st StepType, idx int) string {
	switch st {
	case StepTypeWorkflow:
		names := []string{
			"initialize_context", "load_configuration", "validate_inputs",
			"orchestrate_subtasks", "aggregate_results", "finalize_output",
			"run_pipeline", "checkpoint_state",
		}
		return names[rng.Intn(len(names))]
	case StepTypeTool:
		return fmt.Sprintf("tool_execution_%d", idx)
	case StepTypeInference:
		names := []string{
			"generate_response", "classify_intent", "summarize_context",
			"plan_next_action", "evaluate_output", "refine_draft",
		}
		return names[rng.Intn(len(names))]
	default:
		return fmt.Sprintf("step_%d", idx)
	}
}

func generateResultText(rng *rand.Rand, padding int) string {
	bases := []string{
		"Tool execution completed successfully. Retrieved 42 matching entries from the codebase index.",
		"Operation finished. The requested file was parsed and all 128 functions were analyzed.",
		"Command exited with status 0. Build artifacts written to /tmp/build/output.",
		"Search returned 17 results across 5 files matching the given query pattern.",
		"File written successfully. SHA-256 checksum verified against expected value.",
		"Directory listing complete. Found 23 Go source files and 4 test files.",
		"Tests passed: 89/89. Coverage: 94.2%. Elapsed: 3.41s.",
		"Execution complete. Stdout captured (1.2 KB), stderr empty.",
	}
	return paddedText(rng, bases[rng.Intn(len(bases))], padding)
}

func generateInferenceResult(rng *rand.Rand, padding int) string {
	bases := []string{
		"Based on the provided context, the most likely root cause is an unhandled nil pointer in the authentication middleware. Recommend adding a guard clause before dereferencing the user object.",
		"Analysis complete. The code change introduces a subtle race condition when multiple goroutines write to the shared map. Use sync.RWMutex or sync.Map to serialize access.",
		"The requested refactoring can be applied safely. Extract the validation logic into a separate ValidateRequest function with the following signature: func ValidateRequest(r *http.Request) error.",
		"Intent classified as: code_review. Confidence: 0.97. The user wants a security audit of the authentication module, focusing on session management and token validation.",
		"Summary generated. The trace contains 47 steps spanning 2.3 seconds of wall time. The largest latency contributor is the database query at step 23 (812ms).",
		"Plan generated. Step 1: read the existing implementation. Step 2: identify the failing assertion. Step 3: apply the minimal fix. Step 4: verify with tests.",
	}
	return paddedText(rng, bases[rng.Intn(len(bases))], padding)
}

func generateWorkflowResult(rng *rand.Rand, padding int) string {
	bases := []string{
		"Workflow stage completed. All prerequisite checks passed. Proceeding to next stage.",
		"Pipeline initialized. Loaded 3 plugins and verified configuration schema.",
		"Subtasks dispatched to 4 worker goroutines. Awaiting completion signals.",
		"Aggregation finished. Merged outputs from 12 parallel steps into unified report.",
		"State checkpoint saved. Progress: 67% complete. Estimated remaining: 1.2s.",
		"Output validation passed all 8 schema assertions. Emitting result to downstream.",
	}
	return paddedText(rng, bases[rng.Intn(len(bases))], padding)
}

func generateOutputText(rng *rand.Rand, toolName string, padding int) string {
	var base string
	switch toolName {
	case "search_code":
		base = fmt.Sprintf("Found %d matches in %d files. Top result: engine/internal/trace/types.go:34 — type Step struct matches query pattern.",
			5+rng.Intn(30), 1+rng.Intn(10))
	case "read_file":
		base = fmt.Sprintf("Read %d lines from %s. File contains package declaration, %d imports, and %d top-level declarations.",
			50+rng.Intn(300), randomFilePath(rng), rng.Intn(20), rng.Intn(15))
	case "run_tests":
		pass := 50 + rng.Intn(200)
		base = fmt.Sprintf("--- PASS\nok  \tgithub.com/attest-framework/attest-bench/engine/internal/trace\t%.3fs\nPassed: %d, Failed: 0, Skipped: %d",
			float64(rng.Intn(500))/100.0, pass, rng.Intn(5))
	case "write_file":
		base = fmt.Sprintf("Wrote %d bytes to disk. inode updated. fsync completed in %dµs.",
			512+rng.Intn(4096), rng.Intn(500))
	case "list_directory":
		base = fmt.Sprintf("engine/\n  internal/\n    trace/\n      types.go (%d B)\n      synthetic.go (%d B)\n  cmd/\n    attest-engine/\n      main.go (%d B)",
			rng.Intn(2000)+500, rng.Intn(5000)+1000, rng.Intn(1000)+200)
	case "execute_command":
		base = fmt.Sprintf("exit status 0\nstdout: go build completed in %.2fs\nstderr: (empty)",
			float64(rng.Intn(300))/100.0)
	default:
		base = fmt.Sprintf("Operation returned result code 0. Processed %d items.", rng.Intn(100))
	}
	return paddedText(rng, base, padding)
}

func generateShortContent(rng *rand.Rand) string {
	snippets := []string{
		"package main\n\nimport \"fmt\"\n\nfunc main() { fmt.Println(\"hello\") }\n",
		"type Config struct {\n\tHost string\n\tPort int\n}\n",
		"func validateInput(s string) error {\n\tif s == \"\" {\n\t\treturn errors.New(\"empty input\")\n\t}\n\treturn nil\n}\n",
	}
	return snippets[rng.Intn(len(snippets))]
}

func randomFilePath(rng *rand.Rand) string {
	dirs := []string{"engine/internal/trace", "engine/cmd/attest-engine", "engine/internal/protocol", "pkg/bench", "testdata"}
	files := []string{"types.go", "synthetic.go", "main.go", "handler.go", "config.go", "util.go"}
	return fmt.Sprintf("%s/%s", dirs[rng.Intn(len(dirs))], files[rng.Intn(len(files))])
}

func randomDirPath(rng *rand.Rand) string {
	dirs := []string{"engine/internal", "engine/cmd", "pkg", "testdata", "."}
	return dirs[rng.Intn(len(dirs))]
}

func randomCodeQuery(rng *rand.Rand) string {
	queries := []string{
		"func GenerateSyntheticTrace",
		"type Trace struct",
		"json.Marshal",
		"rand.New(rand.NewSource",
		"http.HandleFunc",
		"sync.RWMutex",
	}
	return queries[rng.Intn(len(queries))]
}

func randomTestPattern(rng *rand.Rand) string {
	patterns := []string{
		"./...",
		"./engine/internal/trace/...",
		"./engine/...",
		"TestSynthetic",
		"TestProtocol",
	}
	return patterns[rng.Intn(len(patterns))]
}

func randomCommand(rng *rand.Rand) string {
	cmds := []string{
		"go build ./...",
		"go test ./... -race",
		"go vet ./...",
		"gofmt -l .",
		"golangci-lint run",
	}
	return cmds[rng.Intn(len(cmds))]
}
