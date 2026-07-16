"""`okf serve` transport flags: --transport/--host/--port parsed by argparse and
threaded through to `serve.mcp.run`; stdio stays the default; `--register
--transport http` still registers the stdio form (with a note).

The `serve.mcp.run` boundary and all subprocess calls are monkeypatched —
no MCP server (stdio or HTTP) and no real `claude` ever start.
"""

import os
import subprocess
import sys

import pytest

from okfkit import cli
from okfkit.serve import mcp as mcpmod


def _vault(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    return str(v)


def _capture_run(monkeypatch):
    """Replace serve.mcp.run with a recorder; also keep the OKF_NONINTERACTIVE
    write `_serve` makes from leaking into other tests."""
    monkeypatch.delenv("OKF_NONINTERACTIVE", raising=False)
    calls = []

    def fake_run(target, use_rag=True, transport="stdio",
                 host="127.0.0.1", port=8000):
        calls.append({"target": target, "use_rag": use_rag,
                      "transport": transport, "host": host, "port": port})
        return 0

    monkeypatch.setattr(mcpmod, "run", fake_run)
    return calls


# ---------------------------------------------------------------------------
# flag parsing + threading to serve.mcp.run
# ---------------------------------------------------------------------------

def test_serve_defaults_to_stdio(tmp_path, monkeypatch, capsys):
    vault = _vault(tmp_path)
    calls = _capture_run(monkeypatch)
    assert cli.main(["serve", "--vault", vault]) == 0
    assert calls == [{"target": os.path.abspath(vault), "use_rag": True,
                      "transport": "stdio", "host": "127.0.0.1", "port": 8000}]
    cap = capsys.readouterr()
    assert "okf MCP server starting (stdio)" in cap.err
    assert cap.out == ""                           # stdout stays clean for stdio


def test_serve_http_flags_thread_through(tmp_path, monkeypatch, capsys):
    vault = _vault(tmp_path)
    calls = _capture_run(monkeypatch)
    assert cli.main(["serve", "--vault", vault, "--transport", "http",
                     "--host", "0.0.0.0", "--port", "9321"]) == 0
    assert calls == [{"target": os.path.abspath(vault), "use_rag": True,
                      "transport": "http", "host": "0.0.0.0", "port": 9321}]
    cap = capsys.readouterr()
    assert "http://0.0.0.0:9321/mcp" in cap.err
    assert "(stdio)" not in cap.err


def test_serve_http_default_host_port(tmp_path, monkeypatch, capsys):
    vault = _vault(tmp_path)
    calls = _capture_run(monkeypatch)
    assert cli.main(["serve", "--vault", vault, "--transport", "http",
                     "--no-rag"]) == 0
    assert calls[0]["transport"] == "http"
    assert calls[0]["host"] == "127.0.0.1" and calls[0]["port"] == 8000
    assert calls[0]["use_rag"] is False            # other flags still respected
    assert "http://127.0.0.1:8000/mcp" in capsys.readouterr().err


def test_serve_rejects_unknown_transport(tmp_path, monkeypatch, capsys):
    vault = _vault(tmp_path)
    calls = _capture_run(monkeypatch)
    with pytest.raises(SystemExit) as ei:
        cli.main(["serve", "--vault", vault, "--transport", "tcp"])
    assert ei.value.code == 2                      # argparse usage error
    assert calls == []
    assert "invalid choice" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# --register x --transport: registration is always the stdio form
# ---------------------------------------------------------------------------

def _fake_subprocess_run(calls):
    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    return run


def test_register_with_http_transport_registers_stdio_and_notes(
        tmp_path, monkeypatch, capsys):
    vault = _vault(tmp_path)
    calls = []
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run(calls))
    assert cli.main(["serve", "--register", "--transport", "http",
                     "--host", "0.0.0.0", "--port", "9321",
                     "--vault", vault]) == 0
    # exactly the stdio argv — no transport/host/port leaks into the command
    assert calls == [[
        "claude", "mcp", "add", "okf-wiki", "--",
        sys.executable, "-m", "okfkit.cli", "serve",
        "--vault", os.path.abspath(vault),
    ]]
    out = capsys.readouterr().out
    assert "registers the stdio form" in out
    assert "ignoring --transport http" in out
    assert "Registered 'okf-wiki'." in out


def test_register_stdio_prints_no_transport_note(tmp_path, monkeypatch, capsys):
    vault = _vault(tmp_path)
    calls = []
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run(calls))
    assert cli.main(["serve", "--register", "--vault", vault]) == 0
    assert "ignoring --transport" not in capsys.readouterr().out
