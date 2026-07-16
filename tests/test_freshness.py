"""Offline tests for `okfkit.freshness` — mtime-based staleness checks shared
by the CLI, doctor, and the MCP server. Pure stdlib: no numpy, no vault build;
index headers are hand-written JSON matching the shape of `rag.Index.save`."""

import json
import os
from datetime import datetime, timezone

from okfkit import freshness

CREATED = "2026-07-01T12:00:00+00:00"
CREATED_TS = datetime.fromisoformat(CREATED).timestamp()


def _write_header(base_dir, created=CREATED):
    """Hand-write a chunks.json with the exact header shape `rag.Index.save`
    produces: {header: {provider, model, dim, vault_path, created}, chunks: []}."""
    d = os.path.join(base_dir, ".okf")
    os.makedirs(d, exist_ok=True)
    header = {"provider": "local", "model": "minishlab/potion-base-8M",
              "dim": 256, "vault_path": str(base_dir), "created": created}
    with open(os.path.join(d, "chunks.json"), "w", encoding="utf-8") as fh:
        json.dump({"header": header, "chunks": []}, fh)
    return header


# ---------------------------------------------------------------------------
# is_stale
# ---------------------------------------------------------------------------
def test_is_stale_newer_file_is_true():
    assert freshness.is_stale(CREATED, CREATED_TS + 60) is True


def test_is_stale_older_file_is_false():
    assert freshness.is_stale(CREATED, CREATED_TS - 60) is False


def test_is_stale_missing_or_garbage_created_is_none():
    assert freshness.is_stale(None, 1e12) is None
    assert freshness.is_stale("", 1e12) is None
    assert freshness.is_stale("not-a-timestamp", 1e12) is None


def test_is_stale_naive_iso_parses():
    # `datetime.fromisoformat` accepts naive timestamps too (local time).
    naive = "2026-07-01T12:00:00"
    ts = datetime.fromisoformat(naive).timestamp()
    assert freshness.is_stale(naive, ts + 1) is True
    assert freshness.is_stale(naive, ts - 1) is False


# ---------------------------------------------------------------------------
# newest_mtime / newest_mtime_under
# ---------------------------------------------------------------------------
def test_newest_mtime_skips_missing_and_empty(tmp_path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("a")
    b.write_text("b")
    os.utime(a, (1000, 1000))
    os.utime(b, (2000, 2000))
    missing = tmp_path / "gone.md"
    assert freshness.newest_mtime([str(a), str(missing), str(b)]) == 2000.0
    assert freshness.newest_mtime([str(missing)]) == 0.0
    assert freshness.newest_mtime([]) == 0.0


def test_newest_mtime_under_filters_by_extension(tmp_path):
    (tmp_path / "sub").mkdir()
    note = tmp_path / "sub" / "note.md"
    other = tmp_path / "data.json"
    note.write_text("note")
    other.write_text("{}")
    os.utime(note, (1000, 1000))
    os.utime(other, (9000, 9000))
    assert freshness.newest_mtime_under(str(tmp_path), (".md",)) == 1000.0
    assert freshness.newest_mtime_under(str(tmp_path)) == 9000.0
    assert freshness.newest_mtime_under(str(tmp_path / "empty-nowhere"), (".md",)) == 0.0


# ---------------------------------------------------------------------------
# index_header
# ---------------------------------------------------------------------------
def test_index_header_absent_is_none(tmp_path):
    assert freshness.index_header(str(tmp_path)) is None


def test_index_header_unreadable_is_none(tmp_path):
    d = tmp_path / ".okf"
    d.mkdir()
    (d / "chunks.json").write_text("not json{")
    assert freshness.index_header(str(tmp_path)) is None


def test_index_header_reads_real_shape(tmp_path):
    written = _write_header(str(tmp_path))
    header = freshness.index_header(str(tmp_path))
    assert header == written
    assert header["provider"] == "local"
    assert header["created"] == CREATED


# ---------------------------------------------------------------------------
# index_staleness end-to-end
# ---------------------------------------------------------------------------
def test_index_staleness_no_index_is_none(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    assert freshness.index_staleness(str(tmp_path), str(vault)) is None


def test_index_staleness_both_directions(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("# Note\n")
    _write_header(str(tmp_path))

    stale_ts = CREATED_TS + 3600          # note edited after the index build
    os.utime(note, (stale_ts, stale_ts))
    assert freshness.index_staleness(str(tmp_path), str(vault)) is True

    fresh_ts = CREATED_TS - 3600          # note untouched since the build
    os.utime(note, (fresh_ts, fresh_ts))
    assert freshness.index_staleness(str(tmp_path), str(vault)) is False


def test_index_staleness_ignores_non_md_files(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    junk = vault / "cache.tmp"
    note.write_text("# Note\n")
    junk.write_text("x")
    _write_header(str(tmp_path))
    os.utime(note, (CREATED_TS - 3600, CREATED_TS - 3600))
    os.utime(junk, (CREATED_TS + 3600, CREATED_TS + 3600))   # newer, but not .md
    assert freshness.index_staleness(str(tmp_path), str(vault)) is False


def test_index_staleness_missing_created_is_none(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_header(str(tmp_path), created=None)
    assert freshness.index_staleness(str(tmp_path), str(vault)) is None
