"""AST static pre-check for generated CadQuery code.

Performs lightweight static analysis before code execution:
1. Syntax validity (ast.parse)
2. Export statement presence
3. Blocked import detection (security)
4. Blocked API call detection (show_object, debug, etc.)
5. Undefined export variable warning
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class AstCheckResult:
    """Result of AST pre-check analysis."""

    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Blocked imports — security-sensitive stdlib modules
# ---------------------------------------------------------------------------

_BLOCKED_IMPORTS: frozenset[str] = frozenset({
    "os",
    "subprocess",
    "shutil",
    "signal",
    "ctypes",
    "socket",
    "sys",
    "importlib",
    "pathlib",
})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _check_syntax(code: str) -> tuple[ast.Module | None, list[str]]:
    """Parse code and return (tree, errors). Empty errors if parse succeeds."""
    try:
        tree = ast.parse(code)
        return tree, []
    except SyntaxError as e:
        msg = f"Syntax error: {e.msg} (line {e.lineno})"
        return None, [msg]


def _check_export(tree: ast.Module) -> list[str]:
    """Check that at least one call containing 'export' exists."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call_str = ast.dump(node.func)
            if "export" in call_str.lower():
                return []
    return ["Missing export statement: code must call an export function (e.g. cq.exporters.export)"]


def _check_blocked_imports(tree: ast.Module) -> list[str]:
    """Check for blocked module imports."""
    errors: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _BLOCKED_IMPORTS:
                    errors.append(
                        f"Blocked import: '{alias.name}' — "
                        f"module '{root}' is not allowed in generated code"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                if root in _BLOCKED_IMPORTS:
                    errors.append(
                        f"Blocked import: 'from {node.module}' — "
                        f"module '{root}' is not allowed in generated code"
                    )
    return errors


def _check_blocked_api_calls(tree: ast.Module) -> list[str]:
    """Check for calls to blocked APIs (show_object, debug, etc.)."""
    from ..core.api_whitelist import BLOCKED_APIS

    errors: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = ""
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name and name in BLOCKED_APIS:
                errors.append(
                    f"Blocked API call: '{name}' is not allowed in generated code"
                )
    return errors


def _check_export_variable_defined(tree: ast.Module) -> list[str]:
    """Warn if the first argument of an export call is not defined in code assignments."""
    warnings: list[str] = []

    # Collect all assigned variable names
    assigned_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned_names.add(target.id)
                elif isinstance(target, ast.Tuple):
                    for elt in target.elts:
                        if isinstance(elt, ast.Name):
                            assigned_names.add(elt.id)

    # Find export calls and check their first argument
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call_str = ast.dump(node.func)
            if "export" in call_str.lower() and node.args:
                first_arg = node.args[0]
                if isinstance(first_arg, ast.Name) and first_arg.id not in assigned_names:
                    warnings.append(
                        f"Export variable '{first_arg.id}' is not defined "
                        f"in any assignment in the code"
                    )

    return warnings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ast_pre_check(code: str) -> AstCheckResult:
    """Run AST-level static pre-checks on generated CadQuery code.

    Checks performed:
    1. Syntax validity (ast.parse)
    2. Export statement present
    3. No blocked imports (os, subprocess, etc.)
    4. No blocked API calls (show_object, debug, etc.)
    5. Warning if export variable not defined

    Parameters
    ----------
    code:
        Python source code string to analyze.

    Returns
    -------
    AstCheckResult
        ``passed`` is True only when there are zero errors.
    """
    # Step 1: syntax
    tree, syntax_errors = _check_syntax(code)
    if syntax_errors:
        return AstCheckResult(passed=False, errors=syntax_errors)

    assert tree is not None

    errors: list[str] = []
    warnings: list[str] = []

    # Step 2: export presence
    errors.extend(_check_export(tree))

    # Step 3: blocked imports
    errors.extend(_check_blocked_imports(tree))

    # Step 4: blocked API calls
    errors.extend(_check_blocked_api_calls(tree))

    # Step 5: undefined export variable (warning only)
    warnings.extend(_check_export_variable_defined(tree))

    return AstCheckResult(
        passed=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )
