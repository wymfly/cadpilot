## Context

cad3dify V3 当前实现了机械引擎管道（CadQuery 代码生成），通过 SSE 流式推送进度，支持文本和图纸两种输入模式。该管道已 E2E 验证通过。

现在需要新增一条完全独立的有机引擎管道，处理自由曲面零件（高尔夫球头、手柄、雕塑等）。核心技术路径：云端 AI 3D 生成 API + 计算几何后处理（修复/缩放/布尔切削）。

**详细设计文档：** [docs/plans/2026-02-27-organic-engine-productization-design.md](../../../docs/plans/2026-02-27-organic-engine-productization-design.md)

## Goals / Non-Goals

**Goals:**
- 支持 Text-to-3D 和 Image-to-3D 两种输入模式
- 通过工程后处理（尺寸约束、平底切削、安装孔）输出可打印工业件
- 独立管道，零侵入现有机械管道代码（feature-gate + 懒加载重型依赖）
- 导航重构，清晰区分两条产品线
- 机械管道回归保护（冒烟测试在合并前必须通过）

**Non-Goals:**
- 不替代现有机械管道（精密零件仍走 CadQuery）
- 不实现本地 3D 生成模型部署（MVP 阶段仅云 API）
- 不实现有机 ↔ 机械的混合生成模式
- 不实现有机模型的迭代修复循环（AI 网格无法像代码一样迭代）

## Decisions

### D1: 完全独立管道（方案 A）

独立 API、独立前端页面、独立状态管理，不侵入现有机械管道。

**替代方案被否决：**
- 统一管道 + 策略分叉（方案 B）：侵入现有代码，两种管道状态机差异大，耦合风险高
- 共享基础设施 + 独立管道（方案 C）：初期实现成本与 A 接近，需抽象层重构

**理由：** 机械管道刚 E2E 验证通过，零风险优先。两条管道稳定后可提取共享层（Job store 契约、SSE 信封 schema、输出路径工具函数）。

### D2: Tripo3D（主）+ Hunyuan3D（备）

**替代方案被否决：**
- Rodin/Hyper3D：网格质量最优但成本高（$0.30-2.00/次），中国访问需代理
- Meshy：需代理访问，延迟较高（60-300s）
- Sloyd：偏游戏资产，不适合工程场景

**理由：** 两者均为国内公司/云服务，直连无需代理，成本低，有开源 fallback。

### D3: manifold3d 布尔运算

**替代方案被否决：**
- trimesh 布尔：官方文档明确声明"通常不可靠"
- CGAL/OpenSCAD：C++ 依赖重，Python 绑定不成熟

**理由：** manifold3d 是唯一保证输出仍为 manifold 的库，对 3D 打印至关重要。

### D6: PyMeshLab GPL v3 许可证策略

项目主体为 MIT 许可，PyMeshLab 为 GPL v3。

**策略：** MVP 阶段使用 PyMeshLab 作为可选依赖（进程隔离或微服务调用），不静态链接。若需闭源分发，切换到 manifold3d 自带的网格修复能力（`Manifold.of()` + 自动修复）+ trimesh 基础修复（非 GPL）。

**理由：** PyMeshLab 的工业级修复能力对 MVP 质量关键，但许可证风险已识别并有明确退出路径。

### D7: Organic router feature-gate 与懒加载

**策略：** organic router 始终挂载（避免未挂载产生 404 歧义），但每个 handler 内部检查 `ORGANIC_ENABLED` 配置，禁用时统一返回 HTTP 503 Service Unavailable。重型依赖（manifold3d、pymeshlab）在 handler/processor 内部懒加载，而非 module-level import。依赖不可用时同样返回 503。

**理由：** 始终挂载 + handler 内检查的方案统一了禁用语义（503），避免 404/503 歧义，同时确保 organic 管道的依赖问题不影响现有机械管道的可用性。

### D8: EngineeringCut discriminated union 设计

**策略：** `EngineeringCut` 使用 Pydantic discriminated union（`Literal` discriminator on `type` field），每种类型（`FlatBottomCut`、`HoleCut`、`SlotCut`）有独立的必填字段和数值边界约束。`OrganicConstraints.engineering_cuts` 使用 `Field(default_factory=list)` 避免可变默认值。

**理由：** 强类型约束在数据层阻止无效切削参数到达几何代码，减少运行时错误。

### D4: 独立前端入口 + 导航重构

前端新增 `/generate/organic` 独立页面，侧边栏重构为二级菜单（精密建模子组 + 创意雕塑独立入口）。

**替代方案被否决：**
- 统一入口 + 模式切换：降低学习成本但 UI 复杂度高
- AI 自动路由：误判风险高，实现复杂

**理由：** 两条管道的输入形式和工作流差异大，独立入口更清晰。

### D5: 后处理管线顺序

PyMeshLab 修复 → trimesh 缩放 → manifold3d 布尔 → 质量校验

**理由：** 先修复保证布尔输入质量；缩放在布尔前以确保工程接口尺寸精确；布尔后二次校验捕获潜在问题。

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|---------|
| AI 网格不 watertight | PyMeshLab 修复 + manifold3d 保证布尔输出 manifold |
| manifold3d 对低质量网格布尔失败 | 先 PyMeshLab 修复；失败时跳过布尔返回仅修复版本 |
| Tripo3D API 不稳定/超时 | Hunyuan3D 自动 fallback + 超时重试 |
| PyMeshLab GPL v3 许可传染性 | 可选依赖 + 进程隔离；闭源时切换 manifold3d 自带修复（见 D6） |
| AI 生成结果不符合预期 | 质量档位让用户选择精度/速度平衡 |
| organic 依赖导入崩溃影响全局 API | feature-gate + 懒加载重型依赖，503 降级（见 D7） |
| 客户端断连孤立付费任务 | Job 持久化 + GET /organic/{job_id} 恢复端点 |
| 布尔切削精度期望不现实 | 公差模型：standard ±0.2mm，high ±0.1mm（见 spec 更新） |
