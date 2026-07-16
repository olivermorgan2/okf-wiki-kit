"""Tests for okfkit.envfile."""

from __future__ import annotations

import io
import os
import sys

import pytest

from okfkit import envfile


@pytest.fixture(autouse=True)
def _reset_provenance():
    envfile.applied.clear()
    envfile.found.clear()
    yield
    envfile.applied.clear()
    envfile.found.clear()


class _FakeTTYIn:
    def __init__(self, answer: str = ""):
        self._answer = answer

    def isatty(self) -> bool:
        return True

    def readline(self) -> str:
        return self._answer


class _FakeTTYErr(io.StringIO):
    def isatty(self) -> bool:
        return True


# ---------------------------------------------------------------- parse

def test_parse(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        "\n"
        "PLAIN = hello\n"
        "export EXPORTED=1\n"
        "SINGLE='sq value'\n"
        'DOUBLE="dq value"\n'
        "MISMATCH=\"half'\n"
        "EQUALS=a=b=c\n"
        "no equals sign here\n"
        "LITERAL=${OTHER}/sub\n"
    )
    got = envfile.parse(str(env))
    assert got == {
        "PLAIN": "hello",
        "EXPORTED": "1",
        "SINGLE": "sq value",
        "DOUBLE": "dq value",
        "MISMATCH": "\"half'",   # only matching quote pairs are stripped
        "EQUALS": "a=b=c",       # split on first '=' only
        "LITERAL": "${OTHER}/sub",  # no interpolation
    }


def test_parse_missing_file(tmp_path):
    assert envfile.parse(str(tmp_path / "nope.env")) == {}


# ---------------------------------------------------------------- candidates

def test_candidates_stops_after_git_dir(tmp_path):
    root = tmp_path / "proj"
    (root / ".git").mkdir(parents=True)
    deep = root / "a" / "b"
    deep.mkdir(parents=True)
    got = envfile.candidates(str(deep))
    assert got == [
        os.path.join(str(deep), ".env"),
        os.path.join(str(root / "a"), ".env"),
        os.path.join(str(root), ".env"),
    ]


def test_candidates_stops_after_okf_config(tmp_path):
    root = tmp_path / "proj"
    sub = root / "sub"
    sub.mkdir(parents=True)
    (root / "okf.config.yaml").write_text("adapter: markdown_folder\n")
    got = envfile.candidates(str(sub))
    assert got == [os.path.join(str(sub), ".env"), os.path.join(str(root), ".env")]


def test_candidates_respects_max_up(tmp_path):
    deep = tmp_path / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    got = envfile.candidates(str(deep), max_up=2)
    assert len(got) == 2
    assert got[0] == os.path.join(str(deep), ".env")  # nearest first
    assert got[1] == os.path.join(str(deep.parent), ".env")


# ---------------------------------------------------------------- load / provenance

def test_load_does_not_override_env_but_records_found(tmp_path, monkeypatch):
    monkeypatch.setenv("OKF_T_PRESET", "from-shell")
    env = tmp_path / ".env"
    env.write_text("OKF_T_PRESET=from-file\n")
    envfile.load([str(env)])
    assert os.environ["OKF_T_PRESET"] == "from-shell"
    assert envfile.found["OKF_T_PRESET"] == str(env)
    assert "OKF_T_PRESET" not in envfile.applied


def test_load_applies_new_keys_with_provenance(tmp_path, monkeypatch):
    monkeypatch.delenv("OKF_T_NEW", raising=False)
    env = tmp_path / ".env"
    env.write_text("OKF_T_NEW=v1\n")
    envfile.load([str(env), str(tmp_path / "missing.env")])
    assert os.environ["OKF_T_NEW"] == "v1"
    assert envfile.applied["OKF_T_NEW"] == str(env)
    assert envfile.found["OKF_T_NEW"] == str(env)
    monkeypatch.delenv("OKF_T_NEW", raising=False)


def test_nearest_env_wins(tmp_path, monkeypatch):
    monkeypatch.delenv("OKF_T_NEAR", raising=False)
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    (outer / ".git").mkdir()
    (outer / ".env").write_text("OKF_T_NEAR=outer\n")
    (inner / ".env").write_text("OKF_T_NEAR=inner\n")
    envfile.load(envfile.candidates(str(inner)))
    assert os.environ["OKF_T_NEAR"] == "inner"
    assert envfile.applied["OKF_T_NEAR"] == str(inner / ".env")
    assert envfile.found["OKF_T_NEAR"] == str(inner / ".env")
    monkeypatch.delenv("OKF_T_NEAR", raising=False)


# ---------------------------------------------------------------- load_default

def test_load_default_is_silent(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OKF_T_SILENT", raising=False)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".env").write_text("OKF_T_SILENT=yes\n")
    monkeypatch.chdir(tmp_path)
    envfile.load_default(config_path=str(tmp_path / "okf.config.yaml"))
    out, err = capsys.readouterr()
    assert out == "" and err == ""
    assert os.environ["OKF_T_SILENT"] == "yes"
    monkeypatch.delenv("OKF_T_SILENT", raising=False)


# ---------------------------------------------------------------- default_env_path

def test_default_env_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert envfile.default_env_path() == os.path.join(str(tmp_path), ".env")
    envfile.found["X"] = str(tmp_path / "elsewhere" / ".env")
    assert envfile.default_env_path() == str(tmp_path / "elsewhere" / ".env")


# ---------------------------------------------------------------- prompt_for_key

def test_prompt_returns_none_when_noninteractive(monkeypatch):
    monkeypatch.setenv("OKF_NONINTERACTIVE", "1")
    assert envfile.prompt_for_key("OKF_T_KEY") is None


def test_prompt_returns_none_without_tty(monkeypatch):
    monkeypatch.delenv("OKF_NONINTERACTIVE", raising=False)
    monkeypatch.setattr(sys, "stdin", _FakeTTYIn())
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert envfile.prompt_for_key("OKF_T_KEY") is None


def test_prompt_happy_path_saves_to_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("OKF_NONINTERACTIVE", raising=False)
    monkeypatch.delenv("OKF_T_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", _FakeTTYIn("y\n"))
    monkeypatch.setattr(sys, "stderr", _FakeTTYErr())
    monkeypatch.setattr(envfile.getpass, "getpass", lambda prompt="": "sekrit")
    assert envfile.prompt_for_key("OKF_T_KEY", hint="voyage") == "sekrit"
    assert os.environ["OKF_T_KEY"] == "sekrit"
    assert (tmp_path / ".env").read_text() == "OKF_T_KEY=sekrit\n"
    monkeypatch.delenv("OKF_T_KEY", raising=False)


def test_prompt_answer_no_leaves_file_untouched(tmp_path, monkeypatch):
    monkeypatch.delenv("OKF_NONINTERACTIVE", raising=False)
    monkeypatch.delenv("OKF_T_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", _FakeTTYIn("n\n"))
    monkeypatch.setattr(sys, "stderr", _FakeTTYErr())
    monkeypatch.setattr(envfile.getpass, "getpass", lambda prompt="": "sekrit")
    assert envfile.prompt_for_key("OKF_T_KEY") == "sekrit"
    assert os.environ["OKF_T_KEY"] == "sekrit"
    assert not (tmp_path / ".env").exists()
    monkeypatch.delenv("OKF_T_KEY", raising=False)
