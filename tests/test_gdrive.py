"""Tests for Google Drive integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from storageanalyser import gdrive
from storageanalyser.web.server import app


class TestGDriveAPI:
    def test_status_unconfigured(self) -> None:
        with patch.object(gdrive, "is_configured", return_value=False), \
             patch.object(gdrive, "has_token", return_value=False):
            with TestClient(app) as client:
                response = client.get("/api/gdrive/status")
                assert response.status_code == 200
                data = response.json()
                assert data["configured"] is False
                assert data["authenticated"] is False

    def test_status_configured(self) -> None:
        with patch.object(gdrive, "is_configured", return_value=True), \
             patch.object(gdrive, "has_token", return_value=True):
            with TestClient(app) as client:
                response = client.get("/api/gdrive/status")
                data = response.json()
                assert data["configured"] is True
                assert data["authenticated"] is True

    def test_result_404_before_scan(self) -> None:
        import storageanalyser.web.server as srv
        srv._gdrive_result = None
        with TestClient(app) as client:
            response = client.get("/api/gdrive/result")
            assert response.status_code == 404

    def test_disconnect(self) -> None:
        with patch.object(gdrive, "disconnect") as mock_disconnect:
            with TestClient(app) as client:
                response = client.post("/api/gdrive/disconnect")
                assert response.status_code == 200
                mock_disconnect.assert_called_once()


class TestGDriveModule:
    def test_is_configured_false(self, tmp_path: Path) -> None:
        with patch.object(gdrive, "CREDENTIALS_FILE", tmp_path / "nope.json"):
            assert gdrive.is_configured() is False

    def test_has_token_false(self, tmp_path: Path) -> None:
        with patch.object(gdrive, "TOKEN_FILE", tmp_path / "nope.json"):
            assert gdrive.has_token() is False

    def test_save_credentials(self, tmp_path: Path) -> None:
        creds_file = tmp_path / "creds.json"
        config_dir = tmp_path
        with patch.object(gdrive, "CREDENTIALS_FILE", creds_file), \
             patch.object(gdrive, "CONFIG_DIR", config_dir):
            gdrive.save_credentials({"installed": {"client_id": "test"}})
            assert creds_file.exists()
            import json
            data = json.loads(creds_file.read_text())
            assert data["installed"]["client_id"] == "test"

    def test_disconnect_removes_token(self, tmp_path: Path) -> None:
        token_file = tmp_path / "token.json"
        token_file.write_text("{}")
        with patch.object(gdrive, "TOKEN_FILE", token_file):
            gdrive.disconnect()
            assert not token_file.exists()
