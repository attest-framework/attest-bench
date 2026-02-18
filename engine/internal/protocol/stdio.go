package protocol

import (
	"bufio"
	"encoding/json"
	"io"
	"log/slog"
)

func Serve(r io.Reader, w io.Writer) error {
	br := bufio.NewReaderSize(r, 1<<20)
	bw := bufio.NewWriter(w)

	// Signal readiness to subprocess harness.
	if _, err := bw.WriteString("{\"ready\":true}\n"); err != nil {
		return err
	}
	if err := bw.Flush(); err != nil {
		return err
	}

	for {
		line, err := br.ReadBytes('\n')
		if err == io.EOF {
			return nil
		}
		if err != nil {
			slog.Error("read error", "err", err)
			return err
		}

		req, parseErr := UnmarshalRequest(line)
		if parseErr != nil {
			slog.Warn("malformed request", "err", parseErr)
			resp := NewErrorResponse(nil, ParseError, "Parse error")
			writeResponse(bw, resp)
			continue
		}

		var resp *Response
		switch req.Method {
		case "trace.submit":
			traceID := extractTraceID(req.Params)
			result, _ := json.Marshal(map[string]string{
				"status":   "ok",
				"trace_id": traceID,
			})
			resp = &Response{
				Jsonrpc: JSONRPCVersion,
				Result:  json.RawMessage(result),
				ID:      req.ID,
			}
		case "ping":
			result, _ := json.Marshal(map[string]bool{"pong": true})
			resp = &Response{
				Jsonrpc: JSONRPCVersion,
				Result:  json.RawMessage(result),
				ID:      req.ID,
			}
		default:
			resp = NewErrorResponse(req.ID, MethodNotFound, "Method not found")
		}

		writeResponse(bw, resp)
	}
}

func writeResponse(bw *bufio.Writer, resp *Response) {
	b, err := MarshalResponse(resp)
	if err != nil {
		slog.Error("marshal response error", "err", err)
		return
	}
	if _, err := bw.Write(b); err != nil {
		slog.Error("write error", "err", err)
		return
	}
	if err := bw.Flush(); err != nil {
		slog.Error("flush error", "err", err)
	}
}

// extractTraceID pulls the trace_id field from raw JSON params.
// Returns a generated placeholder if absent or unparseable.
func extractTraceID(params json.RawMessage) string {
	if len(params) == 0 {
		return "unknown"
	}
	var p map[string]json.RawMessage
	if err := json.Unmarshal(params, &p); err != nil {
		return "unknown"
	}
	raw, ok := p["trace_id"]
	if !ok {
		return "unknown"
	}
	var id string
	if err := json.Unmarshal(raw, &id); err != nil {
		return "unknown"
	}
	return id
}
