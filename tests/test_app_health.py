import socket

from src import app, health


def test_port_fallback_skips_a_taken_port():
    taken = socket.socket()
    taken.bind(("127.0.0.1", 0))
    taken.listen()
    port = taken.getsockname()[1]
    try:
        server = app.bind_server(port)
        try:
            used = server.server_address[1]
            assert used != port and port < used <= port + app.PORT_TRIES - 1
        finally:
            server.server_close()
    finally:
        taken.close()


def test_run_checks_shape():
    checks = health.run_checks()
    assert checks
    for c in checks:
        assert set(c) >= {"name", "ok", "message", "fix"}
        assert isinstance(c["ok"], bool) and isinstance(c["name"], str)
        assert c["ok"] or c["fix"]


def test_missing_detector_python_fails_with_fix(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text("ocr: {}\n")
    (tmp_path / "config" / "detector.yaml").write_text(
        "engine: yolo\nbundle: models/x\npython_env_var: UI_DETECTOR_PYTHON\n"
        f"python_path: {tmp_path / 'nope' / 'python.exe'}\n")
    monkeypatch.setenv("UI_DETECTOR_PYTHON", str(tmp_path / "also_missing.exe"))
    checks = {c["name"]: c for c in health.run_checks(config_dir=tmp_path / "config")}
    py = checks["Detector Python"]
    assert py["ok"] is False and "UI_DETECTOR_PYTHON" in py["fix"]
    assert "also_missing" in py["message"]  # env var wins over python_path
    assert checks["Detector weights"]["ok"] is False
