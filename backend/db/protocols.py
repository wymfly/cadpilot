"""存储抽象接口 — JobRepository + FileStorage Protocol。

通过 Protocol 定义存储接口，实现可替换的后端：
- SQLiteJobRepository → PostgresJobRepository（通过 DATABASE_URL 切换）
- LocalFileStorage → S3FileStorage（通过 STORAGE_BACKEND 切换）
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from backend.db.models import JobModel, OrganicJobModel, UserCorrectionModel


@runtime_checkable
class JobRepository(Protocol):
    """Job 数据访问协议。"""

    async def create(self, job_id: str, **kwargs: Any) -> JobModel: ...

    async def get(self, job_id: str) -> JobModel | None: ...

    async def update(self, job_id: str, **kwargs: Any) -> JobModel: ...

    async def soft_delete(self, job_id: str) -> None: ...

    async def list(
        self,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        input_type: str | None = None,
    ) -> tuple[list[JobModel], int]: ...


@runtime_checkable
class OrganicJobRepository(Protocol):
    """OrganicJob 数据访问协议。"""

    async def create(self, job_id: str, **kwargs: Any) -> OrganicJobModel: ...

    async def get(self, job_id: str) -> OrganicJobModel | None: ...

    async def update(self, job_id: str, **kwargs: Any) -> OrganicJobModel: ...

    async def list(
        self,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
    ) -> tuple[list[OrganicJobModel], int]: ...


@runtime_checkable
class CorrectionRepository(Protocol):
    """UserCorrection 数据访问协议。"""

    async def create(self, **kwargs: Any) -> UserCorrectionModel: ...

    async def list_by_job(self, job_id: str) -> list[UserCorrectionModel]: ...


@runtime_checkable
class FileStorage(Protocol):
    """文件存储协议。"""

    async def save(self, job_id: str, filename: str, data: bytes) -> str:
        """保存文件，返回可访问的 URL 路径。"""
        ...

    async def get_path(self, job_id: str, filename: str) -> str:
        """获取文件的本地路径。"""
        ...

    async def exists(self, job_id: str, filename: str) -> bool:
        """检查文件是否存在。"""
        ...

    async def delete(self, job_id: str, filename: str) -> None:
        """删除文件。"""
        ...
