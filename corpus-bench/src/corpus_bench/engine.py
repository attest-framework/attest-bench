"""attest-engine access: the pinned release binary, JSON-RPC evaluation and `mutate`."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from types import TracebackType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "engine.lock.json"
DEFAULT_ENGINE = ROOT / "bin" / "attest-engine"
REQUEST_TIMEOUT_S = 120.0


class EngineError(RuntimeError):
    """The engine failed, answered with an error, or is not the pinned release."""


def load_lock() -> dict[str, Any]:
    lock: dict[str, Any] = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    return lock


def fetch_engine(dest: Path = DEFAULT_ENGINE) -> Path:
    """Build `attest-engine` from the pinned attest commit (needs git and Go)."""
    lock = load_lock()
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "attest"
        src.mkdir()
        for cmd in (
            ["git", "init", "-q"],
            ["git", "fetch", "-q", "--depth", "1", lock["repo"], lock["commit"]],
            ["git", "checkout", "-q", "--detach", "FETCH_HEAD"],
        ):
            subprocess.run(cmd, cwd=src, check=True, timeout=600)
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["go", "build", "-trimpath", "-o", str(dest.resolve()), "./cmd/attest-engine"],
            cwd=src / "engine",
            check=True,
            env={**os.environ, "CGO_ENABLED": "0"},
            timeout=900,
        )
    return dest


def resolve_engine() -> Path:
    """`ATTEST_ENGINE_PATH`, else the binary `make corpus-engine` fetched."""
    env = os.environ.get("ATTEST_ENGINE_PATH")
    path = Path(env) if env else DEFAULT_ENGINE
    if not path.is_file():
        raise EngineError(f"engine not found at {path}: run `make corpus-engine`")
    version = engine_version(path)
    pinned = load_lock()["version"]
    if version != pinned:
        raise EngineError(f"{path} is attest-engine {version}; the corpus pins {pinned}")
    return path


def engine_version(path: Path) -> str:
    out = subprocess.run(
        [str(path), "version"], capture_output=True, text=True, check=True, timeout=30
    ).stdout.strip()
    prefix = "attest-engine "
    if not out.startswith(prefix):
        raise EngineError(f"unexpected `version` output: {out!r}")
    return out[len(prefix) :]


def mutate(path: Path, fixture: Path, *, seed: int, max_mutants: int) -> dict[str, Any]:
    """Run `attest-engine mutate` on one fixture with its drafted contracts."""
    proc = subprocess.run(
        [
            str(path),
            "mutate",
            str(fixture),
            "--json",
            f"--seed={seed}",
            f"--max-mutants={max_mutants}",
        ],
        capture_output=True,
        text=True,
        timeout=REQUEST_TIMEOUT_S,
        check=False,
    )
    if proc.returncode != 0:
        raise EngineError(f"mutate {fixture.name} exited {proc.returncode}: {proc.stderr.strip()}")
    report: dict[str, Any] = json.loads(proc.stdout)
    return report


class Engine:
    """One engine process speaking JSON-RPC 2.0 over NDJSON on stdio."""

    def __init__(self, path: Path, *, simulation: bool = True) -> None:
        """`simulation` makes the engine refuse every model-backed layer (L5/L6)."""
        self._path = path
        self._env = {**os.environ, **({"ATTEST_SIMULATION": "1"} if simulation else {})}
        self._proc: subprocess.Popen[str] | None = None
        self._next_id = 0
        self.cost_usd = 0.0
        self.model_calls = 0
        self.judge_calls = 0

    def __enter__(self) -> Engine:
        self._proc = subprocess.Popen(
            [str(self._path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            env=self._env,
        )
        init = self._call(
            "initialize",
            {
                "sdk_name": "corpus-bench",
                "sdk_version": "0.1.0",
                "protocol_version": 1,
                "required_capabilities": ["layers_1_4"],
            },
        )
        if not init.get("compatible"):
            raise EngineError(f"engine incompatible: {init}")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            if exc_type is None:
                self._call("shutdown", {})
        finally:
            assert proc.stdin is not None
            proc.stdin.close()
            proc.wait(timeout=30)

    def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        proc = self._proc
        assert proc is not None and proc.stdin is not None and proc.stdout is not None
        self._next_id += 1
        request = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        watchdog = threading.Timer(REQUEST_TIMEOUT_S, proc.kill)
        watchdog.start()
        try:
            proc.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
        finally:
            watchdog.cancel()
        if not line:
            raise EngineError(f"engine closed stdout during {method}")
        reply = json.loads(line)
        if "error" in reply:
            raise EngineError(f"{method}: {reply['error']}")
        result: dict[str, Any] = reply["result"]
        return result

    def evaluate(
        self, trace: dict[str, Any], assertions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Evaluate assertions on a trace; returns the engine's per-assertion results."""
        result = self._call("evaluate_batch", {"trace": trace, "assertions": assertions})
        usage = result["usage"]
        self.cost_usd += float(usage["cost_usd"])
        self.model_calls += int(usage["model_calls"])
        self.judge_calls += int(usage["judge_calls"])
        rows: list[dict[str, Any]] = result["results"]
        return rows
