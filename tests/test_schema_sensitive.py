"""Tests for enhance_config_schema() — x-sensitive post-processing."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from backend.graph.registry import enhance_config_schema


class TestSensitiveFieldDetection:
    """Fields with api_key/secret/password in name get x-sensitive: true."""

    def test_sensitive_api_key_detected(self):
        schema = {
            "properties": {
                "api_key": {"type": "string"},
                "model_name": {"type": "string"},
            }
        }
        result = enhance_config_schema(schema)
        assert result["properties"]["api_key"].get("x-sensitive") is True
        assert "x-sensitive" not in result["properties"]["model_name"]

    def test_sensitive_secret_detected(self):
        schema = {
            "properties": {
                "client_secret": {"type": "string"},
                "endpoint": {"type": "string"},
            }
        }
        result = enhance_config_schema(schema)
        assert result["properties"]["client_secret"].get("x-sensitive") is True
        assert "x-sensitive" not in result["properties"]["endpoint"]

    def test_sensitive_password_detected(self):
        schema = {
            "properties": {
                "db_password": {"type": "string"},
                "db_host": {"type": "string"},
            }
        }
        result = enhance_config_schema(schema)
        assert result["properties"]["db_password"].get("x-sensitive") is True
        assert "x-sensitive" not in result["properties"]["db_host"]

    def test_case_insensitive_match(self):
        schema = {
            "properties": {
                "API_KEY": {"type": "string"},
                "Secret_Token": {"type": "string"},
            }
        }
        result = enhance_config_schema(schema)
        assert result["properties"]["API_KEY"].get("x-sensitive") is True
        assert result["properties"]["Secret_Token"].get("x-sensitive") is True


class TestPydanticNativeMetadataPreserved:
    """Pydantic v2 native metadata (description, min, max, x-group) stays intact."""

    def test_pydantic_native_metadata_preserved(self):
        class SampleConfig(BaseModel):
            api_key: str = Field(description="The API key")
            temperature: float = Field(
                default=0.7,
                ge=0.0,
                le=2.0,
                description="Sampling temperature",
                json_schema_extra={"x-group": "advanced"},
            )

        schema = SampleConfig.model_json_schema()
        result = enhance_config_schema(schema)

        # api_key: x-sensitive injected + description preserved
        api_props = result["properties"]["api_key"]
        assert api_props["x-sensitive"] is True
        assert api_props["description"] == "The API key"

        # temperature: native metadata preserved, no x-sensitive
        temp_props = result["properties"]["temperature"]
        assert "x-sensitive" not in temp_props
        assert temp_props["description"] == "Sampling temperature"
        assert temp_props["x-group"] == "advanced"


class TestNonSensitiveUnchanged:
    """Fields without sensitive names don't get x-sensitive."""

    def test_non_sensitive_unchanged(self):
        schema = {
            "properties": {
                "model_name": {"type": "string"},
                "temperature": {"type": "number"},
                "max_tokens": {"type": "integer"},
            }
        }
        result = enhance_config_schema(schema)
        for field_name in ("model_name", "temperature", "max_tokens"):
            assert "x-sensitive" not in result["properties"][field_name]

    def test_empty_properties(self):
        schema = {"properties": {}}
        result = enhance_config_schema(schema)
        assert result == {"properties": {}}

    def test_no_properties_key(self):
        schema = {"type": "object"}
        result = enhance_config_schema(schema)
        assert result == {"type": "object"}


class TestXScopeAnnotation:
    """Fields annotated with x-scope appear in config_schema."""

    def test_generate_raw_mesh_api_key_has_system_scope(self):
        from backend.graph.configs.generate_raw_mesh import GenerateRawMeshConfig
        schema = GenerateRawMeshConfig.model_json_schema()
        api_key_prop = schema["properties"]["hunyuan3d_api_key"]
        assert api_key_prop.get("x-scope") == "system"
        assert api_key_prop.get("x-sensitive") is True

    def test_generate_raw_mesh_timeout_no_scope(self):
        from backend.graph.configs.generate_raw_mesh import GenerateRawMeshConfig
        schema = GenerateRawMeshConfig.model_json_schema()
        assert "x-scope" not in schema["properties"]["timeout"]

    def test_neural_config_system_fields(self):
        from backend.graph.configs.neural import NeuralStrategyConfig
        schema = NeuralStrategyConfig.model_json_schema()
        for field in ("neural_enabled", "neural_endpoint", "health_check_path"):
            assert schema["properties"][field].get("x-scope") == "system", f"{field} missing x-scope"
        assert "x-scope" not in schema["properties"]["neural_timeout"]

    def test_mesh_healer_retopo_endpoint_system(self):
        from backend.graph.configs.mesh_healer import MeshHealerConfig
        schema = MeshHealerConfig.model_json_schema()
        assert schema["properties"]["retopo_endpoint"].get("x-scope") == "system"

    def test_slice_to_gcode_cli_paths_system(self):
        from backend.graph.configs.slice_to_gcode import SliceToGcodeConfig
        schema = SliceToGcodeConfig.model_json_schema()
        for field in ("prusaslicer_path", "orcaslicer_path"):
            assert schema["properties"][field].get("x-scope") == "system", f"{field} missing x-scope"
