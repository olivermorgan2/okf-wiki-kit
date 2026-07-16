"""Mtime-based staleness checks shared by the CLI, doctor, and the MCP server."""

from __future__ import annotations

import json
import os
from datetime import datetime


def newest_mtime(paths) -> float:
    """Newest mtime over *paths* (unreadable/missing paths skipped); 0.0 if none."""
    newest = 0.0
    for p in paths:
        try:
            newest = max(newest, os.path.getmtime(p))
        except OSError:
            continue
    return newest


def newest_mtime_under(root, exts: tuple[str, ...] | None = None) -> float:
    """Newest mtime of files under *root* (recursive), optionally filtered by
    extension tuple (e.g. ``(".md",)``); 0.0 if none."""
    paths = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if exts and not name.lower().endswith(exts):
                continue
            paths.append(os.path.join(dirpath, name))
    return newest_mtime(paths)


def is_stale(created_iso: str | None, newest: float):
    """True if *newest* (an mtime) is after the ISO *created_iso* timestamp;
    None if the timestamp is missing or unparseable."""
    if not created_iso:
        return None
    try:
        created_ts = datetime.fromisoformat(created_iso).timestamp()
    except ValueError:
        return None
    return newest > created_ts


def index_header(base_dir) -> dict | None:
    """The chunks.json header ({provider, model, dim, vault_path, created})
    written by `rag.Index.save`; None if absent or unreadable. Reads plain JSON
    — no numpy, no index load."""
    from okfkit.serve.rag import Index   # no optional deps at import time
    _npz, chunks_path = Index.paths(base_dir)
    try:
        with open(chunks_path, encoding="utf-8") as fh:
            return json.load(fh).get("header") or {}
    except (OSError, ValueError):
        return None


def index_staleness(base_dir, vault_path):
    """True/False if the index under *base_dir* is older/newer than the newest
    .md file in *vault_path*; None when there is no (readable) index."""
    header = index_header(base_dir)
    if header is None:
        return None
    return is_stale(header.get("created"), newest_mtime_under(vault_path, (".md",)))
