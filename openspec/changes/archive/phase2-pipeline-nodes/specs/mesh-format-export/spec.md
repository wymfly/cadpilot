## ADDED Requirements

### Requirement: Format conversion utility function
系统 SHALL 提供 `convert_mesh(input_path, output_format, output_dir)` 工具函数，支持 OBJ、GLB、STL、3MF 格式互转。

#### Scenario: Convert OBJ to STL
- **WHEN** 调用 `convert_mesh("/jobs/123/mesh.obj", "stl", output_dir)`
- **THEN** 生成 `output_dir/mesh.stl` 文件（输出文件名使用 `{stem}.{format}`），内容为等价的 STL 网格

#### Scenario: Same format passthrough
- **WHEN** 输入格式与目标格式相同
- **THEN** 使用 shutil.copy2 直接复制文件，不做 trimesh 加载/导出（保留原始文件完整性，避免丢失纹理等元数据）

#### Scenario: Unsupported format
- **WHEN** 目标格式不在支持列表中
- **THEN** 抛出 ValueError，附带支持格式列表

### Requirement: Asset export API endpoint
系统 SHALL 提供 `GET /api/jobs/{job_id}/assets/{asset_key}` 端点，支持 `format` 查询参数，按需转换并下载任意节点产物。

#### Scenario: Export asset in original format
- **WHEN** 请求 `GET /api/jobs/123/assets/watertight_mesh`（不指定 format 参数）
- **THEN** 返回原始格式文件（FileResponse），不做任何转换

#### Scenario: Export asset in different format
- **WHEN** 请求 `GET /api/jobs/123/assets/watertight_mesh?format=stl`
- **THEN** 通过 asyncio.to_thread(convert_mesh, ...) 异步转换后返回 STL 文件（避免阻塞事件循环）

#### Scenario: Converted file uses unique name
- **WHEN** 多个客户端同时请求同一 asset 的不同格式
- **THEN** 每次转换使用独立临时目录（如 tempfile.mkdtemp），避免文件名冲突

#### Scenario: Unsupported format requested
- **WHEN** 请求 `GET /api/jobs/123/assets/watertight_mesh?format=xyz`（不在支持列表中）
- **THEN** 返回 HTTP 400 Bad Request，附带支持格式列表（convert_mesh 抛出 ValueError 被路由捕获）

#### Scenario: Asset not found
- **WHEN** 请求的 job_id 或 asset_key 不存在
- **THEN** 返回 HTTP 404

#### Scenario: Temp directory cleanup after response
- **WHEN** 格式转换完成并返回文件
- **THEN** 通过 FastAPI background_tasks 在响应发送后清理临时目录，避免磁盘泄漏

#### Scenario: Export at any pipeline stage
- **WHEN** 管线执行到 mesh_healer 节点完成后
- **THEN** 用户可通过 API 导出 `watertight_mesh` 资产的任意格式，无需等待管线完成
