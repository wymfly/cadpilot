"""Base types for few-shot examples."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaggedExample:
    """CadQuery few-shot example with feature tags for intelligent retrieval.

    Attributes
    ----------
    description:
        Human-readable description of the part (shown as a comment in prompts).
    code:
        CadQuery Python source code template (may contain ``${output_filename}``).
    features:
        Frozenset of semantic feature tags for Jaccard-based selection, e.g.
        ``{"revolve", "stepped", "hole_pattern", "bore"}``.
    """

    description: str
    code: str
    features: frozenset[str] = field(default_factory=frozenset)
