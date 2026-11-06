# Contributing

attest-bench holds benchmarks for [attest](https://github.com/attest-framework/attest). Open an issue before a large change.

## Checks

Run the checks for the part you change before opening a pull request.

| Part | Checks |
|---|---|
| Engine and protocol benchmarks (`engine/`) | `go vet ./... && go test ./... -count=1` |
| Fault corpus (`corpus-bench/`) | `make corpus-setup corpus-engine corpus-check`, then `make corpus-bench` and commit the changed `corpus-bench/published/` tables |
| Workflows (`.github/workflows/`) | `actionlint`; every `uses:` pinned to a commit SHA with a `# vX.Y.Z` comment |

## Rules

- Pin `benchstat` to the commit used in the workflows: `go install golang.org/x/perf/cmd/benchstat@be2c69fb417e`.
- A README number must come from a committed result file. Do not quote a figure the repository cannot reproduce.
- Corpus runs are synthetic. Do not add real customer, payment or credential data.
- Add a run to the corpus by extending the transforms in `corpus-bench/src/corpus_bench/corpus.py`, then run `make corpus-manifest` and review the diff.
- Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat(bench): ...`, `fix(ci): ...`).

## License

By contributing you agree that your contribution is licensed under Apache-2.0, as in `LICENSE`.
