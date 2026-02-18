BINARY     := bin/attest-engine
CMD        := ./engine/cmd/attest-engine
BENCH_PKG  := ./internal/protocol/
BENCH_TIME := -benchtime=5s
BENCH_RUN  := -count=10 -cpu=1 -benchmem

.PHONY: engine engine-profile bench-serial bench-protocol bench-startup bench-all compare report clean

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

compare:
	./scripts/compare.sh

report:
	./scripts/report.sh

clean:
	rm -f $(BINARY)
	rm -f results/bench-*.txt
