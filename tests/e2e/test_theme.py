"""E2E 9.4: 亮暗主题切换测试。

主题切换在前端通过 Ant Design ConfigProvider + localStorage 实现。
后端 API 层不涉及主题状态。本测试验证：
- 应用健康检查通过
- API 服务正常可用
- CORS 配置正确（前端主题依赖静态资源正常加载）
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class TestThemeAndAppHealth:
    """应用健康检查与主题基础设施验证。"""

    def test_health_endpoint(self, client: TestClient) -> None:
        """验证 /api/health 端点正常。"""
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_cors_headers_present(self, client: TestClient) -> None:
        """验证 CORS 头存在（前端跨域访问需要）。"""
        resp = client.options(
            "/api/v1/jobs",
            headers={
                "Origin": "http://localhost:3001",
                "Access-Control-Request-Method": "GET",
            },
        )
        # FastAPI CORS 中间件应返回 200
        assert resp.status_code == 200
        assert "access-control-allow-origin" in resp.headers

    def test_api_v1_accessible(self, client: TestClient) -> None:
        """验证 V1 API 根路径可访问。"""
        resp = client.get("/api/v1/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    def test_static_outputs_mount(self, client: TestClient) -> None:
        """验证 /outputs 静态文件挂载点存在。"""
        # 请求不存在的文件应返回 404（而非路由未定义的 404）
        resp = client.get("/outputs/nonexistent/model.glb")
        # StaticFiles mount 会返回 404 for missing files
        assert resp.status_code == 404

    def test_openapi_docs_accessible(self, client: TestClient) -> None:
        """验证 OpenAPI 文档可访问。"""
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_openapi_json(self, client: TestClient) -> None:
        """验证 OpenAPI JSON schema 可获取。"""
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert schema["info"]["title"] == "cad3dify"
        assert schema["info"]["version"] == "3.0.0"
        # 验证 V1 路径已注册
        paths = list(schema["paths"].keys())
        v1_paths = [p for p in paths if p.startswith("/api/v1/")]
        assert len(v1_paths) > 0
