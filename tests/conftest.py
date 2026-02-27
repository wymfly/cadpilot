"""Test configuration.

The top-level ``cad3dify/__init__.py`` imports v1 chains that depend on
``langchain``, ``cadquery``, and other heavy packages that are not
installed in the lightweight test environment.

We install a custom meta-path finder that intercepts *any* import of
known third-party packages and returns a lightweight stub module.
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import sys
import types
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Stub finder / loader
# ---------------------------------------------------------------------------

# Top-level package names that should be auto-stubbed.
_STUB_ROOTS: frozenset[str] = frozenset({
    "langchain",
    "langchain_core",
    "langchain_experimental",
    "langchain_openai",
    "langchain_anthropic",
    "langchain_google_genai",
    "langchain_google_vertexai",
    "langchainhub",
    "svglib",
    "reportlab",
    # cadquery — NOT stubbed, needed for geometry validation tests
    "cv2",
    "matplotlib",
    # numpy — NOT stubbed, cadquery depends on it
    "dotenv",
    "python_dotenv",
    "rlpycairo",
    "streamlit",
    "httpx",
    "sentence_transformers",
    # loguru — NOT stubbed, used by validators for real logging
    "paddleocr",
    "pytesseract",
    # PIL / Pillow — NOT stubbed, needed for contour overlay tests
    # Organic engine heavy deps — lazy-loaded in handlers
    "manifold3d",
    "pymeshlab",
})


class _StubLoader(importlib.abc.Loader):
    """Loader that creates stub modules with package semantics."""

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> types.ModuleType | None:
        return None  # use default semantics

    def exec_module(self, module: types.ModuleType) -> None:
        module.__path__ = []  # make it a package
        module.__package__ = module.__name__

        # Attribute fallback: any missing attribute returns a MagicMock
        _original_class = type(module)

        class _AttrModule(_original_class):
            def __getattr__(self, item: str) -> MagicMock:
                return MagicMock()

        module.__class__ = _AttrModule


_loader = _StubLoader()


class _StubFinder(importlib.abc.MetaPathFinder):
    """Intercept imports of known heavy-weight packages and return stubs."""

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: object = None,
    ) -> importlib.machinery.ModuleSpec | None:
        root = fullname.split(".")[0]
        if root in _STUB_ROOTS:
            return importlib.machinery.ModuleSpec(
                fullname,
                _loader,
                is_package=True,
            )
        return None


# Install the finder at the *front* of sys.meta_path.
sys.meta_path.insert(0, _StubFinder())


# loguru is NOT stubbed — validators use real logger for info/warning output
