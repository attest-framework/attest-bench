package protocol

import (
	"bufio"
	"io"
	"sort"
	"testing"
	"time"

	"github.com/attest-framework/attest-bench/engine/internal/trace"
)

// BenchmarkLatency_StdioRoundtrip collects per-iteration latency and reports
// p50, p95, and p99 percentiles for evaluate_batch requests through Serve.
func BenchmarkLatency_StdioRoundtrip(b *testing.B) {
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
			clientR, serverW := io.Pipe()
			serverR, clientW := io.Pipe()
			done := make(chan error, 1)
			go func() { done <- Serve(serverR, serverW) }()

			br := bufio.NewReader(clientR)
			br.ReadBytes('\n') //nolint:errcheck // ready signal

			// Initialize.
			clientW.Write(trace.GenerateInitializeRequest(0)) //nolint:errcheck
			br.ReadBytes('\n')                                //nolint:errcheck

			// GenerateEvaluateBatchRequest returns raw JSON without trailing newline.
			raw := trace.GenerateEvaluateBatchRequest(42, tc.steps, tc.asserts)

			durations := make([]time.Duration, 0, b.N)

			for b.Loop() {
				start := time.Now()
				clientW.Write(raw)          //nolint:errcheck
				clientW.Write([]byte("\n")) //nolint:errcheck
				br.ReadBytes('\n')          //nolint:errcheck
				durations = append(durations, time.Since(start))
			}

			if len(durations) > 0 {
				sort.Slice(durations, func(i, j int) bool { return durations[i] < durations[j] })
				b.ReportMetric(float64(percentile(durations, 0.50).Microseconds()), "p50_us")
				b.ReportMetric(float64(percentile(durations, 0.95).Microseconds()), "p95_us")
				b.ReportMetric(float64(percentile(durations, 0.99).Microseconds()), "p99_us")
			}

			// Shutdown.
			shutReq := trace.GenerateShutdownRequest(999)
			clientW.Write(shutReq) //nolint:errcheck
			br.ReadBytes('\n')     //nolint:errcheck
			<-done
			clientR.Close()
			clientW.Close()
		})
	}
}

// percentile returns the value at the given percentile from a pre-sorted slice.
func percentile(sorted []time.Duration, p float64) time.Duration {
	if len(sorted) == 0 {
		return 0
	}
	idx := int(float64(len(sorted)-1) * p)
	return sorted[idx]
}
