package protocol

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"sync"
	"testing"
	"time"

	"github.com/attest-framework/attest-bench/engine/internal/trace"
)

// BenchmarkSerialization measures marshal+unmarshal round-trip cost for spec step counts.
func BenchmarkSerialization(b *testing.B) {
	sizes := []struct {
		name    string
		steps   int
		asserts int
	}{
		{"10step_5assert", 10, 5},
		{"50step_10assert", 50, 10},
		{"100step_10assert", 100, 10},
		{"500step_20assert", 500, 20},
	}
	for _, tc := range sizes {
		b.Run(tc.name, func(b *testing.B) {
			b.ReportAllocs()
			raw := trace.GenerateEvaluateBatchRequest(42, tc.steps, tc.asserts)
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

// BenchmarkStdioRoundtrip measures end-to-end evaluate_batch latency through Serve via io.Pipe.
func BenchmarkStdioRoundtrip(b *testing.B) {
	sizes := []struct {
		name    string
		steps   int
		asserts int
	}{
		{"10step_5assert", 10, 5},
		{"50step_10assert", 50, 10},
		{"100step_10assert", 100, 10},
		{"500step_20assert", 500, 20},
	}

	for _, tc := range sizes {
		b.Run(tc.name, func(b *testing.B) {
			b.ReportAllocs()

			clientR, serverW := io.Pipe()
			serverR, clientW := io.Pipe()

			done := make(chan error, 1)
			go func() {
				done <- Serve(serverR, serverW)
			}()

			br := bufio.NewReader(clientR)
			// Read ready signal.
			if _, err := br.ReadBytes('\n'); err != nil {
				b.Fatalf("read ready signal: %v", err)
			}

			// Send initialize (outside timer).
			initReq := trace.GenerateInitializeRequest(0)
			if _, err := clientW.Write(initReq); err != nil {
				b.Fatalf("write init: %v", err)
			}
			if _, err := br.ReadBytes('\n'); err != nil {
				b.Fatalf("read init response: %v", err)
			}

			// GenerateEvaluateBatchRequest returns raw JSON without trailing newline.
			raw := trace.GenerateEvaluateBatchRequest(42, tc.steps, tc.asserts)
			b.SetBytes(int64(len(raw)))

			for b.Loop() {
				if _, err := clientW.Write(raw); err != nil {
					b.Fatal(err)
				}
				if _, err := clientW.Write([]byte("\n")); err != nil {
					b.Fatal(err)
				}
				if _, err := br.ReadBytes('\n'); err != nil {
					b.Fatal(err)
				}
			}

			// Send shutdown.
			shutReq := trace.GenerateShutdownRequest(999)
			clientW.Write(shutReq) //nolint:errcheck // Serve may have already exited
			br.ReadBytes('\n')     //nolint:errcheck // read shutdown response
			<-done
			clientR.Close()
			clientW.Close()
		})
	}
}

// BenchmarkInitialize measures the cost of a full initialize handshake.
func BenchmarkInitialize(b *testing.B) {
	b.ReportAllocs()
	for b.Loop() {
		clientR, serverW := io.Pipe()
		serverR, clientW := io.Pipe()
		done := make(chan error, 1)
		go func() { done <- Serve(serverR, serverW) }()
		br := bufio.NewReader(clientR)
		br.ReadBytes('\n') //nolint:errcheck // ready signal

		initReq := trace.GenerateInitializeRequest(1)
		clientW.Write(initReq) //nolint:errcheck
		br.ReadBytes('\n')     //nolint:errcheck // init response

		shutReq := trace.GenerateShutdownRequest(2)
		clientW.Write(shutReq) //nolint:errcheck
		br.ReadBytes('\n')     //nolint:errcheck
		<-done
		clientR.Close()
		clientW.Close()
	}
}

// BenchmarkShutdown measures the full lifecycle cost with focus on shutdown.
func BenchmarkShutdown(b *testing.B) {
	b.ReportAllocs()
	for b.Loop() {
		clientR, serverW := io.Pipe()
		serverR, clientW := io.Pipe()
		done := make(chan error, 1)
		go func() { done <- Serve(serverR, serverW) }()
		br := bufio.NewReader(clientR)
		br.ReadBytes('\n') //nolint:errcheck // ready

		initReq := trace.GenerateInitializeRequest(1)
		clientW.Write(initReq) //nolint:errcheck
		br.ReadBytes('\n')     //nolint:errcheck // init response

		shutReq := trace.GenerateShutdownRequest(2)
		clientW.Write(shutReq) //nolint:errcheck
		br.ReadBytes('\n')     //nolint:errcheck // shutdown response
		<-done
		clientR.Close()
		clientW.Close()
	}
}

// BenchmarkSubprocessRoundtrip measures full lifecycle through a real subprocess.
func BenchmarkSubprocessRoundtrip(b *testing.B) {
	cwd, err := os.Getwd()
	if err != nil {
		b.Fatalf("getwd: %v", err)
	}
	binPath := filepath.Join(cwd, "..", "..", "..", "bin", "attest-engine")

	sizes := []struct {
		name    string
		steps   int
		asserts int
	}{
		{"10step_5assert", 10, 5},
		{"100step_10assert", 100, 10},
		{"xl_500step_20assert", 500, 20},
	}

	for _, tc := range sizes {
		b.Run(tc.name, func(b *testing.B) {
			b.ReportAllocs()
			raw := trace.GenerateEvaluateBatchRequest(42, tc.steps, tc.asserts)

			for b.Loop() {
				cmd := exec.Command(binPath, "serve")
				stdin, err := cmd.StdinPipe()
				if err != nil {
					b.Fatalf("stdin pipe: %v", err)
				}
				stdout, err := cmd.StdoutPipe()
				if err != nil {
					b.Fatalf("stdout pipe: %v", err)
				}
				if err := cmd.Start(); err != nil {
					b.Fatalf("start engine: %v (build it first with: make engine)", err)
				}

				br := bufio.NewReader(stdout)
				br.ReadBytes('\n') //nolint:errcheck // ready signal

				// Initialize.
				stdin.Write(trace.GenerateInitializeRequest(1)) //nolint:errcheck
				br.ReadBytes('\n')                              //nolint:errcheck

				// EvaluateBatch.
				stdin.Write(raw)          //nolint:errcheck
				stdin.Write([]byte("\n")) //nolint:errcheck
				br.ReadBytes('\n')        //nolint:errcheck

				// Shutdown.
				stdin.Write(trace.GenerateShutdownRequest(3)) //nolint:errcheck
				br.ReadBytes('\n')                            //nolint:errcheck
				cmd.Wait()                                    //nolint:errcheck
			}
		})
	}
}

// BenchmarkEngineStartup measures cold start to first initialize response.
func BenchmarkEngineStartup(b *testing.B) {
	b.ReportAllocs()
	cwd, err := os.Getwd()
	if err != nil {
		b.Fatalf("getwd: %v", err)
	}
	binPath := filepath.Join(cwd, "..", "..", "..", "bin", "attest-engine")

	for b.Loop() {
		cmd := exec.Command(binPath, "serve")
		stdin, err := cmd.StdinPipe()
		if err != nil {
			b.Fatalf("stdin pipe: %v", err)
		}
		stdout, err := cmd.StdoutPipe()
		if err != nil {
			b.Fatalf("stdout pipe: %v", err)
		}
		if err := cmd.Start(); err != nil {
			b.Fatalf("start engine: %v (build it first with: make engine)", err)
		}

		br := bufio.NewReader(stdout)
		br.ReadBytes('\n') //nolint:errcheck // ready signal

		// Send initialize and measure to response.
		stdin.Write(trace.GenerateInitializeRequest(1)) //nolint:errcheck
		line, readErr := br.ReadBytes('\n')
		if readErr != nil {
			cmd.Process.Kill() //nolint:errcheck
			cmd.Wait()         //nolint:errcheck
			b.Fatalf("read init response: %v", readErr)
		}

		var resp Response
		if err := json.Unmarshal(line[:len(line)-1], &resp); err != nil {
			cmd.Process.Kill() //nolint:errcheck
			cmd.Wait()         //nolint:errcheck
			b.Fatalf("unmarshal init response: %v", err)
		}

		// Clean shutdown.
		stdin.Write(trace.GenerateShutdownRequest(2)) //nolint:errcheck
		br.ReadBytes('\n')                            //nolint:errcheck
		cmd.Wait()                                    //nolint:errcheck
	}
}

// BenchmarkConcurrentSessions runs two in-process Serve instances concurrently
// with evaluate_batch requests.
func BenchmarkConcurrentSessions(b *testing.B) {
	b.ReportAllocs()

	raw := trace.GenerateEvaluateBatchRequest(42, 50, 10) // medium size

	for b.Loop() {
		type session struct {
			clientR *io.PipeReader
			clientW *io.PipeWriter
			br      *bufio.Reader
			done    chan error
		}

		startSession := func() session {
			clientR, serverW := io.Pipe()
			serverR, clientW := io.Pipe()
			done := make(chan error, 1)
			go func() { done <- Serve(serverR, serverW) }()
			br := bufio.NewReader(clientR)
			br.ReadBytes('\n')                              //nolint:errcheck // ready
			clientW.Write(trace.GenerateInitializeRequest(1)) //nolint:errcheck
			br.ReadBytes('\n')                              //nolint:errcheck // init response
			return session{clientR: clientR, clientW: clientW, br: br, done: done}
		}

		s1 := startSession()
		s2 := startSession()

		var wg sync.WaitGroup
		wg.Add(2)

		doRequests := func(s session) {
			defer wg.Done()
			for i := 0; i < 10; i++ {
				s.clientW.Write(raw)          //nolint:errcheck
				s.clientW.Write([]byte("\n")) //nolint:errcheck
				s.br.ReadBytes('\n')          //nolint:errcheck
			}
		}

		go doRequests(s1)
		go doRequests(s2)
		wg.Wait()

		// Shutdown both sessions.
		for _, s := range []session{s1, s2} {
			s.clientW.Write(trace.GenerateShutdownRequest(999)) //nolint:errcheck
			s.br.ReadBytes('\n')                                //nolint:errcheck
			<-s.done
			s.clientR.Close()
			s.clientW.Close()
		}
	}
}

// BenchmarkSerializationScaling measures json round-trip cost across increasing step counts.
func BenchmarkSerializationScaling(b *testing.B) {
	steps := []int{10, 50, 100, 250, 500, 1000}
	for _, n := range steps {
		b.Run(fmt.Sprintf("%d_steps", n), func(b *testing.B) {
			b.ReportAllocs()
			tr := trace.GenerateSyntheticTraceN(42, n)
			raw, err := json.Marshal(tr)
			if err != nil {
				b.Fatal(err)
			}
			b.SetBytes(int64(len(raw)))
			b.ReportMetric(float64(len(raw))/1024.0, "json_kb")
			for b.Loop() {
				var out trace.Trace
				if err := json.Unmarshal(raw, &out); err != nil {
					b.Fatal(err)
				}
				if _, err := json.Marshal(&out); err != nil {
					b.Fatal(err)
				}
			}
		})
	}
}

// BenchmarkConcurrentSessions_Scaled runs parameterized concurrent Serve
// instances (2, 5, 10 sessions) with per-request latency percentile reporting.
func BenchmarkConcurrentSessions_Scaled(b *testing.B) {
	sessionCounts := []int{2, 5, 10}
	raw := trace.GenerateEvaluateBatchRequest(42, 50, 10) // medium size

	for _, numSessions := range sessionCounts {
		b.Run(fmt.Sprintf("%d_sessions", numSessions), func(b *testing.B) {
			b.ReportAllocs()

			for b.Loop() {
				type session struct {
					clientR *io.PipeReader
					clientW *io.PipeWriter
					br      *bufio.Reader
					done    chan error
				}

				startSession := func() session {
					clientR, serverW := io.Pipe()
					serverR, clientW := io.Pipe()
					done := make(chan error, 1)
					go func() { done <- Serve(serverR, serverW) }()
					br := bufio.NewReader(clientR)
					br.ReadBytes('\n')                                //nolint:errcheck // ready
					clientW.Write(trace.GenerateInitializeRequest(1)) //nolint:errcheck
					br.ReadBytes('\n')                                //nolint:errcheck // init response
					return session{clientR: clientR, clientW: clientW, br: br, done: done}
				}

				sessions := make([]session, numSessions)
				for i := range sessions {
					sessions[i] = startSession()
				}

				var mu sync.Mutex
				var allLatencies []time.Duration
				var wg sync.WaitGroup
				wg.Add(numSessions)

				for _, s := range sessions {
					go func(s session) {
						defer wg.Done()
						for i := 0; i < 10; i++ {
							start := time.Now()
							s.clientW.Write(raw)          //nolint:errcheck
							s.clientW.Write([]byte("\n")) //nolint:errcheck
							s.br.ReadBytes('\n')          //nolint:errcheck
							d := time.Since(start)
							mu.Lock()
							allLatencies = append(allLatencies, d)
							mu.Unlock()
						}
					}(s)
				}
				wg.Wait()

				// Report percentiles across all sessions.
				sort.Slice(allLatencies, func(i, j int) bool { return allLatencies[i] < allLatencies[j] })
				p50 := percentile(allLatencies, 0.50)
				p99 := percentile(allLatencies, 0.99)
				b.ReportMetric(float64(p50.Microseconds()), "p50_µs")
				b.ReportMetric(float64(p99.Microseconds()), "p99_µs")
				if p50 > 0 {
					b.ReportMetric(float64(p99)/float64(p50), "p99/p50_ratio")
				}

				// Shutdown all sessions.
				for _, s := range sessions {
					s.clientW.Write(trace.GenerateShutdownRequest(999)) //nolint:errcheck
					s.br.ReadBytes('\n')                                //nolint:errcheck
					<-s.done
					s.clientR.Close()
					s.clientW.Close()
				}
			}
		})
	}
}

// BenchmarkSustainedLoad measures latency distribution over a long-lived Serve
// instance to surface GC pressure and heap accumulation effects.
func BenchmarkSustainedLoad(b *testing.B) {
	clientR, serverW := io.Pipe()
	serverR, clientW := io.Pipe()
	done := make(chan error, 1)
	go func() { done <- Serve(serverR, serverW) }()

	br := bufio.NewReader(clientR)
	if _, err := br.ReadBytes('\n'); err != nil {
		b.Fatalf("read ready signal: %v", err)
	}

	// Initialize.
	if _, err := clientW.Write(trace.GenerateInitializeRequest(0)); err != nil {
		b.Fatalf("write init: %v", err)
	}
	if _, err := br.ReadBytes('\n'); err != nil {
		b.Fatalf("read init response: %v", err)
	}

	raw := trace.GenerateEvaluateBatchRequest(42, 100, 10)

	// Warmup — 50 iterations to populate heap.
	for i := 0; i < 50; i++ {
		clientW.Write(raw)          //nolint:errcheck
		clientW.Write([]byte("\n")) //nolint:errcheck
		br.ReadBytes('\n')          //nolint:errcheck
	}

	b.ReportAllocs()
	b.ResetTimer()

	latencies := make([]time.Duration, 0, b.N)
	for b.Loop() {
		start := time.Now()
		clientW.Write(raw)          //nolint:errcheck
		clientW.Write([]byte("\n")) //nolint:errcheck
		br.ReadBytes('\n')          //nolint:errcheck
		latencies = append(latencies, time.Since(start))
	}

	if len(latencies) > 0 {
		sort.Slice(latencies, func(i, j int) bool { return latencies[i] < latencies[j] })
		b.ReportMetric(float64(percentile(latencies, 0.50).Microseconds()), "p50_µs")
		b.ReportMetric(float64(percentile(latencies, 0.95).Microseconds()), "p95_µs")
		b.ReportMetric(float64(percentile(latencies, 0.99).Microseconds()), "p99_µs")
		b.ReportMetric(float64(latencies[len(latencies)-1].Microseconds()), "max_µs")
	}

	// Shutdown.
	shutReq := trace.GenerateShutdownRequest(999)
	clientW.Write(shutReq) //nolint:errcheck
	br.ReadBytes('\n')     //nolint:errcheck
	<-done
	clientR.Close()
	clientW.Close()
}
