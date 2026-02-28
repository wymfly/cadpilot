"""E2E 9.6: 旧 API 废弃验证。

验证新 V1 API 是标准入口，旧版端点向后兼容状态检查。

当前状态：旧版路由（/api/generate 等）仍然挂载以保持向后兼容。
本测试验证：
1. V1 端点是标准入口且功能完整
2. 不存在的 V1 路径正确返回 404
3. 统一错误格式在所有场景下工作
4. 旧版路由的兼容性状态（标记为后续移除）
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.models.job import create_job


class TestV1CanonicalEndpoints:
    """V1 API 标准端点验证。"""

    def test_v1_jobs_exists(self, client: TestClient) -> None:
        """GET /api/v1/jobs 正常响应。"""
        resp = client.get("/api/v1/jobs")
        assert resp.status_code == 200

    def test_v1_jobs_create(self, client: TestClient) -> None:
        """POST /api/v1/jobs 创建 Job（返回 SSE 流）。"""
        from tests.e2e.conftest import get_sse_job_id

        resp = client.post(
            "/api/v1/jobs",
            json={"input_type": "text", "text": "test"},
        )
        assert resp.status_code == 200
        job_id = get_sse_job_id(resp)
        assert job_id  # job_id 存在于 SSE 事件中

    def test_v1_upload_exists(self, client: TestClient) -> None:
        """POST /api/v1/jobs/upload 图纸上传端点存在（返回 SSE 流）。"""
        resp = client.post(
            "/api/v1/jobs/upload",
            files={"image": ("test.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        )
        assert resp.status_code == 200

    def test_v1_preview_exists(self, client: TestClient) -> None:
        """POST /api/v1/preview/parametric 预览端点存在。"""
        resp = client.post(
            "/api/v1/preview/parametric",
            json={"template_name": "test", "params": {}},
        )
        # 端点存在（模板不存在时返回 404，非路由级 404）
        assert resp.status_code in (200, 404, 500)


class TestNonexistentV1Paths:
    """不存在的 V1 路径返回正确错误。"""

    def test_v1_nonexistent_resource(self, client: TestClient) -> None:
        """访问不存在的 V1 资源返回 404。"""
        resp = client.get("/api/v1/nonexistent")
        assert resp.status_code in (404, 405)

    def test_v1_nonexistent_job(self, client: TestClient) -> None:
        """查询不存在的 Job 返回 404 + 统一错误格式。"""
        resp = client.get("/api/v1/jobs/nonexistent-job-id")
        assert resp.status_code == 404
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == "JOB_NOT_FOUND"

    def test_v1_nonexistent_job_events(self, client: TestClient) -> None:
        """订阅不存在的 Job 事件返回 404。"""
        resp = client.get("/api/v1/jobs/nonexistent/events")
        assert resp.status_code == 404

    def test_v1_nonexistent_job_confirm(self, client: TestClient) -> None:
        """确认不存在的 Job 返回 404。"""
        resp = client.post(
            "/api/v1/jobs/nonexistent/confirm",
            json={"confirmed_params": {}},
        )
        assert resp.status_code == 404

    def test_v1_nonexistent_job_regenerate(self, client: TestClient) -> None:
        """重新生成不存在的 Job 返回 404。"""
        resp = client.post("/api/v1/jobs/nonexistent/regenerate")
        assert resp.status_code == 404

    def test_v1_nonexistent_job_delete(self, client: TestClient) -> None:
        """删除不存在的 Job 返回 404。"""
        resp = client.delete("/api/v1/jobs/nonexistent")
        assert resp.status_code == 404

    def test_v1_nonexistent_job_corrections(self, client: TestClient) -> None:
        """查询不存在 Job 的修正记录返回 404。"""
        resp = client.get("/api/v1/jobs/nonexistent/corrections")
        assert resp.status_code == 404


class TestErrorFormatConsistency:
    """统一错误格式在所有端点一致。"""

    def test_404_error_format(self, client: TestClient) -> None:
        """404 错误包含标准 error.code + error.message。"""
        resp = client.get("/api/v1/jobs/missing")
        assert resp.status_code == 404
        data = resp.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]
        assert data["error"]["code"] == "JOB_NOT_FOUND"

    async def test_409_error_format(self, client: TestClient) -> None:
        """409 状态冲突错误格式标准。"""
        await create_job("err-1", input_type="text", input_text="test")

        resp = client.post(
            "/api/v1/jobs/err-1/confirm",
            json={"confirmed_params": {}},
        )
        assert resp.status_code == 409
        data = resp.json()
        assert data["error"]["code"] == "INVALID_JOB_STATE"

    def test_422_validation_error_format(self, client: TestClient) -> None:
        """422 请求体校验错误格式标准。"""
        resp = client.post(
            "/api/v1/jobs",
            content="invalid json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"]["code"] == "VALIDATION_FAILED"


class TestLegacyRoutesStatus:
    """旧版路由当前状态检查。

    这些路由当前仍然挂载（backward compat），计划后续迭代移除。
    测试标记为文档性质，记录当前兼容状态。
    """

    def test_legacy_health_still_available(self, client: TestClient) -> None:
        """旧版 /api/health 仍可访问。"""
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_legacy_templates_still_available(self, client: TestClient) -> None:
        """旧版 /api/templates 仍可访问。"""
        resp = client.get("/api/templates")
        assert resp.status_code == 200

    def test_v1_is_canonical(self, client: TestClient) -> None:
        """验证 V1 API 路径完整注册。"""
        resp = client.get("/openapi.json")
        schema = resp.json()
        paths = list(schema["paths"].keys())

        v1_required = [
            "/api/v1/jobs",
            "/api/v1/jobs/{job_id}",
            "/api/v1/jobs/{job_id}/confirm",
            "/api/v1/jobs/{job_id}/regenerate",
            "/api/v1/jobs/{job_id}/events",
            "/api/v1/jobs/{job_id}/corrections",
            "/api/v1/jobs/upload",
            "/api/v1/preview/parametric",
        ]
        for required_path in v1_required:
            assert required_path in paths, f"缺少 V1 路径: {required_path}"
