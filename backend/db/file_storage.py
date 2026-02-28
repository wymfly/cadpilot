"""本地文件存储实现 — FileStorage Protocol。

将生成的 STEP/GLB/STL/3MF 文件存储在 outputs/{job_id}/ 目录下。
"""

from __future__ import annotations

import asyncio
from pathlib import Path


class LocalFileStorage:
    """本地磁盘文件存储，实现 FileStorage Protocol。"""

    def __init__(self, base_dir: str | Path = "outputs") -> None:
        self._base_dir = Path(base_dir).resolve()

    def _job_dir(self, job_id: str) -> Path:
        return self._base_dir / job_id

    async def save(self, job_id: str, filename: str, data: bytes) -> str:
        """保存文件到 outputs/{job_id}/{filename}，返回 URL 路径。"""
        job_dir = self._job_dir(job_id)

        def _write() -> None:
            job_dir.mkdir(parents=True, exist_ok=True)
            (job_dir / filename).write_bytes(data)

        await asyncio.to_thread(_write)
        return f"/outputs/{job_id}/{filename}"

    async def get_path(self, job_id: str, filename: str) -> str:
        """返回文件的绝对路径。"""
        return str(self._job_dir(job_id) / filename)

    async def exists(self, job_id: str, filename: str) -> bool:
        """检查文件是否存在。"""
        path = self._job_dir(job_id) / filename
        return await asyncio.to_thread(path.exists)

    async def delete(self, job_id: str, filename: str) -> None:
        """删除文件。"""
        path = self._job_dir(job_id) / filename

        def _remove() -> None:
            if path.exists():
                path.unlink()

        await asyncio.to_thread(_remove)
