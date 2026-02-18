BINARY     := bin/attest-engine
CMD        := ./engine/cmd/attest-engine
BENCH_PKG  := ./internal/protocol/
BENCH_TIME := -benchtime=5s
BENCH_RUN  := -count=10 -cpu=1 -benchmem

.PHONY: engine engine-profile bench-serial bench-protocol bench-startup bench-all bench-init bench-shutdown bench-subprocess bench-concurrent bench-concurrent-scaled bench-scaling bench-latency bench-sustained bench-codec bench-profile-allocs bench-full bench-report compare report clean

engine:
	CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o $(BINARY) $(CMD)

engine-profile:
	CGO_ENABLED=0 go build -trimpath -o $(BINARY) $(CMD)

bench-serial:
	cd engine && go test $(BENCH_PKG) -run='^$$' -bench=BenchmarkSerialization $(BENCH_TIME) $(BENCH_RUN)

bench-protocol: engine
	cd engine && go test $(BENCH_PKG) -run='^$$' -bench=BenchmarkStdioRoundtrip $(BENCH_TIME) $(BENCH_RUN)

bench-startup: engine
	cd engine && go test $(BENCH_PKG) -run='^$$' -bench=BenchmarkEngineStartup $(BENCH_TIME) $(BENCH_RUN)

bench-all: engine
	cd engine && go test $(BENCH_PKG) -run='^$$' -bench=. $(BENCH_TIME) $(BENCH_RUN) | tee ../results/bench-$$(date +%Y%m%d-%H%M%S).txt

bench-init:
	cd engine && go test $(BENCH_PKG) -run='^$$' -bench=BenchmarkInitialize $(BENCH_TIME) $(BENCH_RUN)

bench-shutdown:
	cd engine && go test $(BENCH_PKG) -run='^$$' -bench=BenchmarkShutdown $(BENCH_TIME) $(BENCH_RUN)

bench-subprocess: engine
	cd engine && go test $(BENCH_PKG) -run='^$$' -bench=BenchmarkSubprocessRoundtrip $(BENCH_TIME) $(BENCH_RUN)

bench-concurrent: engine
	cd engine && go test $(BENCH_PKG) -run='^$$' -bench=BenchmarkConcurrentSessions $(BENCH_TIME) $(BENCH_RUN)

bench-concurrent-scaled: engine
	cd engine && go test $(BENCH_PKG) -run='^$$' -bench=BenchmarkConcurrentSessions_Scaled $(BENCH_TIME) $(BENCH_RUN)

bench-scaling:
	cd engine && go test $(BENCH_PKG) -run='^$$' -bench=BenchmarkSerializationScaling $(BENCH_TIME) $(BENCH_RUN)

bench-latency: engine
	cd engine && go test $(BENCH_PKG) -run='^$$' -bench=BenchmarkLatency -benchtime=10s -count=5 -cpu=1 -benchmem

bench-sustained:
	cd engine && go test $(BENCH_PKG) -run='^$$' -bench=BenchmarkSustainedLoad $(BENCH_TIME) $(BENCH_RUN)

bench-codec:
	cd engine && go test $(BENCH_PKG) -run='^$$' -bench=BenchmarkCodecComparison $(BENCH_TIME) $(BENCH_RUN)

bench-profile-allocs:
	mkdir -p prof
	cd engine && go test $(BENCH_PKG) -run='^$$' -bench=BenchmarkSerialization/500step -benchmem -memprofile=../prof/serial-500.mem -count=1 -benchtime=100x
	cd engine && go test $(BENCH_PKG) -run='^$$' -bench=BenchmarkSerializationScaling/500_steps -benchmem -memprofile=../prof/scaling-500.mem -count=1 -benchtime=100x
	go tool pprof -text -alloc_objects prof/serial-500.mem > prof/serial-500-allocs.txt
	go tool pprof -text -alloc_objects prof/scaling-500.mem > prof/scaling-500-allocs.txt
	@echo "Allocation profiles written to prof/"

bench-full: engine
	cd engine && go test $(BENCH_PKG) -run='^$$' -bench=. -benchtime=10s -count=5 -cpu=1 -benchmem \
		| tee ../results/bench-$$(date +%Y%m%d-%H%M%S).txt

bench-report:
	go run ./engine/cmd/bench-report $$(ls -t results/bench-*.txt | head -1)

compare:
	./scripts/compare.sh

report:
	./scripts/report.sh

clean:
	rm -f $(BINARY)
	rm -f results/bench-*.txt
