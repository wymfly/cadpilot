"""Tests for organic pipeline Pydantic models."""
from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_flat_bottom_cut_defaults():
    from backend.models.organic import FlatBottomCut
    cut = FlatBottomCut()
    assert cut.type == "flat_bottom"
    assert cut.offset == 0.0


def test_hole_cut_requires_diameter_and_depth():
    from backend.models.organic import HoleCut
    with pytest.raises(ValidationError):
        HoleCut()  # missing required fields
    hole = HoleCut(diameter=10.0, depth=25.0)
    assert hole.direction == "bottom"


def test_slot_cut_requires_dimensions():
    from backend.models.organic import SlotCut
    with pytest.raises(ValidationError):
        SlotCut()  # missing required fields
    slot = SlotCut(width=5.0, depth=10.0, length=20.0)
    assert slot.type == "slot"


def test_hole_cut_rejects_invalid_values():
    from backend.models.organic import HoleCut
    with pytest.raises(ValidationError):
        HoleCut(diameter=-1, depth=10)
    with pytest.raises(ValidationError):
        HoleCut(diameter=10, depth=0)


def test_discriminated_union_dispatch():
    from backend.models.organic import OrganicConstraints
    constraints = OrganicConstraints(
        bounding_box=(80, 80, 60),
        engineering_cuts=[
            {"type": "flat_bottom"},
            {"type": "hole", "diameter": 10, "depth": 25},
        ],
    )
    assert len(constraints.engineering_cuts) == 2
    assert constraints.engineering_cuts[0].type == "flat_bottom"
    assert constraints.engineering_cuts[1].type == "hole"


def test_organic_constraints_default_factory():
    from backend.models.organic import OrganicConstraints
    c1 = OrganicConstraints()
    c2 = OrganicConstraints()
    assert c1.engineering_cuts is not c2.engineering_cuts  # no shared mutable default


def test_organic_generate_request_validation():
    from backend.models.organic import OrganicGenerateRequest
    req = OrganicGenerateRequest(prompt="高尔夫球头")
    assert req.quality_mode == "standard"
    assert req.provider == "auto"


def test_organic_generate_request_rejects_empty_prompt():
    from backend.models.organic import OrganicGenerateRequest
    with pytest.raises(ValidationError):
        OrganicGenerateRequest(prompt="")


def test_mesh_stats_serialization():
    from backend.models.organic import MeshStats
    stats = MeshStats(
        vertex_count=1000,
        face_count=2000,
        is_watertight=True,
        volume_cm3=12.5,
        bounding_box={"x": 80, "y": 80, "z": 60},
        has_non_manifold=False,
        repairs_applied=["fix_normals"],
        boolean_cuts_applied=2,
    )
    d = stats.model_dump()
    assert d["is_watertight"] is True
    assert d["boolean_cuts_applied"] == 2


def test_organic_job_result():
    from backend.models.organic import MeshStats, OrganicJobResult
    stats = MeshStats(
        vertex_count=100, face_count=200, is_watertight=True,
        volume_cm3=1.0, bounding_box={"x": 10, "y": 10, "z": 10},
        has_non_manifold=False, repairs_applied=[], boolean_cuts_applied=0,
    )
    result = OrganicJobResult(
        job_id="test-123",
        model_url="/outputs/test/model.glb",
        mesh_stats=stats,
        provider_used="tripo3d",
        generation_time_s=15.0,
        post_processing_time_s=5.0,
    )
    assert result.stl_url is None
