"""Tests for AssetStore Protocol and LocalAssetStore implementation."""

import os
import pytest
from pathlib import Path


class TestLocalAssetStoreSaveLoad:
    def test_save_and_load(self, tmp_path):
        from backend.graph.asset_store import LocalAssetStore

        store = LocalAssetStore(workspace=tmp_path)
        data = b"mesh data here"
        uri = store.save(job_id="j1", name="mesh", data=data, fmt="obj")

        assert "j1" in uri
        assert "mesh.obj" in uri

        loaded = store.load(uri)
        assert loaded == data

    def test_load_nonexistent_raises(self, tmp_path):
        from backend.graph.asset_store import LocalAssetStore

        store = LocalAssetStore(workspace=tmp_path)
        with pytest.raises(FileNotFoundError):
            store.load(f"file://{tmp_path}/jobs/nonexistent/mesh.obj")

    def test_directory_auto_created(self, tmp_path):
        from backend.graph.asset_store import LocalAssetStore

        store = LocalAssetStore(workspace=tmp_path)
        store.save(job_id="j1", name="out", data=b"x", fmt="stl")
        # Should not raise — directory created automatically

    def test_overwrite_existing(self, tmp_path):
        from backend.graph.asset_store import LocalAssetStore

        store = LocalAssetStore(workspace=tmp_path)
        uri1 = store.save(job_id="j1", name="mesh", data=b"old", fmt="obj")
        uri2 = store.save(job_id="j1", name="mesh", data=b"new", fmt="obj")

        assert uri1 == uri2
        assert store.load(uri1) == b"new"

    def test_workspace_from_env(self, tmp_path, monkeypatch):
        from backend.graph.asset_store import LocalAssetStore

        monkeypatch.setenv("CADPILOT_WORKSPACE", str(tmp_path))
        store = LocalAssetStore()
        uri = store.save(job_id="j1", name="test", data=b"data", fmt="bin")
        assert str(tmp_path) in uri

    def test_workspace_default_cwd(self, tmp_path, monkeypatch):
        from backend.graph.asset_store import LocalAssetStore

        monkeypatch.delenv("CADPILOT_WORKSPACE", raising=False)
        monkeypatch.chdir(tmp_path)
        store = LocalAssetStore()
        uri = store.save(job_id="j1", name="test", data=b"data", fmt="bin")
        assert str(tmp_path.resolve()) in uri

    def test_path_traversal_rejected(self, tmp_path):
        from backend.graph.asset_store import LocalAssetStore

        store = LocalAssetStore(workspace=tmp_path)
        with pytest.raises(ValueError, match="workspace boundary"):
            store.save(
                job_id="../../../etc", name="passwd",
                data=b"evil", fmt="txt",
            )

    def test_path_traversal_in_name_rejected(self, tmp_path):
        from backend.graph.asset_store import LocalAssetStore

        store = LocalAssetStore(workspace=tmp_path)
        with pytest.raises(ValueError, match="workspace boundary"):
            store.save(
                job_id="j1", name="../../etc/passwd",
                data=b"evil", fmt="txt",
            )


class TestAssetStoreProtocol:
    def test_local_implements_protocol(self):
        from backend.graph.asset_store import AssetStore, LocalAssetStore

        store = LocalAssetStore()
        assert isinstance(store, AssetStore)
