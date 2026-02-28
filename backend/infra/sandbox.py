"""Safe code executor — AST pre-check + subprocess isolation.

Blocks dangerous patterns (os.system, subprocess, eval, exec, __import__)
at the AST level, then runs approved code in a subprocess with timeout.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import time
from dataclasses import dataclass


class SecurityViolation(Exception):
    """Raised when code contains a forbidden pattern."""


# ---------------------------------------------------------------------------
# Blocked patterns
# ---------------------------------------------------------------------------

# Modules that must not be imported.
_BLOCKED_MODULES: frozenset[str] = frozenset({
    "os",
    "subprocess",
    "shutil",
    "signal",
    "ctypes",
    "socket",
    "sys",
    "importlib",
})

# Built-in function names that must not be called.
_BLOCKED_CALLS: frozenset[str] = frozenset({
    "eval",
    "exec",
    "__import__",
    "compile",
    "globals",
    "locals",
    "breakpoint",
})


# ---------------------------------------------------------------------------
# AST visitor
# ---------------------------------------------------------------------------


class _SecurityVisitor(ast.NodeVisitor):
    """Walk the AST and collect security violations."""

    def __init__(self) -> None:
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in _BLOCKED_MODULES:
                self.violations.append(
                    f"Blocked import: '{alias.name}' (module '{root}' is forbidden)"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            root = node.module.split(".")[0]
            if root in _BLOCKED_MODULES:
                self.violations.append(
                    f"Blocked import: 'from {node.module}' (module '{root}' is forbidden)"
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = self._call_name(node)
        if name in _BLOCKED_CALLS:
            self.violations.append(f"Blocked call: '{name}' is forbidden")
        # Check for os.system, os.popen etc. via attribute calls
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                if node.func.value.id in _BLOCKED_MODULES:
                    self.violations.append(
                        f"Blocked call: '{node.func.value.id}.{node.func.attr}' is forbidden"
                    )
        self.generic_visit(node)

    @staticmethod
    def _call_name(node: ast.Call) -> str:
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        return ""


# ---------------------------------------------------------------------------
# Execution result
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResult:
    """Result of a sandboxed code execution."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    duration_s: float = 0.0


# ---------------------------------------------------------------------------
# SafeExecutor
# ---------------------------------------------------------------------------


class SafeExecutor:
    """AST-checked + subprocess-isolated code executor."""

    def __init__(
        self,
        *,
        timeout_s: int = 60,
        work_dir: str | None = None,
    ) -> None:
        self.timeout_s = timeout_s
        self.work_dir = work_dir

    def check_code(self, code: str) -> None:
        """Raise :class:`SecurityViolation` if *code* contains forbidden patterns."""
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            raise SecurityViolation(f"Syntax error in code: {exc}") from exc

        visitor = _SecurityVisitor()
        visitor.visit(tree)

        if visitor.violations:
            raise SecurityViolation(
                "Security violations detected:\n" + "\n".join(f"  - {v}" for v in visitor.violations)
            )

    def execute(self, code: str) -> ExecutionResult:
        """Check code safety, then execute in a subprocess with timeout."""
        # AST pre-check — raises SecurityViolation if blocked
        self.check_code(code)

        start = time.monotonic()
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                cwd=self.work_dir,
            )
            duration = time.monotonic() - start
            return ExecutionResult(
                success=proc.returncode == 0,
                stdout=proc.stdout,
                stderr=proc.stderr,
                timed_out=False,
                duration_s=duration,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            return ExecutionResult(
                success=False,
                stderr=f"Execution timed out after {self.timeout_s}s",
                timed_out=True,
                duration_s=duration,
            )
