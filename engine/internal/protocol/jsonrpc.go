package protocol

import (
	"encoding/json"
	"fmt"
)

const JSONRPCVersion = "2.0"

const (
	ParseError     = -32700
	InvalidRequest = -32600
	MethodNotFound = -32601
	InvalidParams  = -32602
	InternalError  = -32603
)

type Request struct {
	Jsonrpc string          `json:"jsonrpc"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
	ID      any             `json:"id"`
}

type Response struct {
	Jsonrpc string          `json:"jsonrpc"`
	Result  json.RawMessage `json:"result,omitempty"`
	Error   *RPCError       `json:"error,omitempty"`
	ID      any             `json:"id"`
}

type RPCError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
	Data    any    `json:"data,omitempty"`
}

func MarshalRequest(req *Request) ([]byte, error) {
	b, err := json.Marshal(req)
	if err != nil {
		return nil, err
	}
	return append(b, '\n'), nil
}

func MarshalResponse(resp *Response) ([]byte, error) {
	b, err := json.Marshal(resp)
	if err != nil {
		return nil, err
	}
	return append(b, '\n'), nil
}

func UnmarshalRequest(data []byte) (*Request, error) {
	var req Request
	if err := json.Unmarshal(data, &req); err != nil {
		return nil, err
	}
	if req.Jsonrpc != JSONRPCVersion {
		return nil, fmt.Errorf("invalid jsonrpc version: %q", req.Jsonrpc)
	}
	return &req, nil
}

func UnmarshalResponse(data []byte) (*Response, error) {
	var resp Response
	if err := json.Unmarshal(data, &resp); err != nil {
		return nil, err
	}
	if resp.Jsonrpc != JSONRPCVersion {
		return nil, fmt.Errorf("invalid jsonrpc version: %q", resp.Jsonrpc)
	}
	return &resp, nil
}

func NewErrorResponse(id any, code int, msg string) *Response {
	return &Response{
		Jsonrpc: JSONRPCVersion,
		Error: &RPCError{
			Code:    code,
			Message: msg,
		},
		ID: id,
	}
}

type InitializeParams struct {
	SDKVersion   string   `json:"sdk_version"`
	SDKLanguage  string   `json:"sdk_language"`
	Capabilities []string `json:"capabilities,omitempty"`
}

type InitializeResult struct {
	EngineVersion string   `json:"engine_version"`
	Capabilities  []string `json:"capabilities"`
	Compatible    bool     `json:"compatible"`
}

type EvaluateBatchParams struct {
	Trace      json.RawMessage `json:"trace"`
	Assertions []Assertion     `json:"assertions"`
}

type Assertion struct {
	ID         string          `json:"assertion_id"`
	Type       string          `json:"type"`
	Level      int             `json:"level"`
	Parameters json.RawMessage `json:"parameters"`
}

type AssertionResult struct {
	AssertionID string `json:"assertion_id"`
	Status      string `json:"status"`
	DurationNs  int64  `json:"duration_ns"`
}

type EvaluateBatchResult struct {
	Results []AssertionResult `json:"results"`
}

type ShutdownResult struct {
	Status string `json:"status"`
}
