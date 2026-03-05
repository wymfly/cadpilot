# GPU Server 模型服务 API 标准化

> 日期：2026-03-05
> 范围：GPU 服务器（100.84.132.54）上三个 3D 生成模型的 API 统一改造
> 前置依赖：无
> 后续依赖：后端有机管道策略集成

---

## 背景

GPU 服务器上已部署三个模型服务（Hunyuan3D-2.1 :8080、TripoSG :8081、TRELLIS.2 :8082），各自 API 接口不统一：

| 差异点 | Hunyuan3D-2.1 | TripoSG | TRELLIS.2 |
|--------|-------------|---------|-----------|
| 路径 | POST /generate | POST /generate | POST /generate |
| 请求体 | JSON（字段各异） | JSON | Pydantic model |
| 特有参数 | octree_resolution, texture, face_count | num_inference_steps, guidance_scale, faces | simplify, texture_size, remesh |
| 错误处理 | JSONResponse 500 | JSONResponse 500 | dict 返回 |
| 健康检查 | GET /health | GET /health | GET /health |
| 输入校验 | 无 | 无 | Pydantic 基本校验 |
| 超时控制 | 无 | 无 | 无 |
| 并发保护 | semaphore | 无 | 无 |

## 目标

定义统一 API 契约，三个模型服务实现同一接口规范，使后端策略代码可以用统一的 `LocalModelStrategy` 基类对接。

---

## API 契约

### POST /v1/generate

**请求：**

```json
{
  "image": "<base64_encoded_png>",
  "seed": 42,
  "params": {
    "num_inference_steps": 50,
    "guidance_scale": 7.0,
    "simplify": 100000,
    "texture": false
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| image | string (base64) | 是 | PNG/JPEG 图片 |
| seed | int | 否 | 随机种子，默认随机 |
| params | object | 否 | 模型特定参数，不认识的参数静默忽略 |

**输入校验：**
- image 必填，base64 解码后必须是有效图片
- 图片尺寸上限 4096x4096
- base64 数据大小上限 20MB

**成功响应（200）：**

```
HTTP/1.1 200 OK
Content-Type: model/gltf-binary
X-Mesh-Vertices: 1234567
X-Mesh-Faces: 2345678
X-Mesh-Watertight: true
X-Generation-Time-Ms: 14200

<GLB binary data>
```

| 响应头 | 类型 | 说明 |
|--------|------|------|
| X-Mesh-Vertices | int | 顶点数 |
| X-Mesh-Faces | int | 面数 |
| X-Mesh-Watertight | bool | 是否水密 |
| X-Generation-Time-Ms | int | 生成耗时（毫秒） |

**错误响应：**

```json
// 400 — 输入校验失败
{"error": "invalid_image", "message": "Image decode failed or exceeds 4096x4096"}

// 503 — GPU 忙（正在处理其他请求）
// 同时设置 HTTP 标准 Retry-After 响应头：Retry-After: 30
{"error": "gpu_busy", "message": "Generation in progress", "retry_after": 30}

// 504 — 生成超时
{"error": "generation_timeout", "message": "Generation exceeded 300s timeout"}

// 500 — 内部错误
{"error": "internal_error", "message": "..."}
```

### GET /v1/health

**响应（200）：**

```json
{
  "status": "ok",
  "model": "triposg",
  "gpu": "NVIDIA GeForce RTX 5090",
  "vram_free_mb": 25000
}
```

---

## 改造范围

### 三个文件

| 文件 | 位置 |
|------|------|
| Hunyuan3D-2.1 API | `~/workspace/models/Hunyuan3D-2.1/api_server.py` |
| TripoSG API | `~/workspace/models/TripoSG/api_server.py` |
| TRELLIS.2 API | `~/workspace/models/TRELLIS.2/api_server.py` |

### 每个文件的改造内容

1. **路由变更**：`/generate` → `/v1/generate`，`/health` → `/v1/health`（保留旧路由直接响应，非重定向——`LocalModelStrategy._check_endpoint_health()` 仅接受 200，3xx 会被判定为不健康）
2. **请求模型统一**：统一 `GenerateRequest` Pydantic model（image + seed + params）
3. **输入校验**：base64 解码 + 图片格式/尺寸校验
4. **GPU 信号量**：`asyncio.Semaphore(1)` 保护生成函数，503 when busy。信号量**必须在 `finally` 块中释放**，防止超时异常导致泄露
5. **超时控制**：`asyncio.wait_for(generate(), timeout=300)`。超时处理策略：信号量**不在超时时释放**，而是等推理任务真正结束后才释放（在推理 wrapper 的 finally 中释放）。这样超时后新请求会收到 503（gpu_busy），而非重叠执行
6. **响应头**：加 mesh 元信息（trimesh 分析后写入 header）
7. **错误码统一**：结构化 JSON 错误响应

### 不改的部分

- 模型加载逻辑不变
- 推理代码不变
- conda 环境不变
- 启动脚本不变（只改端口内的 API 层）

---

## 各模型特定参数映射

| params 字段 | Hunyuan3D-2.1 | TripoSG | TRELLIS.2 |
|------------|--------------|---------|-----------|
| num_inference_steps | ✅ (默认 5) | ✅ (默认 50) | 忽略 |
| guidance_scale | ✅ (默认 5.0) | ✅ (默认 7.0) | 忽略 |
| texture | ✅ (默认 true) | 忽略 | 忽略 |
| octree_resolution | ✅ (默认 256) | 忽略 | 忽略 |
| simplify | 忽略 | ✅ faces 参数映射 | ✅ (默认 100000) |
| texture_size | 忽略 | 忽略 | ✅ (默认 4096) |

---

## 迁移计划

### 实施顺序

按风险从低到高逐个改造，每改一个验证通过后再进入下一个：

1. **TripoSG**（最简单，已有 JSON+base64 格式，只需加 `/v1/` 前缀 + 响应头 + 信号量）
2. **TRELLIS.2**（中等，需统一请求模型 + 加信号量 + 超时）
3. **Hunyuan3D-2.1**（最复杂，需重构 model_worker 模式 + 去掉 SaaS 分支）

### 回退策略

- 旧路由 `/generate` 和 `/health` 保留为**直接响应**（调用同一 handler），不做重定向
- 如改造失败，可立即回退到旧路由（后端 `LocalModelStrategy` 切回 `/generate` 路径）
- 每个模型独立改造，互不影响

---

## 验证方式

每个模型改造后的验证：

```bash
# 健康检查
curl http://100.84.132.54:808X/v1/health

# 正常生成
curl -X POST http://100.84.132.54:808X/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"image": "<base64>", "seed": 42}' \
  --output test.glb

# 检查响应头
curl -v -X POST http://100.84.132.54:808X/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"image": "<base64>"}' \
  --output /dev/null 2>&1 | grep "X-Mesh"

# GPU 忙测试（并发两个请求）
# 第二个应返回 503 + retry_after

# 无效输入
curl -X POST http://100.84.132.54:808X/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"image": "not_valid_base64"}'
# 应返回 400

# 旧路由兼容（非重定向，直接 200）
curl -s -o /dev/null -w "%{http_code}" http://100.84.132.54:808X/health
# 应返回 200（非 3xx）

# 并发 503 测试
curl -X POST http://100.84.132.54:808X/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"image": "<base64>"}' &
sleep 1
curl -s -w "\n%{http_code}" -X POST http://100.84.132.54:808X/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"image": "<base64>"}'
# 第二个请求应返回 503 + retry_after
```
