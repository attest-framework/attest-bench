package main

import (
	"bufio"
	"fmt"
	"math"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

type target struct {
	benchName string
	label     string
	targetNs  int64
	ceilingNs int64
}

type benchResult struct {
	name    string
	nsPerOp []float64
	custom  map[string][]float64
}

var targets = []target{
	{"BenchmarkStdioRoundtrip/10step_5assert", "Small EvaluateBatch", 3_000_000, 5_000_000},
	{"BenchmarkStdioRoundtrip/50step_10assert", "Medium EvaluateBatch", 5_000_000, 10_000_000},
	{"BenchmarkStdioRoundtrip/100step_10assert", "Large EvaluateBatch", 5_000_000, 10_000_000},
	{"BenchmarkStdioRoundtrip/500step_20assert", "XL EvaluateBatch", 15_000_000, 30_000_000},
	{"BenchmarkEngineStartup", "Engine cold start", 500_000_000, 1_000_000_000},
}

var (
	benchLineRe  = regexp.MustCompile(`^(Benchmark\S+)\s+(\d+)\s+(\d+(?:\.\d+)?)\s+ns/op`)
	cpuSuffixRe  = regexp.MustCompile(`-\d+$`)
	customMetric = regexp.MustCompile(`(\d+(?:\.\d+)?)\s+(p50_us|p95_us|p99_us|json_kb)`)
	stepsRe      = regexp.MustCompile(`(\d+)step`)
	assertsRe    = regexp.MustCompile(`(\d+)assert`)
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintf(os.Stderr, "usage: bench-report <results-file>\n")
		os.Exit(2)
	}

	path := os.Args[1]
	results, err := parseFile(path)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(2)
	}

	exitCode := renderReport(path, results)
	os.Exit(exitCode)
}

func parseFile(path string) (map[string]*benchResult, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open %s: %w", path, err)
	}
	defer f.Close()

	results := make(map[string]*benchResult)
	scanner := bufio.NewScanner(f)

	for scanner.Scan() {
		line := scanner.Text()
		m := benchLineRe.FindStringSubmatch(line)
		if m == nil {
			continue
		}

		rawName := m[1]
		name := cpuSuffixRe.ReplaceAllString(rawName, "")

		nsOp, err := strconv.ParseFloat(m[3], 64)
		if err != nil {
			continue
		}

		br, ok := results[name]
		if !ok {
			br = &benchResult{
				name:   name,
				custom: make(map[string][]float64),
			}
			results[name] = br
		}
		br.nsPerOp = append(br.nsPerOp, nsOp)

		customs := customMetric.FindAllStringSubmatch(line, -1)
		for _, cm := range customs {
			val, err := strconv.ParseFloat(cm[1], 64)
			if err != nil {
				continue
			}
			br.custom[cm[2]] = append(br.custom[cm[2]], val)
		}
	}

	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("scan %s: %w", path, err)
	}

	return results, nil
}

func median(vals []float64) float64 {
	if len(vals) == 0 {
		return math.NaN()
	}
	sorted := make([]float64, len(vals))
	copy(sorted, vals)
	sort.Float64s(sorted)
	n := len(sorted)
	if n%2 == 0 {
		return (sorted[n/2-1] + sorted[n/2]) / 2
	}
	return sorted[n/2]
}

func nsToMs(ns float64) string {
	return fmt.Sprintf("%.2fms", ns/1_000_000)
}

func status(actualNs float64, t target) string {
	if actualNs <= float64(t.targetNs) {
		return "PASS"
	}
	if actualNs <= float64(t.ceilingNs) {
		return "WARN"
	}
	return "FAIL"
}

func extractStepsAsserts(benchName string) (string, string) {
	steps := "—"
	asserts := "—"
	if m := stepsRe.FindStringSubmatch(benchName); m != nil {
		steps = m[1]
	}
	if m := assertsRe.FindStringSubmatch(benchName); m != nil {
		asserts = m[1]
	}
	return steps, asserts
}

func renderReport(path string, results map[string]*benchResult) int {
	filename := path
	if idx := strings.LastIndex(path, "/"); idx >= 0 {
		filename = path[idx+1:]
	}

	fmt.Println("# Protocol Benchmark Report")
	fmt.Println()
	fmt.Printf("Generated: %s\n", time.Now().Format("2006-01-02 15:04:05"))
	fmt.Printf("Source: %s\n", filename)
	fmt.Println()

	// Protocol Roundtrip Latency table
	fmt.Println("## Protocol Roundtrip Latency")
	fmt.Println()
	fmt.Println("| Benchmark | Steps | Assertions | Target | Hard Ceiling | Actual (median) | Status |")
	fmt.Println("|-----------|-------|------------|--------|-------------|-----------------|--------|")

	hasFail := false
	allBelowTarget := true
	noCeilingBreach := true
	engineColdStartOk := true

	for _, t := range targets {
		steps, asserts := extractStepsAsserts(t.benchName)
		br, ok := results[t.benchName]

		var actualStr, statusStr string
		if !ok || len(br.nsPerOp) == 0 {
			actualStr = "N/A"
			statusStr = "N/A"
		} else {
			med := median(br.nsPerOp)
			actualStr = nsToMs(med)
			statusStr = status(med, t)
			if statusStr == "FAIL" {
				hasFail = true
				noCeilingBreach = false
			}
			if statusStr != "PASS" {
				allBelowTarget = false
			}
			if t.benchName == "BenchmarkEngineStartup" && med > float64(t.targetNs) {
				engineColdStartOk = false
			}
		}

		if statusStr == "N/A" {
			allBelowTarget = false
			if t.benchName == "BenchmarkEngineStartup" {
				engineColdStartOk = false
			}
		}

		fmt.Printf("| %s | %s | %s | <%s | %s | %s | %s |\n",
			t.label, steps, asserts,
			nsToMs(float64(t.targetNs)),
			nsToMs(float64(t.ceilingNs)),
			actualStr, statusStr)
	}
	fmt.Println()

	// Percentile Latency table — only if any result has percentile data
	hasPercentile := false
	for _, br := range results {
		if len(br.custom["p50_us"]) > 0 || len(br.custom["p95_us"]) > 0 || len(br.custom["p99_us"]) > 0 {
			hasPercentile = true
			break
		}
	}

	if hasPercentile {
		fmt.Println("## Percentile Latency")
		fmt.Println()
		fmt.Println("| Benchmark | p50 | p95 | p99 |")
		fmt.Println("|-----------|-----|-----|-----|")

		// Iterate in a stable order by collecting and sorting names
		var names []string
		for name, br := range results {
			if len(br.custom["p50_us"]) > 0 || len(br.custom["p95_us"]) > 0 || len(br.custom["p99_us"]) > 0 {
				names = append(names, name)
			}
		}
		sort.Strings(names)

		for _, name := range names {
			br := results[name]
			p50 := fmtPercentile(br.custom["p50_us"])
			p95 := fmtPercentile(br.custom["p95_us"])
			p99 := fmtPercentile(br.custom["p99_us"])
			fmt.Printf("| %s | %s | %s | %s |\n", name, p50, p95, p99)
		}
		fmt.Println()
	}

	// Serialization Scaling table — look for BenchmarkSerialization results
	var serNames []string
	for name := range results {
		if strings.HasPrefix(name, "BenchmarkSerialization/") {
			serNames = append(serNames, name)
		}
	}
	sort.Strings(serNames)

	if len(serNames) > 0 {
		fmt.Println("## Serialization Scaling")
		fmt.Println()
		fmt.Println("| Benchmark | Payload Size | ns/op |")
		fmt.Println("|-----------|-------------|-------|")

		for _, name := range serNames {
			br := results[name]
			med := median(br.nsPerOp)
			sizePart := name[strings.LastIndex(name, "/")+1:]
			payloadStr := "—"
			if len(br.custom["json_kb"]) > 0 {
				payloadStr = fmt.Sprintf("%.1f KB", median(br.custom["json_kb"]))
			}
			fmt.Printf("| %s | %s | %.0f |\n", sizePart, payloadStr, med)
		}
		fmt.Println()
	}

	// Decision section
	fmt.Println("## Decision")
	fmt.Println()
	fmt.Printf("- [%s] All benchmarks below target: %s\n",
		checkMark(allBelowTarget), criterionStatus(allBelowTarget))
	fmt.Printf("- [%s] No benchmark exceeds hard ceiling: %s\n",
		checkMark(noCeilingBreach), criterionStatus(noCeilingBreach))
	fmt.Printf("- [%s] Engine cold start < 500ms: %s\n",
		checkMark(engineColdStartOk), criterionStatus(engineColdStartOk))
	fmt.Println()

	goNoGo := "PASS"
	if hasFail || !noCeilingBreach {
		goNoGo = "FAIL"
	}
	fmt.Printf("**Go/No-Go: %s**\n", goNoGo)

	if goNoGo == "FAIL" {
		return 1
	}
	return 0
}

func fmtPercentile(vals []float64) string {
	if len(vals) == 0 {
		return "—"
	}
	med := median(vals)
	return fmt.Sprintf("%.0fus", med)
}

func checkMark(ok bool) string {
	if ok {
		return "x"
	}
	return " "
}

func criterionStatus(ok bool) string {
	if ok {
		return "PASS"
	}
	return "FAIL"
}
