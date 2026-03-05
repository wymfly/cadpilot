# 有机管道策略清理 + shell_node 设计

> 日期：2026-03-05
> 范围：后端有机管道的策略重构、节点清理、新增 shell_node
> 前置依赖：GPU Server API 标准化（`2026-03-05-gpu-server-api-standardization.md`）

---

## 背景

有机管道的 `generate_raw_mesh` 节点当前注册了 4 个策略，其中 2 个已过时：
- `tripo3d`：依赖 Replicate SaaS API，已决定不使用
- `spar3d`：模型已淘汰，GPU 服务器未部署

同时缺少本地 TripoSG 和 TRELLIS.2 的直连策略。默认策略仍是 `hunyuan3d`，按调研结论应改为 `triposg`。

管道还缺少 shell_node（抽壳节点），无法满足金属 3D 打印的中空薄壁需求。

---

## 一、策略清理

### 1.1 文件变更

| 操作 | 文件 | 说明 |
|------|------|------|
| 删除 | `strategies/generate/tripo3d.py` | SaaS 策略，已弃用 |
| 删除 | `strategies/generate/spar3d.py` | 模型已淘汰 |
| 新增 | `strategies/generate/triposg.py` | 本地 TripoSG（:8081） |
| 新增 | `strategies/generate/trellis2.py` | 本地 TRELLIS.2（:8082） |
| 重写 | `strategies/generate/hunyuan3d.py` | 去掉 SaaS 分支，统一走本地 API |
| 重写 | `strategies/generate/base.py` | `LocalModelStrategy` 改为 JSON+base64 协议 |
| 重写 | `configs/generate_raw_mesh.py` | 三端点配置 + 默认策略改 triposg |
| 更新 | `nodes/generate_raw_mesh.py` | 策略注册表更新，去掉 fallback_chain |

### 1.2 `LocalModelStrategy` 基类改造

**改前（multipart + /v1/generate）：**
```python
async def _post_generate(self, endpoint, image_data, params, timeout):
    url = f"{endpoint}/v1/generate"
    files = {"image": ("input.png", image_data, "image/png")}
    resp = await client.post(url, files=files, data=params)
```

**改后（JSON + base64 + /v1/generate）：**
```python
async def _post_generate(self, endpoint, image_b64, seed, params, timeout):
    url = f"{endpoint}/v1/generate"
    body = {"image": image_b64, "seed": seed, "params": params or {}}
    resp = await client.post(url, json=body)
    # 解析响应头 mesh 元信息
    mesh_meta = {
        "vertices": resp.headers.get("X-Mesh-Vertices"),
        "faces": resp.headers.get("X-Mesh-Faces"),
        "watertight": resp.headers.get("X-Mesh-Watertight", "").lower() == "true",
    }
    return resp.content, resp.headers.get("content-type"), mesh_meta
```

**503 重试策略：** 当 GPU 服务器返回 503（gpu_busy）时，`LocalModelStrategy` 读取 `Retry-After` 响应头。边界处理：header 缺失/非数字/负值 → 默认 30s。重试决策：如果 `retry_after + 300s（预估推理时间）> 剩余 timeout 预算`，直接抛出异常而非浪费唯一重试机会。否则等待后重试一次。`timeout` 配置作用于**单次 HTTP 请求**，总超时（含重试等待）由管道层控制。

### 1.3 三个策略的差异

三个策略继承 `LocalModelStrategy`，差异仅在：

| | triposg | trellis2 | hunyuan3d |
|--|---------|----------|-----------|
| config 字段 | triposg_endpoint | trellis2_endpoint | hunyuan3d_endpoint |
| 默认 params | `{}` | `{"simplify": 100000, "texture": false}` | `{"texture": false}` |
| 进度文案 | "TripoSG 生成中" | "TRELLIS.2 生成中" | "Hunyuan3D 生成中" |

金属打印场景下 TRELLIS.2 和 Hunyuan3D 的纹理生成是浪费，默认关闭。

### 1.4 GenerateRawMeshConfig 更新

```python
class GenerateRawMeshConfig(BaseNodeConfig):
    strategy: str = "triposg"  # 改默认

    triposg_endpoint: str | None = None
    trellis2_endpoint: str | None = None
    hunyuan3d_endpoint: str | None = None

    timeout: int = 330          # GPU 服务器内部 300s + 30s 网络余量
    output_format: str = "glb"
```

### 1.5 generate_raw_mesh 节点更新

```python
@register_node(
    name="generate_raw_mesh",
    strategies={
        "triposg": TripoSGGenerateStrategy,
        "trellis2": TRELLIS2GenerateStrategy,
        "hunyuan3d": Hunyuan3DGenerateStrategy,
    },
    default_strategy="triposg",
    # 无 fallback_chain — 用户显式选策略，失败即报错
)
```

**`auto` 策略处理：** 当前配置中 `strategy` 字段可能传入 `"auto"` 或无效值。移除 fallback_chain 后：
- `"auto"` → 视为 `"triposg"`（默认策略），在节点 `execute()` 入口处映射
- 无效策略名 → 抛出 `ValueError`，附带可用策略列表

```python
# 节点 execute() 入口
if config.strategy == "auto":
    config.strategy = "triposg"
if config.strategy not in self.strategies:
    raise ValueError(f"Unknown strategy '{config.strategy}', available: {list(self.strategies)}")
```

### 1.6 清理关联代码

| 文件 | 操作 |
|------|------|
| `infra/mesh_providers/tripo.py` | 检查是否还有其他引用，无则删除 |
| `strategies/generate/__init__.py` | 移除 tripo3d/spar3d 导出 |

---

## 二、shell_node 设计

### 2.1 节点定义

```python
@register_node(
    name="shell_node",
    display_name="抽壳",
    requires=["scaled_mesh"],
    produces=["shelled_mesh"],
    input_types=["organic"],
    config_model=ShellNodeConfig,
    strategies={"meshlib": MeshLibShellStrategy},
    default_strategy="meshlib",
    non_fatal=False,
    description="SDF 偏移抽壳，将实心 mesh 转为指定壁厚的中空薄壁体",
)
```

### 2.2 配置

```python
class ShellNodeConfig(BaseNodeConfig):
    strategy: str = "meshlib"
    wall_thickness: float = Field(2.0, gt=0, le=50.0)  # mm，壁厚（>0，上限 50mm）
    voxel_resolution: int = 0         # 0 = 自适应（根据 bbox 和 wall_thickness 计算，上限 512）
    shell_enabled: bool = False       # 默认不启用，用户显式开启
```

`shell_enabled=False` 时 passthrough：`scaled_mesh` → `shelled_mesh`（零成本）。

**失败策略：** `non_fatal=False`，抽壳失败时管道报错终止。原因：
- 用户显式开启 `shell_enabled=True` 说明中空是硬需求（如高尔夫球头）
- 如果抽壳失败静默跳过，下游打印的是实心体，浪费材料且不符合设计意图
- 失败时返回明确错误信息（如"布尔差集失败：mesh 非流形"），引导用户调整 `voxel_resolution` 或 `wall_thickness`

### 2.3 算法（MeshLib SDF offset）

**自适应分辨率：** `voxel_resolution=0` 时，根据 mesh bounding box 最大边长和壁厚自动计算：`resolution = min(512, max(256, ceil(bbox_max / wall_thickness * 5)))`。上限 512 防止内存爆炸（512^3 体素 ≈ 512MB，可接受），下限 256 保证基础精度，确保壁厚方向至少 5 个体素覆盖。

```
1. 加载 scaled_mesh (trimesh)
2. 转为 MeshLib 格式 (mr.Mesh)
3. 计算 SDF 体积 (mr.meshToVolume)
4. 在 offset = -wall_thickness 处提取内壁等值面 (mr.gridToMesh)
5. 布尔差集：外壳 - 内壁 = 中空体 (mr.boolean with BooleanOperation.DifferenceAB)
6. 验证：水密性 + 最小壁厚检查
7. 输出 shelled_mesh
```

### 2.4 管道位置

```
generate_raw_mesh → mesh_healer → mesh_scale → shell_node(新)
→ boolean_assemble → orientation_optimizer → generate_supports
→ thermal_simulation → apply_lattice → slice_to_gcode
```

`boolean_assemble` 需要以下变更：
1. `requires` 从 `["scaled_mesh"]` 改为 `["shelled_mesh"]`
2. `nodes/boolean_assemble.py` 第 49 行：`ctx.get_asset("scaled_mesh")` → `ctx.get_asset("shelled_mesh")`
3. `strategies/boolean/manifold3d.py` 第 43 行：`ctx.get_asset("scaled_mesh")` → `ctx.get_asset("shelled_mesh")`

shell_node 的 passthrough 模式保证了向后兼容：`shell_enabled=False` 时 `shelled_mesh` 就是 `scaled_mesh` 的直接传递。

**资产名解耦考量：** LangGraph 管道构建器通过 requires/produces 做拓扑排序，shell_node 必须始终存在于图中（即使 passthrough）。如果未来需要支持动态节点裁剪，应改为 shell_node 的 passthrough 输出仍注册为 `scaled_mesh`（原位覆盖），避免下游节点感知中间步骤。当前阶段保持 `shelled_mesh` 命名以明确语义。

### 2.5 新增文件

| 文件 | 说明 |
|------|------|
| `nodes/shell_node.py` | 节点注册 + passthrough 逻辑 |
| `configs/shell_node.py` | ShellNodeConfig |
| `strategies/shell/__init__.py` | 包初始化 |
| `strategies/shell/meshlib_shell.py` | MeshLibShellStrategy 实现 |

---

## 三、验证方式

### 策略清理验证

```bash
# 单元测试
uv run pytest tests/ -v -k "generate_raw_mesh or strategy"

# 集成测试（需 GPU server 运行）
# 配置 triposg_endpoint=http://100.84.132.54:8081
# 发送图片 → 检查返回 GLB + 水密性
```

### shell_node 验证

```bash
# 单元测试：passthrough 模式（shell_enabled=False）
#   → 验证 shelled_mesh == scaled_mesh（零拷贝传递）
# 单元测试：抽壳模式（mock MeshLib，验证调用参数）
#   → 验证 meshToVolume / gridToMesh / boolean 调用序列
#   → 验证 wall_thickness / voxel_resolution 参数传递
# 单元测试：抽壳失败（non_fatal=False）
#   → 验证抛出异常而非静默跳过
# 集成测试：实心球体 → 抽壳 → 验证中空（体积减少 + 水密）
```

### boolean_assemble 兼容验证

```bash
# 验证 boolean_assemble 读取 shelled_mesh（非 scaled_mesh）
# 验证 passthrough 模式下 boolean_assemble 正常工作（shelled_mesh = scaled_mesh）
```

### 策略边界测试

```bash
# strategy="auto" → 等同 "triposg"
# strategy="invalid_name" → 抛出 ValueError
# endpoint 不可达 → 健康检查失败，明确报错
```
