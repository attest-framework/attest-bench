package trace

// StepType identifies the kind of work a Step represents.
type StepType string

const (
	StepTypeWorkflow  StepType = "workflow"
	StepTypeTool      StepType = "tool_call"
	StepTypeInference StepType = "inference"
)

// Trace is the top-level record emitted by an Attest agent run.
type Trace struct {
	ID       string         `json:"trace_id"`
	Steps    []Step         `json:"steps"`
	Metadata map[string]any `json:"metadata"`
}

// Step is one unit of work inside a Trace.
type Step struct {
	ID        string         `json:"step_id"`
	ParentID  string         `json:"parent_id,omitempty"`
	Name      string         `json:"name"`
	Type      StepType       `json:"type"`
	StartNs   int64          `json:"start_time_ns"`
	EndNs     int64          `json:"end_time_ns"`
	ToolCalls []ToolCall     `json:"tool_calls,omitempty"`
	Result    string         `json:"result,omitempty"`
	Attrs     map[string]any `json:"attributes,omitempty"`
}

// ToolCall records a single external tool invocation within a Step.
type ToolCall struct {
	ID         string         `json:"tool_call_id"`
	Name       string         `json:"name"`
	Input      map[string]any `json:"input"`
	Output     string         `json:"output"`
	DurationNs int64          `json:"duration_ns"`
}
