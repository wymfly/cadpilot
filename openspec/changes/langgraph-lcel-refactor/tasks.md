## 1. LCEL Chain 基础设施

- [ ] 1.1 创建 `backend/graph/chains/__init__.py` 模块结构和 re-export
- [ ] 1.2 实现 `backend/graph/chains/fix_chain.py`: `build_fix_chain()` — 将 `SmartFixChain` 转为 LCEL Runnable（`prompt | llm.with_retry() | parser`），复用 `smart_refiner._parse_code()`
- [ ] 1.3 为 `build_fix_chain()` 编写测试：mock LLM 返回 Python 代码块 → 验证解析结果，mock 返回空文本 → 验证返回 None
- [ ] 1.4 实现 `backend/graph/chains/compare_chain.py`: `build_compare_chain(structured=False)` — 将 `SmartCompareChain` 转为 LCEL Runnable，含两张图的 `ImagePromptTemplate`，复用 `smart_refiner._extract_comparison()`
- [ ] 1.5 为 `build_compare_chain()` 编写测试：mock VL 返回 "PASS" → 验证 result=None，mock 返回差异描述 → 验证 result=差异文本，验证 structured=True 使用不同 prompt
- [ ] 1.6 实现 `backend/graph/chains/code_gen_chain.py`: `build_code_gen_chain()` — 将 `CodeGeneratorChain` 转为 LCEL Runnable，复用 `code_generator._parse_code()`
- [ ] 1.7 为 `build_code_gen_chain()` 编写测试：mock LLM 返回带 \`\`\`python 包裹的代码 → 验证解析，验证 prompt 中包含 modeling_context 变量
- [ ] 1.8 实现 `backend/graph/chains/vision_chain.py`: `build_vision_analysis_chain()` — 将 `DrawingAnalyzerChain` 转为 LCEL Runnable，含 `ImagePromptTemplate`，复用 `drawing_analyzer._parse_drawing_spec()`
- [ ] 1.9 为 `build_vision_analysis_chain()` 编写测试：mock VL 返回含 DrawingSpec JSON 的文本 → 验证解析为 DrawingSpec 对象，mock 返回无效 JSON → 验证 result=None
- [ ] 1.10 运行全部 chain 测试并提交：`uv run pytest tests/test_lcel_chains.py -v`

## 2. Refiner 子图

- [ ] 2.1 定义 `RefinerState` TypedDict 和状态映射函数（`CadJobState ↔ RefinerState`），放在 `backend/graph/subgraphs/refiner.py`
- [ ] 2.2 实现 `static_diagnose` 节点：调用 `validate_code_params()` + `validate_bounding_box()` + 可选 `compare_topology()`，结果写入 `static_notes`
- [ ] 2.3 实现 `render_for_compare` 节点：渲染 STEP → PNG（支持多视角降级到单视角）
- [ ] 2.4 实现 `vl_compare` 节点：调用 `build_compare_chain()` 进行 VL 对比，解析 verdict（pass/fail），派发 `job.refining` SSE 事件
- [ ] 2.5 实现 `coder_fix` 节点：调用 `build_fix_chain()` 修复代码，合并 VL 反馈 + static_notes，派发 `job.refining` SSE 事件
- [ ] 2.6 实现 `re_execute` 节点：沙箱执行修复后的代码，集成 `RollbackTracker` 检测分数退化
- [ ] 2.7 实现 `build_refiner_subgraph()`: 组装 `static_diagnose → render → vl_compare → [pass: END, fail: coder_fix → re_execute → round_check → conditional_edge]` 子图拓扑
- [ ] 2.8 为子图编写集成测试：mock 所有 LLM chain，验证 1 轮 PASS 退出、3 轮 max_rounds 退出、rollback 场景
- [ ] 2.9 运行 refiner 子图测试并提交：`uv run pytest tests/test_refiner_subgraph.py -v`

## 3. 节点层迁移——analyze_vision_node

- [ ] 3.1 重写 `analyze_vision_node`: 移除 `asyncio.to_thread(_run_analyze_vision)`，改为直接 `await build_vision_analysis_chain().ainvoke({"image_type": ..., "image_data": ...})`
- [ ] 3.2 在节点中内联 OCR fusion 调用（`fuse_ocr_with_spec()`），保持 graceful degradation
- [ ] 3.3 保留 `_cost_optimizer` 结果缓存逻辑（cache hit 时跳过 LLM）
- [ ] 3.4 更新 `tests/test_drawing_analyzer.py`: mock 从 `DrawingAnalyzerChain.invoke` 改为 mock `build_vision_analysis_chain` 返回的 Runnable
- [ ] 3.5 运行 vision 节点测试：`uv run pytest tests/test_drawing_analyzer.py tests/test_graph_nodes.py -v -k vision`

## 4. 节点层迁移——generate_step_drawing_node

- [ ] 4.1 重写 `generate_step_drawing_node`: 移除 `asyncio.to_thread(_run_generate_from_spec)`，改为内联编排
- [ ] 4.2 内联 Stage 1.5 逻辑：调用 `ModelingStrategist.select(spec)` + API whitelist injection（从 `pipeline.py` 迁移）
- [ ] 4.3 内联 Stage 2 单路生成：`await build_code_gen_chain().ainvoke()` + `Template.safe_substitute()` + `execute_python_code()`
- [ ] 4.4 内联 Stage 2 Best-of-N 并发生成：`asyncio.gather(*[chain.ainvoke(ctx) for _ in range(N)])`，每个候选用独立 tempdir 执行和评分
- [ ] 4.5 内联 Stage 3.5 几何验证：`validate_step_geometry()`
- [ ] 4.6 集成 refiner 子图调用：构造 `RefinerState`，调用 `refiner_subgraph.ainvoke(state)`，提取 refined code
- [ ] 4.7 内联 Stage 5 后置检查：`cross_section_analysis()`
- [ ] 4.8 更新 generation 节点测试：mock LCEL chain + subgraph，验证编排流程
- [ ] 4.9 运行 generation 节点测试：`uv run pytest tests/test_generation_nodes.py -v`

## 5. pipeline.py 清理

- [ ] 5.1 删除 `pipeline.py` 中的 `analyze_vision_spec()` 函数（节点已不再调用）
- [ ] 5.2 删除 `pipeline.py` 中的 `generate_step_from_spec()` 函数（节点已不再调用）
- [ ] 5.3 更新 `analyze_and_generate_step()` 函数使其仍可用（CLI/benchmark 入口）——暂时保留对旧 Chain 的调用，标记 `# TODO: migrate to LCEL`
- [ ] 5.4 清理 `pipeline.py` 顶部未使用的 import（`DrawingAnalyzerChain`、`CodeGeneratorChain`、`SmartRefiner` 如果 `analyze_and_generate_step` 仍用则保留）
- [ ] 5.5 运行全量测试确认无回归：`uv run pytest tests/ -v`

## 6. 旧 Chain 类标记 deprecated

- [ ] 6.1 在 `DrawingAnalyzerChain`、`CodeGeneratorChain`、`SmartCompareChain`、`SmartFixChain` 类上添加 `@deprecated("使用 backend.graph.chains 中的 build_*_chain() 替代")` 装饰器
- [ ] 6.2 删除 `_run_analyze_vision()` 和 `_run_generate_from_spec()` 同步包装函数（已无调用方）
- [ ] 6.3 更新 `tests/test_smart_refiner.py`: mock 从 `SmartCompareChain.invoke` / `SmartFixChain.invoke` 改为 mock LCEL chain
- [ ] 6.4 运行全量测试并提交：`uv run pytest tests/ -v`

## 7. 验证与文档

- [ ] 7.1 Grep 验证无 `asyncio.to_thread` 调用 vision/generation 同步函数：`git grep "to_thread.*_run_analyze\|to_thread.*_run_generate"` 应返回 0 结果
- [ ] 7.2 Grep 验证 LangGraph 节点不直接 import SequentialChain：`git grep "from.*SequentialChain\|import.*SequentialChain" backend/graph/` 应返回 0 结果
- [ ] 7.3 TypeScript 编译检查：`cd frontend && npx tsc --noEmit`（确保前端不受影响）
- [ ] 7.4 更新 CLAUDE.md 架构描述：反映 LCEL chain + refiner subgraph 新模式
- [ ] 7.5 全量测试最终确认：`uv run pytest tests/ -v` — 所有测试通过
