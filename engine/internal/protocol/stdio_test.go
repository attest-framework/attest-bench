package protocol

import (
	"bufio"
	"bytes"
	"encoding/json"
	"io"
	"testing"
)

// serveOnce runs Serve in a goroutine and returns reader/writer ends and a
// done channel that closes when Serve returns.
func serveSetup(t *testing.T) (pw *io.PipeWriter, pr *io.PipeReader, done chan error) {
	t.Helper()
	clientR, serverW := io.Pipe() // client reads, server writes
	serverR, clientW := io.Pipe() // server reads, client writes
	done = make(chan error, 1)
	go func() {
		done <- Serve(serverR, serverW)
	}()
	return clientW, clientR, done
}

// readLine reads exactly one newline-terminated line from r.
func readLine(t *testing.T, r io.Reader) []byte {
	t.Helper()
	br := bufio.NewReader(r)
	line, err := br.ReadBytes('\n')
	if err != nil {
		t.Fatalf("readLine: %v", err)
	}
	return line
}

// sendRequest marshals and writes a request to w.
func sendRequest(t *testing.T, w io.Writer, req *Request) {
	t.Helper()
	b, err := MarshalRequest(req)
	if err != nil {
		t.Fatalf("MarshalRequest: %v", err)
	}
	if _, err := w.Write(b); err != nil {
		t.Fatalf("write request: %v", err)
	}
}

// TestServeReadySignal verifies that the first line written by Serve is {"ready":true}.
func TestServeReadySignal(t *testing.T) {
	clientW, clientR, done := serveSetup(t)

	line := readLine(t, clientR)
	var m map[string]bool
	if err := json.Unmarshal(bytes.TrimRight(line, "\n"), &m); err != nil {
		t.Fatalf("unmarshal ready signal: %v", err)
	}
	if !m["ready"] {
		t.Errorf("expected ready=true, got %v", m)
	}

	clientW.Close()
	<-done
}

// TestServePing sends a ping and verifies the pong response.
func TestServePing(t *testing.T) {
	clientW, clientR, done := serveSetup(t)

	// Consume ready signal.
	readLine(t, clientR)

	req := &Request{
		Jsonrpc: JSONRPCVersion,
		Method:  "ping",
		ID:      1,
	}
	sendRequest(t, clientW, req)

	line := readLine(t, clientR)
	resp, err := UnmarshalResponse(bytes.TrimRight(line, "\n"))
	if err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if resp.Error != nil {
		t.Fatalf("unexpected error: %v", resp.Error)
	}
	var result map[string]bool
	if err := json.Unmarshal(resp.Result, &result); err != nil {
		t.Fatalf("unmarshal result: %v", err)
	}
	if !result["pong"] {
		t.Errorf("expected pong=true, got %v", result)
	}

	clientW.Close()
	<-done
}

// TestServeRoundtrip sends a trace.submit request and verifies status ok.
func TestServeRoundtrip(t *testing.T) {
	clientW, clientR, done := serveSetup(t)

	// Consume ready signal.
	readLine(t, clientR)

	params, _ := json.Marshal(map[string]string{"trace_id": "test-trace-42"})
	req := &Request{
		Jsonrpc: JSONRPCVersion,
		Method:  "trace.submit",
		Params:  json.RawMessage(params),
		ID:      2,
	}
	sendRequest(t, clientW, req)

	line := readLine(t, clientR)
	resp, err := UnmarshalResponse(bytes.TrimRight(line, "\n"))
	if err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if resp.Error != nil {
		t.Fatalf("unexpected error: %v", resp.Error)
	}
	var result map[string]string
	if err := json.Unmarshal(resp.Result, &result); err != nil {
		t.Fatalf("unmarshal result: %v", err)
	}
	if result["status"] != "ok" {
		t.Errorf("expected status=ok, got %q", result["status"])
	}
	if result["trace_id"] != "test-trace-42" {
		t.Errorf("expected trace_id=test-trace-42, got %q", result["trace_id"])
	}

	clientW.Close()
	<-done
}

// TestServeUnknownMethod verifies that an unknown method returns MethodNotFound.
func TestServeUnknownMethod(t *testing.T) {
	clientW, clientR, done := serveSetup(t)

	// Consume ready signal.
	readLine(t, clientR)

	req := &Request{
		Jsonrpc: JSONRPCVersion,
		Method:  "no.such.method",
		ID:      3,
	}
	sendRequest(t, clientW, req)

	line := readLine(t, clientR)
	resp, err := UnmarshalResponse(bytes.TrimRight(line, "\n"))
	if err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if resp.Error == nil {
		t.Fatal("expected error response, got nil error")
	}
	if resp.Error.Code != MethodNotFound {
		t.Errorf("expected MethodNotFound (%d), got %d", MethodNotFound, resp.Error.Code)
	}

	clientW.Close()
	<-done
}

// TestServeMalformedJSON verifies that malformed JSON returns ParseError and the loop continues.
func TestServeMalformedJSON(t *testing.T) {
	clientW, clientR, done := serveSetup(t)

	// Consume ready signal.
	readLine(t, clientR)

	// Send garbage.
	if _, err := io.WriteString(clientW, "not valid json\n"); err != nil {
		t.Fatalf("write garbage: %v", err)
	}

	line := readLine(t, clientR)
	resp, err := UnmarshalResponse(bytes.TrimRight(line, "\n"))
	if err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if resp.Error == nil {
		t.Fatal("expected error response, got nil error")
	}
	if resp.Error.Code != ParseError {
		t.Errorf("expected ParseError (%d), got %d", ParseError, resp.Error.Code)
	}

	// Verify the loop continues by sending a valid ping.
	req := &Request{
		Jsonrpc: JSONRPCVersion,
		Method:  "ping",
		ID:      4,
	}
	sendRequest(t, clientW, req)

	line = readLine(t, clientR)
	resp2, err := UnmarshalResponse(bytes.TrimRight(line, "\n"))
	if err != nil {
		t.Fatalf("unmarshal ping response: %v", err)
	}
	if resp2.Error != nil {
		t.Fatalf("unexpected error after recovery: %v", resp2.Error)
	}

	clientW.Close()
	<-done
}

// TestServeEOF verifies that closing the reader causes Serve to return nil.
func TestServeEOF(t *testing.T) {
	clientW, clientR, done := serveSetup(t)

	// Consume ready signal.
	readLine(t, clientR)

	// Close the write end (server sees EOF).
	clientW.Close()

	if err := <-done; err != nil {
		t.Errorf("expected Serve to return nil on EOF, got %v", err)
	}
	clientR.Close()
}

// TestMarshalUnmarshalRoundtrip verifies marshal/unmarshal symmetry for Request.
func TestMarshalUnmarshalRoundtrip(t *testing.T) {
	params, _ := json.Marshal(map[string]string{"key": "value"})
	original := &Request{
		Jsonrpc: JSONRPCVersion,
		Method:  "trace.submit",
		Params:  json.RawMessage(params),
		ID:      99,
	}

	b, err := MarshalRequest(original)
	if err != nil {
		t.Fatalf("MarshalRequest: %v", err)
	}

	decoded, err := UnmarshalRequest(bytes.TrimRight(b, "\n"))
	if err != nil {
		t.Fatalf("UnmarshalRequest: %v", err)
	}

	if decoded.Method != original.Method {
		t.Errorf("method mismatch: %q != %q", decoded.Method, original.Method)
	}
	if decoded.Jsonrpc != original.Jsonrpc {
		t.Errorf("jsonrpc mismatch: %q != %q", decoded.Jsonrpc, original.Jsonrpc)
	}
	if string(decoded.Params) != string(original.Params) {
		t.Errorf("params mismatch: %q != %q", decoded.Params, original.Params)
	}
}
