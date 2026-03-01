"""ParametricTemplateEngine — match, render, validate.

Core engine for the parametric template system:
- find_matches(part_type): list templates for a given part type
- render(name, params): Jinja2 render CadQuery code from template
- validate(name, params): check param ranges and constraints
"""

from __future__ import annotations

from pathlib import Path

import jinja2

from backend.models.template import ParametricTemplate, load_all_templates


class TemplateEngine:
    """Parametric template engine — lookup, validate, render."""

    def __init__(self, templates: list[ParametricTemplate] | None = None) -> None:
        self._templates: dict[str, ParametricTemplate] = {}
        if templates:
            for t in templates:
                self._templates[t.name] = t

    # -- factory -------------------------------------------------------------

    @classmethod
    def from_directory(cls, path: Path) -> TemplateEngine:
        """Load all YAML templates from *path* and return a new engine."""
        templates = load_all_templates(path)
        return cls(templates=templates)

    # -- lookup --------------------------------------------------------------

    def list_templates(self) -> list[ParametricTemplate]:
        """Return all loaded templates."""
        return list(self._templates.values())

    def get_template(self, name: str) -> ParametricTemplate:
        """Return a single template by name or raise ``KeyError``."""
        if name not in self._templates:
            raise KeyError(f"Template '{name}' not found")
        return self._templates[name]

    def find_matches(self, part_type: str) -> list[ParametricTemplate]:
        """Return all templates whose ``part_type`` equals *part_type*."""
        return [t for t in self._templates.values() if t.part_type == part_type]

    # -- validation ----------------------------------------------------------

    def validate(self, name: str, params: dict) -> list[str]:
        """Validate *params* against template definitions and constraints.

        Returns a list of human-readable error strings (empty = all OK).

        1. Range checks via ``ParametricTemplate.validate_params``.
        2. Constraint expression evaluation (e.g. ``"height < diameter"``).
           Only ``min``, ``max``, ``abs`` builtins are exposed.
        """
        tmpl = self.get_template(name)
        errors = tmpl.validate_params(params)

        # Evaluate constraint expressions against merged params
        merged = tmpl.get_defaults()
        merged.update(params)

        _safe_builtins = {"__builtins__": {"min": min, "max": max, "abs": abs}}
        for constraint in tmpl.constraints:
            try:
                if not eval(constraint, _safe_builtins, merged):  # noqa: S307
                    errors.append(f"Constraint violation: {constraint}")
            except Exception as exc:
                errors.append(f"Constraint evaluation error: {constraint} ({exc})")
        return errors

    # -- rendering -----------------------------------------------------------

    def render(
        self,
        name: str,
        params: dict,
        output_filename: str = "output.step",
    ) -> str:
        """Render CadQuery code from a template via Jinja2.

        Missing params are filled with template defaults.
        ``output_filename`` is injected as an extra variable.
        """
        tmpl = self.get_template(name)

        # Merge defaults ← caller params ← output_filename
        merged = tmpl.get_defaults()
        merged.update(params)
        merged["output_filename"] = output_filename

        # Cast int-typed params (API sends all values as float)
        int_params = {p.name for p in tmpl.params if p.param_type == "int"}
        for k in int_params:
            if k in merged and isinstance(merged[k], float):
                merged[k] = int(merged[k])

        env = jinja2.Environment(undefined=jinja2.StrictUndefined)
        template = env.from_string(tmpl.code_template)
        return template.render(**merged)
