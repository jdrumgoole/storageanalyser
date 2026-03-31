"""Tests for the web frontend."""

from __future__ import annotations

import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from storageanalyser.models import Category, Recommendation, ScanResult
from storageanalyser.web.server import app, scan_manager

_IS_WINDOWS = sys.platform == "win32"


class TestWebPages:
    def test_index_returns_200(self) -> None:
        with TestClient(app) as client:
            response = client.get("/")
            assert response.status_code == 200
            assert "StorageAnalyser" in response.text

    def test_static_css_accessible(self) -> None:
        with TestClient(app) as client:
            response = client.get("/static/app.css")
            assert response.status_code == 200


class TestScanAPI:
    def test_scan_invalid_path(self) -> None:
        with TestClient(app) as client:
            response = client.post("/api/scan?path=/nonexistent/path/xyz")
            assert response.status_code == 422

    def test_result_404_before_scan(self) -> None:
        scan_manager.reset()
        with TestClient(app) as client:
            response = client.get("/api/scan/result")
            assert response.status_code == 404

    def test_status_endpoint(self) -> None:
        scan_manager.reset()
        with TestClient(app) as client:
            response = client.get("/api/scan/status")
            data = response.json()
            assert "active" in data
            assert "has_result" in data

    def test_script_404_before_scan(self, tmp_path: Path) -> None:
        scan_manager.reset()
        with TestClient(app) as client:
            response = client.get(f"/api/scan/script?paths={tmp_path / 'foo'}")
            assert response.status_code == 404

    def test_script_400_no_paths(self, tmp_path: Path) -> None:
        # Inject a fake result
        scan_manager._result = ScanResult(root=str(tmp_path))
        scan_manager._scan_id = "test123"
        with TestClient(app) as client:
            response = client.get("/api/scan/script")
            assert response.status_code == 400
        scan_manager.reset()

    def test_script_download(self, tmp_path: Path) -> None:
        root = str(tmp_path)
        bigfile = str(tmp_path / "bigfile.bin")
        scan_manager._result = ScanResult(root=root)
        scan_manager._result.recommendations = [
            Recommendation(
                path=bigfile,
                size=100_000_000,
                category=Category.LARGE_FILE,
                reason="Large file",
            )
        ]
        scan_manager._scan_id = "test456"
        with TestClient(app) as client:
            response = client.get(f"/api/scan/script?paths={bigfile}")
            assert response.status_code == 200
            if _IS_WINDOWS:
                assert "Remove-Item" in response.text
            else:
                assert "#!/usr/bin/env bash" in response.text
            assert "bigfile.bin" in response.text
            assert "attachment" in response.headers.get("content-disposition", "")
        scan_manager.reset()

    def test_reset_endpoint(self, tmp_path: Path) -> None:
        scan_manager._result = ScanResult(root=str(tmp_path))
        scan_manager._scan_id = "test789"
        with TestClient(app) as client:
            response = client.post("/api/scan/reset")
            assert response.status_code == 200
            assert scan_manager.result is None

    def test_result_with_injected_scan(self, tmp_path: Path) -> None:
        """Test result endpoint by running the analyzer directly and injecting the result."""
        from storageanalyser.analyzer import DiskAnalyzer

        # Create some test files
        (tmp_path / "file1.txt").write_text("hello")
        (tmp_path / "file2.txt").write_text("world")

        analyzer = DiskAnalyzer(tmp_path, progress=False)
        result = analyzer.scan()

        scan_manager._result = result
        scan_manager._scan_id = "injected"

        with TestClient(app) as client:
            response = client.get("/api/scan/result")
            assert response.status_code == 200
            data = response.json()
            assert "total_scanned" in data
            assert "recommendations" in data
            assert data["total_scanned"] == 2
            assert data["scan_id"] == "injected"
        scan_manager.reset()


class TestScanManager:
    def test_generate_script_empty(self) -> None:
        scan_manager.reset()
        assert scan_manager.generate_script(["/foo"]) == ""

    def test_result_to_dict_none(self) -> None:
        scan_manager.reset()
        assert scan_manager.result_to_dict() is None

    def test_generate_script_contains_commands(self, tmp_path: Path) -> None:
        """Generated script must include a cleanup command for each selected path."""
        file_a = str(tmp_path / "a.bin")
        file_b = str(tmp_path / "b.bin")
        scan_manager._result = ScanResult(root=str(tmp_path))
        scan_manager._result.recommendations = [
            Recommendation(path=file_a, size=50_000_000,
                           category=Category.LARGE_FILE, reason="Large"),
            Recommendation(path=file_b, size=30_000_000,
                           category=Category.ARTIFACT, reason="Artifact"),
        ]
        scan_manager._scan_id = "gen_test"
        script = scan_manager.generate_script([file_a, file_b])
        assert "a.bin" in script
        assert "b.bin" in script
        if _IS_WINDOWS:
            assert "Remove-Item" in script
        else:
            assert "rm" in script
        scan_manager.reset()

    def test_script_download_round_trip(self, tmp_path: Path) -> None:
        """Paths from result_to_dict must match in generate_script (round-trip)."""
        file_path = str(tmp_path / "data.bin")
        scan_manager._result = ScanResult(root=str(tmp_path))
        scan_manager._result.recommendations = [
            Recommendation(path=file_path, size=200_000_000,
                           category=Category.LARGE_FILE, reason="Large file"),
        ]
        scan_manager._scan_id = "rt_test"

        # Get the path as the web UI would see it
        result_dict = scan_manager.result_to_dict()
        api_path = result_dict["recommendations"][0]["path"]

        # Use that exact path to request a script (simulates the JS flow)
        with TestClient(app) as client:
            response = client.get("/api/scan/script", params={"paths": api_path})
            assert response.status_code == 200
            assert "data.bin" in response.text
            if _IS_WINDOWS:
                assert "Remove-Item" in response.text
            else:
                assert "rm " in response.text
        scan_manager.reset()


def _free_port() -> int:
    """Find a free port by binding to port 0 and letting the OS assign one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _port_in_use(port: int) -> bool:
    """Return True if a process is listening on the given port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _start_server(cmd: list[str], port: int) -> subprocess.Popen:
    """Start a server subprocess and wait until it's listening."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(40):
        if proc.poll() is not None:
            out = proc.stdout.read().decode() if proc.stdout else ""
            raise AssertionError(f"Server exited early (rc={proc.returncode}): {out}")
        if _port_in_use(port):
            return proc
        time.sleep(0.25)
    proc.kill()
    proc.wait()
    raise AssertionError("Server did not start within 10 seconds")


def _shutdown_and_assert_exit(proc: subprocess.Popen, port: int) -> None:
    """POST /api/shutdown and assert the process exits and the port is freed."""
    url = f"http://127.0.0.1:{port}"
    try:
        resp = httpx.post(f"{url}/api/shutdown", timeout=5)
        assert resp.status_code == 200
        assert resp.json()["status"] == "shutting_down"
    except (httpx.RemoteProtocolError, httpx.ConnectError):
        pass  # Server exited before sending response — acceptable

    proc.wait(timeout=10)
    assert proc.poll() is not None, "Server process should have exited"

    time.sleep(0.5)
    assert not _port_in_use(port), f"Port {port} should be free after shutdown"


class TestServerShutdown:
    def test_exit_button_direct_invocation(self) -> None:
        """python -m storageanalyser.web.server: Exit button stops server and frees port."""
        port = _free_port()
        proc = _start_server(
            [sys.executable, "-m", "storageanalyser.web.server", "--port", str(port)],
            port,
        )
        try:
            _shutdown_and_assert_exit(proc, port)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

    def test_exit_button_cli_web_mode(self) -> None:
        """storageanalyser --web: Exit button stops server and frees port."""
        port = _free_port()
        proc = _start_server(
            [sys.executable, "-m", "storageanalyser.cli", "--web", "--port", str(port)],
            port,
        )
        try:
            _shutdown_and_assert_exit(proc, port)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

    @pytest.mark.skipif(_IS_WINDOWS, reason="SIGINT not reliably sendable on Windows")
    def test_ctrl_c_cli_web_mode(self) -> None:
        """storageanalyser --web: Ctrl-C cleanly stops server and frees port."""
        port = _free_port()
        proc = _start_server(
            [sys.executable, "-m", "storageanalyser.cli", "--web", "--port", str(port)],
            port,
        )
        try:
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=10)
            assert proc.poll() is not None, "Server process should have exited"
            time.sleep(0.5)
            assert not _port_in_use(port), f"Port {port} should be free after Ctrl-C"
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
