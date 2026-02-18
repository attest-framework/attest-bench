package protocol

import (
	"bufio"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"github.com/attest-framework/attest-bench/engine/internal/trace"
)

// BenchmarkSerialization measures marshal+unmarshal round-trip cost for each trace size.
func BenchmarkSerialization(b *testing.B) {
	sizes := []struct {
		name string
		size trace.TraceSize
	}{
		{"small", trace.Small},
		{"medium", trace.Medium},
		{"large", trace.Large},
	}

	for _, tc := range sizes {
		b.Run(tc.name, func(b *testing.B) {
			b.ReportAllocs()
			raw := trace.GenerateSyntheticBatchRequest(42, tc.size)
			b.SetBytes(int64(len(raw)))
			for b.Loop() {
				req, err := UnmarshalRequest(raw)
				if err != nil {
					b.Fatal(err)
				}
				_, err = MarshalRequest(req)
				if err != nil {
					b.Fatal(err)
				}
			}
		})
	}
}

// BenchmarkStdioRoundtrip measures end-to-end latency through Serve via io.Pipe.
func BenchmarkStdioRoundtrip(b *testing.B) {
	sizes := []struct {
		name string
		size trace.TraceSize
	}{
		{"small", trace.Small},
		{"medium", trace.Medium},
		{"large", trace.Large},
	}

	for _, tc := range sizes {
		b.Run(tc.name, func(b *testing.B) {
			b.ReportAllocs()

			// Set up bidirectional pipes: client <-> server.
			clientR, serverW := io.Pipe() // server writes → client reads
			serverR, clientW := io.Pipe() // client writes → server reads

			done := make(chan error, 1)
			go func() {
				done <- Serve(serverR, serverW)
			}()

			// Read the ready signal before benchmarking.
			br := bufio.NewReader(clientR)
			readySig, err := br.ReadBytes('\n')
			if err != nil {
				b.Fatalf("read ready signal: %v", err)
			}
			var ready map[string]bool
			if err := json.Unmarshal(readySig[:len(readySig)-1], &ready); err != nil {
				b.Fatalf("unmarshal ready signal: %v", err)
			}
			if !ready["ready"] {
				b.Fatal("server did not send ready=true")
			}

			raw := trace.GenerateSyntheticBatchRequest(42, tc.size)
			b.SetBytes(int64(len(raw)))

			// Pre-unmarshal the request once; we only benchmark the Serve roundtrip.
			req, err := UnmarshalRequest(raw)
			if err != nil {
				b.Fatalf("unmarshal request: %v", err)
			}

			for b.Loop() {
				wire, err := MarshalRequest(req)
				if err != nil {
					b.Fatal(err)
				}
				if _, err := clientW.Write(wire); err != nil {
					b.Fatal(err)
				}
				if _, err := br.ReadBytes('\n'); err != nil {
					b.Fatal(err)
				}
			}

			clientW.Close()
			<-done
			clientR.Close()
		})
	}
}

// BenchmarkEngineStartup measures time from exec to receiving the ready signal.
func BenchmarkEngineStartup(b *testing.B) {
	b.ReportAllocs()

	// The test binary runs with CWD set to the package directory:
	// .../attest-bench/engine/internal/protocol/
	// The binary lives at .../attest-bench/bin/attest-engine
	cwd, err := os.Getwd()
	if err != nil {
		b.Fatalf("getwd: %v", err)
	}
	binPath := filepath.Join(cwd, "..", "..", "..", "bin", "attest-engine")

	for b.Loop() {
		cmd := exec.Command(binPath, "serve")
		stdout, err := cmd.StdoutPipe()
		if err != nil {
			b.Fatalf("stdout pipe: %v", err)
		}
		if err := cmd.Start(); err != nil {
			b.Fatalf("start engine: %v (build it first with: make engine)", err)
		}

		br := bufio.NewReader(stdout)
		line, err := br.ReadBytes('\n')
		if err != nil {
			cmd.Process.Kill() //nolint:errcheck
			cmd.Wait()         //nolint:errcheck
			b.Fatalf("read ready signal: %v", err)
		}

		var ready map[string]bool
		if err := json.Unmarshal(line[:len(line)-1], &ready); err != nil {
			cmd.Process.Kill() //nolint:errcheck
			cmd.Wait()         //nolint:errcheck
			b.Fatalf("unmarshal ready: %v", err)
		}
		if !ready["ready"] {
			cmd.Process.Kill() //nolint:errcheck
			cmd.Wait()         //nolint:errcheck
			b.Fatalf("expected ready=true, got %v", ready)
		}

		// Shut down cleanly via stdin EOF.
		cmd.Process.Kill() //nolint:errcheck
		cmd.Wait()         //nolint:errcheck
	}
}
