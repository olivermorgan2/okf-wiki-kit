"""CLI staleness warnings and .env loading.

Tiny real projects (markdown_folder adapter) in tmp_path; the search-path index
is faked so no embeddings backend is ever needed.
"""

import os
import time

from okfkit import cli, freshness


def _project(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n\nHello.\n", encoding="utf-8")
    cfgp = tmp_path / "okf.config.yaml"
    cfgp.write_text("adapter: markdown_folder\n"
                    "adapter_options:\n  path: ./notes\n"
                    "output: ./vault\n", encoding="utf-8")
    return str(cfgp), notes


BUILD_WARNING = "older than the newest source file"
INDEX_WARNING = "vault is newer than the index"


# ---------------------------------------------------------------------------
# build: enrichment.json vs newest source mtime
# ---------------------------------------------------------------------------

def test_build_warns_when_enrichment_older_than_source(tmp_path, capsys):
    cfgp, notes = _project(tmp_path)
    ep = tmp_path / "enrichment.json"
    ep.write_text("{}", encoding="utf-8")
    now = time.time()
    os.utime(ep, (now - 1000, now - 1000))
    os.utime(notes / "a.md", (now, now))
    assert cli.main(["build", "-c", cfgp]) == 0
    assert BUILD_WARNING in capsys.readouterr().out


def test_build_no_warning_when_enrichment_fresh(tmp_path, capsys):
    cfgp, notes = _project(tmp_path)
    ep = tmp_path / "enrichment.json"
    ep.write_text("{}", encoding="utf-8")
    now = time.time()
    os.utime(notes / "a.md", (now - 1000, now - 1000))
    os.utime(ep, (now, now))
    assert cli.main(["build", "-c", cfgp]) == 0
    out = capsys.readouterr().out
    assert "(using" in out                 # enrichment was picked up
    assert BUILD_WARNING not in out


def test_build_no_warning_without_enrichment(tmp_path, capsys):
    cfgp, _notes = _project(tmp_path)
    assert cli.main(["build", "-c", cfgp]) == 0
    assert BUILD_WARNING not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# search: index staleness goes to STDERR, results stay pipeable
# ---------------------------------------------------------------------------

class _FakeHit:
    score, heading, type, node_id, title = 0.9, "", "Note", "a", "A"


class _FakeIndex:
    def search(self, query, k=8, types=None):
        return [_FakeHit()]


def test_search_stale_index_warns_on_stderr_only(tmp_path, monkeypatch, capsys):
    cfgp, _notes = _project(tmp_path)
    monkeypatch.setattr(cli, "_load_index", lambda cfg, backend=None: _FakeIndex())
    seen = {}
    monkeypatch.setattr(freshness, "index_staleness",
                        lambda base_dir, vault: seen.update(base=base_dir, vault=vault) or True)
    assert cli.main(["search", "hello", "-c", cfgp]) == 0
    cap = capsys.readouterr()
    assert INDEX_WARNING in cap.err
    assert "Warning" not in cap.out        # stdout carries only the hits
    assert "a — A" in cap.out
    # the check ran against the config's base dir and resolved vault
    assert seen["base"] == str(tmp_path)
    assert seen["vault"] == str(tmp_path / "vault")


def test_search_fresh_index_stays_quiet(tmp_path, monkeypatch, capsys):
    cfgp, _notes = _project(tmp_path)
    monkeypatch.setattr(cli, "_load_index", lambda cfg, backend=None: _FakeIndex())
    monkeypatch.setattr(freshness, "index_staleness", lambda base_dir, vault: False)
    assert cli.main(["search", "hello", "-c", cfgp]) == 0
    assert capsys.readouterr().err == ""


def test_ask_stale_index_warns_on_stderr(tmp_path, monkeypatch, capsys):
    cfgp, _notes = _project(tmp_path)
    monkeypatch.setattr(cli, "_load_index", lambda cfg, backend=None: _FakeIndex())
    monkeypatch.setattr(freshness, "index_staleness", lambda base_dir, vault: True)

    from okfkit import enrich
    from okfkit import serve as servemod
    monkeypatch.setattr(enrich, "make_backend", lambda **kw: object())
    monkeypatch.setattr(servemod, "ask", lambda q, idx, backend, k=8, types=None: ("answer", [_FakeHit()]))
    assert cli.main(["ask", "hello", "-c", cfgp]) == 0
    assert INDEX_WARNING in capsys.readouterr().err


# ---------------------------------------------------------------------------
# .env loading around main()
# ---------------------------------------------------------------------------

def test_env_next_to_config_is_loaded(tmp_path, monkeypatch):
    cfgp, _notes = _project(tmp_path)
    (tmp_path / ".env").write_text("OKF_CLI_ENV_TEST=from-dotenv\n", encoding="utf-8")
    monkeypatch.setattr(os, "environ", dict(os.environ))   # isolate mutations
    os.environ.pop("OKF_CLI_ENV_TEST", None)
    assert cli.main(["build", "-c", cfgp]) == 0
    assert os.environ.get("OKF_CLI_ENV_TEST") == "from-dotenv"


def test_env_does_not_override_real_environment(tmp_path, monkeypatch):
    cfgp, _notes = _project(tmp_path)
    (tmp_path / ".env").write_text("OKF_CLI_ENV_TEST=from-dotenv\n", encoding="utf-8")
    monkeypatch.setattr(os, "environ", dict(os.environ))
    os.environ["OKF_CLI_ENV_TEST"] = "preset"
    assert cli.main(["build", "-c", cfgp]) == 0
    assert os.environ["OKF_CLI_ENV_TEST"] == "preset"
