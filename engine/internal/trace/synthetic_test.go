package trace

import (
	"encoding/json"
	"fmt"
	"testing"
)

// TestSyntheticTraceSize verifies that each size class produces a JSON payload
// within the expected byte-range bounds.
func TestSyntheticTraceSize(t *testing.T) {
	cases := []struct {
		size    TraceSize
		minSize int
		maxSize int
		label   string
	}{
		{Small, 3000, 8000, "Small"},
		{Medium, 15000, 40000, "Medium"},
		{Large, 40000, 150000, "Large"},
		{XL, 150000, 1200000, "XL"},
	}

	for _, tc := range cases {
		t.Run(tc.label, func(t *testing.T) {
			b := GenerateSyntheticBatchRequest(42, tc.size)
			if len(b) < tc.minSize {
				t.Errorf("%s: payload too small: got %d bytes, want >= %d", tc.label, len(b), tc.minSize)
			}
			if len(b) > tc.maxSize {
				t.Errorf("%s: payload too large: got %d bytes, want <= %d", tc.label, len(b), tc.maxSize)
			}
		})
	}
}

// TestSyntheticTraceDeterminism verifies that the same seed + size always
// produces byte-identical output.
func TestSyntheticTraceDeterminism(t *testing.T) {
	sizes := []TraceSize{Small, Medium, Large, XL}
	seeds := []int64{0, 1, 12345, -999, 1<<32 - 1}

	for _, size := range sizes {
		for _, seed := range seeds {
			a := GenerateSyntheticBatchRequest(seed, size)
			b := GenerateSyntheticBatchRequest(seed, size)
			if string(a) != string(b) {
				t.Errorf("seed=%d size=%d: non-deterministic output", seed, size)
			}
		}
	}
}

// TestSyntheticTraceStructure validates that generated traces have well-formed
// IDs, valid parent references, and non-empty tool calls on tool_call steps.
func TestSyntheticTraceStructure(t *testing.T) {
	sizes := []struct {
		size  TraceSize
		label string
	}{
		{Small, "Small"},
		{Medium, "Medium"},
		{Large, "Large"},
		{XL, "XL"},
	}

	for _, tc := range sizes {
		t.Run(tc.label, func(t *testing.T) {
			tr := GenerateSyntheticTrace(77, tc.size)

			if tr.ID == "" {
				t.Fatal("trace ID is empty")
			}
			if len(tr.Steps) == 0 {
				t.Fatal("trace has no steps")
			}

			// Build a set of known step IDs for parent-reference validation.
			stepIDs := make(map[string]struct{}, len(tr.Steps))
			for _, s := range tr.Steps {
				if s.ID == "" {
					t.Errorf("step has empty ID: %+v", s)
				}
				stepIDs[s.ID] = struct{}{}
			}

			for _, s := range tr.Steps {
				// Validate parent reference.
				if s.ParentID != "" {
					if _, ok := stepIDs[s.ParentID]; !ok {
						t.Errorf("step %s has unknown parent_id %s", s.ID, s.ParentID)
					}
				}

				// tool_call steps must have at least one ToolCall.
				if s.Type == StepTypeTool && len(s.ToolCalls) == 0 {
					t.Errorf("tool_call step %s has no tool calls", s.ID)
				}

				// Each ToolCall must have a non-empty ID, name, output.
				for _, tc2 := range s.ToolCalls {
					if tc2.ID == "" {
						t.Errorf("tool call in step %s has empty ID", s.ID)
					}
					if tc2.Name == "" {
						t.Errorf("tool call %s has empty name", tc2.ID)
					}
					if tc2.Output == "" {
						t.Errorf("tool call %s has empty output", tc2.ID)
					}
					if tc2.DurationNs <= 0 {
						t.Errorf("tool call %s has non-positive duration_ns: %d", tc2.ID, tc2.DurationNs)
					}
				}

				// inference steps must carry model attribution in Attrs.
				if s.Type == StepTypeInference {
					if s.Attrs == nil {
						t.Errorf("inference step %s has nil attributes", s.ID)
					} else {
						for _, key := range []string{"model", "input_tokens", "output_tokens", "latency_ms"} {
							if _, ok := s.Attrs[key]; !ok {
								t.Errorf("inference step %s missing attribute %q", s.ID, key)
							}
						}
					}
				}

				// Timestamps must be ordered.
				if s.EndNs <= s.StartNs {
					t.Errorf("step %s: end_time_ns (%d) <= start_time_ns (%d)", s.ID, s.EndNs, s.StartNs)
				}
			}
		})
	}
}

// TestSyntheticBatchRequest verifies the JSON-RPC envelope fields.
func TestSyntheticBatchRequest(t *testing.T) {
	b := GenerateSyntheticBatchRequest(1, Small)

	// Must be valid JSON.
	var raw map[string]any
	if err := json.Unmarshal(b, &raw); err != nil {
		t.Fatalf("batch request is not valid JSON: %v", err)
	}

	// Required top-level keys.
	for _, key := range []string{"jsonrpc", "method", "params", "id"} {
		if _, ok := raw[key]; !ok {
			t.Errorf("batch request missing key %q", key)
		}
	}

	if got, _ := raw["jsonrpc"].(string); got != "2.0" {
		t.Errorf("jsonrpc: want \"2.0\", got %q", got)
	}
	if got, _ := raw["method"].(string); got != "trace.submit" {
		t.Errorf("method: want \"trace.submit\", got %q", got)
	}

	// params must contain a trace object.
	params, ok := raw["params"].(map[string]any)
	if !ok {
		t.Fatalf("params is not an object")
	}
	if _, ok := params["trace"]; !ok {
		t.Error("params missing \"trace\" key")
	}

	// id must be numeric (JSON numbers decode as float64).
	if _, ok := raw["id"].(float64); !ok {
		t.Errorf("id is not a number: %T %v", raw["id"], raw["id"])
	}
}

// TestGenerateSyntheticTraceN verifies exact step count control.
func TestGenerateSyntheticTraceN(t *testing.T) {
	counts := []int{10, 50, 100, 250, 500, 1000}
	for _, n := range counts {
		t.Run(fmt.Sprintf("%d_steps", n), func(t *testing.T) {
			tr := GenerateSyntheticTraceN(42, n)
			if len(tr.Steps) != n {
				t.Errorf("expected %d steps, got %d", n, len(tr.Steps))
			}
		})
	}
}

// TestEvaluateBatchRequest verifies the evaluate_batch JSON-RPC envelope.
func TestEvaluateBatchRequest(t *testing.T) {
	b := GenerateEvaluateBatchRequest(42, 10, 5)
	var raw map[string]any
	if err := json.Unmarshal(b, &raw); err != nil {
		t.Fatalf("not valid JSON: %v", err)
	}
	if got := raw["method"].(string); got != "evaluate_batch" {
		t.Errorf("method: want evaluate_batch, got %q", got)
	}
	params := raw["params"].(map[string]any)
	assertions := params["assertions"].([]any)
	if len(assertions) != 5 {
		t.Errorf("expected 5 assertions, got %d", len(assertions))
	}
}
