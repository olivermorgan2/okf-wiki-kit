"""Offline tests for `okf doctor` (okfkit/doctor.py).

A real vault is built with `engine.build` into tmp_path (as in
test_serve_mcp.py); the index "freshness" is a hand-written chunks.json header.
`subprocess.run` is monkeypatched so no `claude` CLI is ever invoked, and
envfile provenance (`applied`/`found`) is swapped for fresh dicts so the
developer's own .env files cannot leak into assertions. No network.
"""

import json
import os
import types
from datetime import datetime, timedelta

import pytest

from okfkit import doctor, engine, envfile
from okfkit.model import Node

SENTINEL = "sk-sentinel-value-must-never-print"
KEYS = ("VOYAGE_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY")


def _nodes():
    return [
        Node(id="a", type="Topic", title="Alpha", body="Alpha links [[b]] in prose."),
        Node(id="b", type="Topic", title="Beta", body="Beta body."),
    ]


def _write_index_header(tmp_path):
    """A fresh-looking index header (created in the future, so never stale)."""
    from okfkit.serve.rag import Index          # no optional deps at import time
    _npz, chunks_path = Index.paths(str(tmp_path))
    os.makedirs(os.path.dirname(chunks_path), exist_ok=True)
    created = (datetime.now() + timedelta(minutes=5)).isoformat()
    with open(chunks_path, "w", encoding="utf-8") as fh:
        json.dump({"header": {"provider": "local", "model": "potion",
                              "created": created}, "chunks": []}, fh)


def _project(tmp_path, embed_provider="local", with_vault=True, with_index=True):
    """Write a config (+ source dir) under tmp_path; optionally vault + index."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.md").write_text("# A\n", encoding="utf-8")
    cfg_path = tmp_path / "okf.config.yaml"
    cfg_path.write_text(
        "adapter: markdown_folder\n"
        "adapter_options: {path: ./src}\n"
        "output: ./vault\n"
        "serve:\n"
        "  rag:\n"
        "    embedding:\n"
        f"      provider: {embed_provider}\n",
        encoding="utf-8")
    if with_vault:
        assert engine.build(_nodes(), str(tmp_path / "vault")).ok
    if with_index:
        _write_index_header(tmp_path)
    return str(cfg_path)


def _raise_file_not_found(*args, **kwargs):
    raise FileNotFoundError("claude")


@pytest.fixture
def isolated(monkeypatch):
    """No real keys, no real .env provenance, no real `claude` CLI."""
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OKF_NONINTERACTIVE", "1")
    monkeypatch.setattr(envfile, "applied", {})
    monkeypatch.setattr(envfile, "found", {})
    monkeypatch.setattr(envfile, "load_default", lambda *a, **k: None)
    monkeypatch.setattr(doctor.subprocess, "run", _raise_file_not_found)
    return monkeypatch


# ---------------------------------------------------------------------------
# Healthy project / missing vault
# ---------------------------------------------------------------------------
def test_healthy_local_project_exits_zero(tmp_path, isolated, capsys):
    cfg = _project(tmp_path)
    assert doctor.run(cfg) == 0
    out = capsys.readouterr().out
    assert "✗" not in out                       # nothing failed
    assert "✓ config:" in out
    assert "✓ vault:" in out
    assert "✓ semantic index:" in out
    assert "no key needed" in out               # local embeddings


def test_missing_vault_fails(tmp_path, isolated, capsys):
    cfg = _project(tmp_path, with_vault=False, with_index=False)
    assert doctor.run(cfg) == 1
    out = capsys.readouterr().out
    assert "✗ vault:" in out and "okf build" in out


# ---------------------------------------------------------------------------
# MCP checks degrade gracefully
# ---------------------------------------------------------------------------
def test_claude_cli_absent_warns_but_completes(tmp_path, isolated, capsys):
    cfg = _project(tmp_path)
    assert doctor.run(cfg) == 0                 # warn, never a crash or fail
    out = capsys.readouterr().out
    assert "claude CLI not found" in out
    assert "✓ vault:" in out                    # later checks still ran


def test_registered_server_with_dead_command_fails(tmp_path, isolated, capsys):
    cfg = _project(tmp_path)
    outputs = {
        "mcp list": "okf-wiki: /nonexistent/bin/python -m okfkit.cli serve - ✓ Connected\n",
        "mcp get": "Name: okf-wiki\nCommand: /nonexistent/bin/python -m okfkit.cli serve\n",
    }
    isolated.setattr(
        doctor.subprocess, "run",
        lambda cmd, **kw: types.SimpleNamespace(
            stdout=outputs.get(" ".join(cmd[1:3]), ""), stderr="", returncode=0))
    assert doctor.run(cfg) == 1
    out = capsys.readouterr().out
    assert "does not resolve" in out and "okf serve --register" in out


# ---------------------------------------------------------------------------
# Key provenance matrix (the headline behavior): shell-only != .env-loaded
# ---------------------------------------------------------------------------
def test_shell_only_key_warns_about_mcp_spawned_servers(tmp_path, isolated, capsys):
    cfg = _project(tmp_path, embed_provider="voyage")
    isolated.setenv("VOYAGE_API_KEY", SENTINEL)     # exported, but in no .env file
    assert doctor.run(cfg) == 0                     # warn, not fail
    out = capsys.readouterr().out
    assert "set in this shell only" in out
    assert "will NOT see it" in out
    assert SENTINEL not in out                      # never print a key's value


def test_env_file_loaded_key_is_ok(tmp_path, isolated, capsys):
    cfg = _project(tmp_path, embed_provider="voyage")
    isolated.setenv("VOYAGE_API_KEY", SENTINEL)
    envfile.found["VOYAGE_API_KEY"] = str(tmp_path / ".env")
    assert doctor.run(cfg) == 0
    out = capsys.readouterr().out
    assert "loaded from" in out
    assert "works for MCP-spawned servers too" in out
    assert SENTINEL not in out


def test_missing_needed_key_fails(tmp_path, isolated, capsys):
    cfg = _project(tmp_path, embed_provider="voyage")
    assert doctor.run(cfg) == 1
    out = capsys.readouterr().out
    assert "✗ embedding key (voyage): Set VOYAGE_API_KEY" in out
    assert ".env" in out


def test_no_config_skips_dependent_checks(tmp_path, isolated, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)                     # nowhere near a real config
    assert doctor.run(str(tmp_path / "okf.config.yaml")) == 0
    out = capsys.readouterr().out
    assert "⚠ config:" in out and "okf init" in out
    assert "skipped: no config" in out
