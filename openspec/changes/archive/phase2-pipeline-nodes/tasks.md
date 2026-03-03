## 1. [backend] 导出基础设施

- [ ] 1.1 创建 `backend/core/mesh_converter.py` — `convert_mesh()` 工具函数，支持 OBJ/GLB/STL/3MF 互转 + 同格式 shutil.copy2 passthrough + 不支持格式 ValueError + 输出文件名使用 `{stem}.{format}` 避免冲突
- [ ] 1.2 [test] 编写 `tests/test_mesh_converter.py` — 格式转换单元测试（正常转换、同格式 copy、不支持格式）
- [ ] 1.3 创建 `backend/api/routes/export.py` — `GET /api/jobs/{job_id}/assets/{asset_key}` 端点，`format` 参数默认 None（返回原始格式），转换通过 `asyncio.to_thread(convert_mesh, ...)` 异步执行，每次转换使用独立 tempdir，ValueError 捕获返回 400，background_tasks 清理 tmpdir
- [ ] 1.4 [test] 编写导出端点集成测试 — 原始格式下载、格式转换下载、不支持格式 400、404 场景、tmpdir 清理验证

## 2. [backend] mesh_scale 实现

- [ ] 2.1 重写 `backend/graph/nodes/mesh_scale.py` — 从 stub 替换为真实均匀缩放（从 `MeshPostProcessor.scale_mesh()` 提取 + 新增底面贴合），执行顺序：均匀缩放 → 底面贴合 Z=0 → XY 质心居中。无目标尺寸时 passthrough
- [ ] 2.2 [test] 编写/更新 `tests/test_mesh_pipeline.py` 中 mesh_scale 测试 — 缩放、对齐顺序验证、passthrough、无输入跳过

## 3. [backend] boolean_assemble

- [ ] 3.1 创建 `backend/graph/configs/boolean_assemble.py` — BooleanAssembleConfig（strategy、voxel_resolution、skip_on_non_manifold）
- [ ] 3.2 创建 `backend/graph/strategies/boolean/manifold3d.py` — Manifold3DStrategy，从 `MeshPostProcessor.apply_boolean_cuts()` 提取布尔运算核心逻辑
- [ ] 3.3 实现流形校验门 — is_manifold_check()（trimesh.is_watertight）+ force_voxelize()（manifold3d 体素化）+ 2x 分辨率重试一次 + skip_on_non_manifold=False（默认）时修复失败抛出异常 + skip_on_non_manifold=True 时 passthrough 并警告
- [ ] 3.4 创建 `backend/graph/nodes/boolean_assemble.py` — 节点注册（strategies={"manifold3d": ...}），包含：上游缺失跳过 + 无 engineering_cuts 时 passthrough + quality_mode="draft" 时 passthrough + progress reporting
- [ ] 3.5 [test] 编写 `tests/test_boolean_assemble.py` — 注册测试、流形 passthrough、非流形修复、非流形修复失败（skip=False 抛异常 / skip=True passthrough）、2x 分辨率重试、切割操作（flat_bottom/hole/slot）、单切割失败不中断（标记 partial_cuts）、全部切割失败抛异常、无 cuts passthrough、draft 模式跳过、无输入跳过
- [ ] 3.6 删除 `backend/graph/nodes/boolean_cuts.py` stub 节点 + 删除 `backend/graph/nodes/export_formats.py` 节点，更新 `tests/test_mesh_pipeline.py` 移除相关测试并替换为 boolean_assemble + mesh_scale 测试

## 4. [backend] generate_raw_mesh

- [ ] 4.1 创建 `backend/graph/configs/generate_raw_mesh.py` — GenerateRawMeshConfig（per-model api_key/endpoint 字段 + timeout + output_format）
- [ ] 4.2 创建 `backend/graph/strategies/generate/base.py` — 本地部署基类（LocalModelStrategy），仅封装 POST /v1/generate 调用 + health check（带 TTL 缓存），不含 SaaS 回退逻辑（SPAR3D/TRELLIS 是 local-only，SaaS 回退由 Hunyuan3D 策略自行实现）
- [ ] 4.3 创建 `backend/graph/strategies/generate/hunyuan3d.py` — Hunyuan3DGenerateStrategy，内部按 config 选择 SaaS（复用 HunyuanProvider）或本地 endpoint，check_available() 支持 local 不健康回退 SaaS，execute() 支持 local 失败回退 SaaS
- [ ] 4.4 创建 `backend/graph/strategies/generate/tripo3d.py` — Tripo3DGenerateStrategy，包装现有 TripoProvider（SaaS only）
- [ ] 4.5 创建 `backend/graph/strategies/generate/spar3d.py` — SPAR3DGenerateStrategy（本地 only，POST /v1/generate）
- [ ] 4.6 创建 `backend/graph/strategies/generate/trellis.py` — TRELLISGenerateStrategy（本地 only，POST /v1/generate）
- [ ] 4.7 创建 `backend/graph/nodes/generate_raw_mesh.py` — 节点注册（4 个策略 + fallback_chain），NodeContext 签名，SSE 进度通过 ctx.dispatch_progress()，超时 fallback 到下一策略
- [ ] 4.8 在 `backend/graph/nodes/organic.py` 中移除 `generate_organic_mesh_node` 的 `@register_node` 装饰器，保留为适配器函数（接受 CadJobState 签名，内部封装为 NodeContext 后委托给 generate_raw_mesh_node，再将产物同步回 state），避免 NodeRegistry asset conflict 和签名不兼容崩溃
- [ ] 4.9 [test] 编写 `tests/test_generate_raw_mesh.py` — 注册测试、各策略 check_available 测试（含 local-only 不可用返回 False、dual-deploy 本地不健康回退 SaaS 返回 True）、SaaS/本地双部署 mock 测试、fallback 测试、超时 fallback 测试、运行时错误 fallback 测试、所有策略耗尽失败测试、SSE 进度测试、legacy 适配器测试（CadJobState→NodeContext 桥接）、put_asset format 动态推导测试
- [ ] 4.10 [test] 验证 builder_legacy.py 仍能正常导入和运行

## 5. [backend] slice_to_gcode

- [ ] 5.1 创建 `backend/graph/configs/slice_to_gcode.py` — SliceToGcodeConfig（prusaslicer_path、orcaslicer_path、layer_height[0.05-0.6]、fill_density[0-100]、support_material、nozzle_diameter、filament_type、timeout=120）
- [ ] 5.2 创建 `backend/graph/strategies/slice/prusaslicer.py` — PrusaSlicerStrategy，可配置 CLI 路径（config.prusaslicer_path 或 shutil.which）+ CLI 参数构建（必须透传 nozzle_diameter、filament_type 等硬件参数）+ asyncio subprocess + 超时 fallback + runtime error fallback + check_available() 检测
- [ ] 5.3 创建 `backend/graph/strategies/slice/orcaslicer.py` — OrcaSlicerStrategy，OrcaSlicer CLI 适配（参数格式差异：fill_density 不带百分号、nozzle_diameter/filament_type 参数名映射等）
- [ ] 5.4 创建 `backend/core/gcode_parser.py` — G-code 元数据解析（层数、G1 指令数、耗材用量、预估打印时间），支持多种切片器注释格式（PrusaSlicer: `; estimated printing time` / OrcaSlicer: `; total estimated time` 等），优先匹配已知模式，未匹配返回空 dict + 警告
- [ ] 5.5 创建 `backend/graph/nodes/slice_to_gcode.py` — 节点注册（OR 依赖、2 策略 + fallback_chain），best mesh 选择逻辑 + 格式转换（GLB→STL via convert_mesh）
- [ ] 5.6 [test] 编写 `tests/test_slice_to_gcode.py` — 注册测试、CLI mock 测试（含 nozzle_diameter/filament_type 参数验证）、best mesh 选择、gcode 解析（PrusaSlicer 格式 + OrcaSlicer 格式 + 解析失败）、CLI 未安装跳过、超时 fallback、runtime error fallback、所有策略耗尽失败

## 6. [backend][test] 集成验证 + Legacy 废弃

- [ ] 6.1 [test] 端到端集成测试 — 完整 organic 管线（generate_raw_mesh → mesh_healer → mesh_scale → boolean_assemble → slice_to_gcode）跑通（AI 模型用 mock strategy）
- [ ] 6.2 [test] DependencyResolver 验证 — 确认新管线拓扑排序正确，export_formats 和 boolean_cuts 不出现，generate_organic_mesh 不重复注册
- [ ] 6.3 更新 `finalize_node` — 读取 PipelineState.assets 中新架构产物（raw_mesh、watertight_mesh、final_mesh、gcode_bundle），确保前端可获取 model_url 等信息
- [ ] 6.4 在 `backend/graph/nodes/organic.py` 中标记 `postprocess_organic_node` 为 `@deprecated`
- [ ] 6.5 删除 `backend/infra/mesh_providers/auto.py`（AutoProvider），更新 `__init__.py` 导出
- [ ] 6.6 [test] 运行完整测试套件 + lint 验证
