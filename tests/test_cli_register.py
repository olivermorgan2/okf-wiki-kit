"""`okf serve --register` — runs `claude mcp add` pinned to this interpreter.

All subprocess calls are monkeypatched; nothing here touches a real `claude`.
"""

import os
import subprocess
import sys

from okfkit import cli


def _write_config(tmp_path, extra=""):
    p = tmp_path / "okf.config.yaml"
    p.write_text("adapter: markdown_folder\n"
                 "adapter_options:\n  path: ./notes\n"
                 "output: ./vault\n" + extra, encoding="utf-8")
    return str(p)


def _fake_run(calls, returncode=0, stdout="", stderr=""):
    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)
    return run


# ---------------------------------------------------------------------------
# argv construction
# ---------------------------------------------------------------------------

def test_register_exact_argv_with_config(tmp_path, monkeypatch, capsys):
    cfgp = _write_config(tmp_path)
    calls = []
    monkeypatch.setattr(subprocess, "run", _fake_run(calls))
    assert cli.main(["serve", "--register", "-c", cfgp]) == 0
    assert calls == [[
        "claude", "mcp", "add", "okf-wiki", "--",
        sys.executable, "-m", "okfkit.cli", "serve",
        "-c", os.path.abspath(cfgp),
    ]]


def test_register_uses_config_server_name(tmp_path, monkeypatch, capsys):
    cfgp = _write_config(tmp_path, "serve:\n  mcp:\n    name: my-wiki\n")
    calls = []
    monkeypatch.setattr(subprocess, "run", _fake_run(calls))
    assert cli.main(["serve", "--register", "-c", cfgp]) == 0
    assert calls[0][3] == "my-wiki"


def test_register_vault_variant(tmp_path, monkeypatch, capsys):
    vault = tmp_path / "vault"
    vault.mkdir()
    calls = []
    monkeypatch.setattr(subprocess, "run", _fake_run(calls))
    assert cli.main(["serve", "--register", "--vault", str(vault)]) == 0
    assert calls == [[
        "claude", "mcp", "add", "okf-wiki", "--",
        sys.executable, "-m", "okfkit.cli", "serve",
        "--vault", os.path.abspath(str(vault)),
    ]]


def test_register_no_rag_variant(tmp_path, monkeypatch, capsys):
    cfgp = _write_config(tmp_path)
    calls = []
    monkeypatch.setattr(subprocess, "run", _fake_run(calls))
    assert cli.main(["serve", "--register", "--no-rag", "-c", cfgp]) == 0
    assert calls[0][-1] == "--no-rag"
    assert calls[0][-3:-1] == ["-c", os.path.abspath(cfgp)]


# ---------------------------------------------------------------------------
# outcomes
# ---------------------------------------------------------------------------

def test_register_claude_not_on_path(tmp_path, monkeypatch, capsys):
    cfgp = _write_config(tmp_path)

    def run(cmd, **kwargs):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(subprocess, "run", run)
    assert cli.main(["serve", "--register", "-c", cfgp]) == 1
    cap = capsys.readouterr()
    assert "claude CLI not found on PATH" in cap.err
    assert "Running:" in cap.out   # the manual command was still printed


def test_register_already_exists(tmp_path, monkeypatch, capsys):
    cfgp = _write_config(tmp_path)
    monkeypatch.setattr(subprocess, "run", _fake_run(
        [], returncode=1, stderr="MCP server okf-wiki Already Exists in local config"))
    assert cli.main(["serve", "--register", "-c", cfgp]) == 1
    cap = capsys.readouterr()
    assert "already registered" in cap.err
    assert "claude mcp remove okf-wiki" in cap.err


def test_register_other_failure_passes_stderr_through(tmp_path, monkeypatch, capsys):
    cfgp = _write_config(tmp_path)
    monkeypatch.setattr(subprocess, "run", _fake_run(
        [], returncode=2, stderr="some other claude failure\n"))
    assert cli.main(["serve", "--register", "-c", cfgp]) == 1
    assert "some other claude failure" in capsys.readouterr().err


def test_register_success_prints_running_and_registered(tmp_path, monkeypatch, capsys):
    cfgp = _write_config(tmp_path)
    monkeypatch.setattr(subprocess, "run", _fake_run(
        [], returncode=0, stdout="Added stdio MCP server okf-wiki\n"))
    assert cli.main(["serve", "--register", "-c", cfgp]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Running: claude mcp add okf-wiki -- ")
    assert "Added stdio MCP server okf-wiki" in out
    assert "Registered 'okf-wiki'." in out
