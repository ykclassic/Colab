"""Bounded subprocess sandbox for quantitative validation artifacts.

This is a process-isolation boundary for trusted repository code. It is not a
container or VM and must not be used to execute hostile tenant code.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory


class SandboxError(RuntimeError):
    """Raised when a sandboxed validation job cannot complete safely."""


@dataclass(frozen=True)
class SandboxResult:
    """Captured result from a bounded validation process."""

    return_code: int
    stdout: str
    stderr: str


class QuantSandbox:
    """Run trusted validation scripts with time, output, and filesystem bounds."""

    def __init__(self, *, timeout_seconds: float = 30.0, max_output_bytes: int = 1_000_000) -> None:
        if timeout_seconds <= 0 or max_output_bytes <= 0:
            raise ValueError("sandbox limits must be positive")
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes

    def run(self, script: str, payload: dict[str, object] | None = None) -> SandboxResult:
        if not script.strip():
            raise ValueError("script must not be empty")
        with TemporaryDirectory(prefix="colab-sandbox-") as directory:
            root = Path(directory)
            script_path = root / "job.py"
            input_path = root / "input.json"
            script_path.write_text(script, encoding="utf-8")
            input_path.write_text(json.dumps(payload or {}), encoding="utf-8")
            env = {
                "PATH": os.environ.get("PATH", ""),
                "PYTHONUNBUFFERED": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "COLAB_SANDBOX_INPUT": str(input_path),
            }
            try:
                completed = subprocess.run(
                    [sys.executable, "-I", str(script_path)],
                    cwd=root,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise SandboxError("sandbox execution exceeded timeout") from exc
            stdout = completed.stdout[: self.max_output_bytes]
            stderr = completed.stderr[: self.max_output_bytes]
            if len(completed.stdout) > self.max_output_bytes or len(completed.stderr) > self.max_output_bytes:
                raise SandboxError("sandbox output exceeded configured limit")
            return SandboxResult(completed.returncode, stdout, stderr)
