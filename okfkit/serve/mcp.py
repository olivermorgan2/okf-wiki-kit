"""Read-only MCP server over a built OKF vault (Phase 8).

Architecture: all logic lives in `VaultService` (vault graph via `serve.vault`
plus the optional Phase 7 `rag.Index`), which imports nothing from the `mcp`
SDK — so it is unit-testable with no optional deps installed. The five `okf_*`
tools registered by `create_server` are thin wrappers over it.

The `mcp` package is OPTIONAL: it is lazy-imported inside `create_server`, with
a `SystemExit` install hint on `ImportError` (mirroring `enrich.Backend`).
Graph tools (get_note / list_notes / neighbors / vault_info) need zero API
keys; `search` needs a previously built index (`okf index`) and degrades with
an actionable error when there is none.

Register with an MCP client, e.g.:
    claude mcp add okf-wiki -- okf serve -c /abs/path/okf.config.yaml
"""

from __future__ import annotations

import json
import os
from collections import Counter
from difflib import get_close_matches
from typing import Any

from okfkit.serve import vault as vaultmod

DEFAULT_SERVER_NAME = "okf-wiki"
DEFAULT_MAX_NOTE_CHARS = 20000

_INSTRUCTIONS = (
    "Read-only access to an OKF/Obsidian knowledge wiki. Start with "
    "okf_vault_info to see note types, tags and whether semantic search is "
    "available. Find notes with okf_search (semantic) or okf_list_notes "
    "(browse/paginate by type or tag), read them with okf_get_note, and walk "
    "the link graph with okf_neighbors. Note ids are wikilink targets "
    "(file basenames)."
)


class SearchUnavailable(RuntimeError):
    """Semantic search cannot run: RAG disabled, or no index has been built."""


class VaultService:
    """All server logic, MCP-free. The vault is loaded once at construction;
    the semantic index is loaded lazily on the first `search` call."""

    def __init__(self, vault_path, base_dir=None, use_rag=True,
                 max_note_chars=DEFAULT_MAX_NOTE_CHARS, exclude_types=()):
        self.vault_path = os.path.abspath(os.path.expanduser(vault_path))
        # where `okf index` keeps the sidecar index ({base_dir}/.okf/)
        self.base_dir = base_dir or os.path.dirname(self.vault_path)
        self.use_rag = use_rag
        self.max_note_chars = int(max_note_chars)
        self.notes = vaultmod.load_vault(self.vault_path, exclude_types)
        self.backlink_map = vaultmod.backlinks(self.notes)
        self._index = None          # rag.Index, loaded on first search

    # -- tools ---------------------------------------------------------------
    def search(self, query: str, k: int = 8, types=None) -> list[dict]:
        """Ranked semantic hits ``{id, type, title, description, snippet, score}``.

        Raises `SearchUnavailable` (actionable message) when RAG is disabled
        or no index exists — the graph tools keep working regardless.
        """
        hits = self._get_index().search(query, k=k, types=types)
        out = []
        for h in hits:
            note = self.notes.get(h.node_id)
            out.append({
                "id": h.node_id,
                "type": h.type,
                "title": h.title,
                "description": note.description if note else "",
                "snippet": _snippet(h.text),
                "score": round(float(h.score), 4),
            })
        return out

    def get_note(self, id: str, offset: int = 0) -> dict:
        """Full note: frontmatter, body (windowed at `max_note_chars`),
        outgoing links and backlinks. Unknown id -> error dict with suggestions."""
        note = self.notes.get(id)
        if note is None:
            return self._missing(id)
        offset = max(0, int(offset))
        end = offset + self.max_note_chars
        truncated = end < len(note.body)
        result = {
            "id": note.id,
            "type": note.type,
            "title": note.title,
            "description": note.description,
            "tags": note.tags,
            "frontmatter": _jsonable(note.frontmatter),
            "body": note.body[offset:end],
            "body_length": len(note.body),
            "offset": offset,
            "truncated": truncated,
            "next_offset": end if truncated else None,
            "outgoing": self._refs(vaultmod.outgoing(note)),
            "backlinks": self._refs(self.backlink_map.get(note.id, [])),
        }
        if truncated:
            result["hint"] = (f"Body is {len(note.body)} chars; call again with "
                              f"offset={end} for the next window.")
        return result

    def list_notes(self, type: str | None = None, tag: str | None = None,
                   limit: int = 50, cursor: str | None = None) -> dict:
        """Page through notes (sorted by id): ``{rows, total, next_cursor}``.
        `cursor` is the opaque `next_cursor` from the previous call."""
        try:
            start = int(cursor) if cursor else 0
        except (TypeError, ValueError):
            return {"error": f"Invalid cursor {cursor!r}: pass the `next_cursor` "
                             "value returned by the previous okf_list_notes call."}
        rows = [self.notes[nid] for nid in sorted(self.notes)]
        if type:
            want = type.strip().lower()
            rows = [n for n in rows if n.type.lower() == want]
        if tag:
            want = tag.strip().lower()
            rows = [n for n in rows if any(t.lower() == want for t in n.tags)]
        limit = max(1, int(limit))
        page = rows[start:start + limit]
        return {
            "rows": [{"id": n.id, "type": n.type, "title": n.title,
                      "description": n.description} for n in page],
            "total": len(rows),
            "next_cursor": str(start + limit) if start + limit < len(rows) else None,
        }

    def neighbors(self, id: str, direction: str = "both") -> dict:
        """Graph neighbors of a note: outgoing wikilinks and/or backlinks,
        each ``{id, type, title}``. `direction`: "outgoing" | "backlinks" | "both"."""
        note = self.notes.get(id)
        if note is None:
            return self._missing(id)
        d = (direction or "both").strip().lower()
        if d not in ("both", "outgoing", "out", "backlinks", "in"):
            return {"error": f"Invalid direction {direction!r}: use 'outgoing', "
                             "'backlinks' or 'both'."}
        result = {"id": note.id, "type": note.type, "title": note.title}
        if d in ("both", "outgoing", "out"):
            result["outgoing"] = self._refs(vaultmod.outgoing(note))
        if d in ("both", "backlinks", "in"):
            result["backlinks"] = self._refs(self.backlink_map.get(note.id, []))
        return result

    def vault_info(self) -> dict:
        """Vault orientation: note counts by type, tag counts, total, and
        semantic-index presence/freshness."""
        type_counts = Counter(n.type or "(untyped)" for n in self.notes.values())
        tag_counts = Counter(t for n in self.notes.values() for t in n.tags)
        return {
            "vault_path": self.vault_path,
            "total": len(self.notes),
            "types": dict(sorted(type_counts.items())),
            "tags": dict(sorted(tag_counts.items())),
            "search_enabled": self.use_rag,
            "index": self._index_info(),
        }

    # -- internals -------------------------------------------------------
    def _get_index(self):
        if not self.use_rag:
            raise SearchUnavailable(
                "Semantic search is disabled (server started with --no-rag). "
                "Browse with okf_list_notes / okf_get_note instead, or restart "
                "`okf serve` without --no-rag.")
        if self._index is None:
            from okfkit.serve.rag import Index
            try:
                self._index = Index.load(self.base_dir)
            except FileNotFoundError:
                raise SearchUnavailable(
                    f"No semantic index under {os.path.join(self.base_dir, '.okf')}. "
                    "Build one with `okf index` (pip install "
                    "'okf-wiki-kit[rag,local-embeddings]'), then retry. "
                    "okf_list_notes / okf_get_note work without an index.")
            except SystemExit as exc:   # missing numpy/SDK/API key from rag/embeddings
                raise SearchUnavailable(f"Could not load the semantic index: {exc}")
        return self._index

    def _index_info(self) -> dict:
        from okfkit.serve.rag import Index   # no optional deps at import time
        _npz, chunks_path = Index.paths(self.base_dir)
        if not os.path.exists(chunks_path):
            return {"present": False,
                    "hint": "Run `okf index` to enable okf_search."}
        try:
            with open(chunks_path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            return {"present": False, "hint": f"Index unreadable: {exc}"}
        header = data.get("header") or {}
        created = header.get("created")
        return {
            "present": True,
            "provider": header.get("provider"),
            "model": header.get("model"),
            "chunks": len(data.get("chunks") or []),
            "created": created,
            "stale": self._newer_than(created),
        }

    def _newer_than(self, created: str | None):
        """True if any note file is newer than the index timestamp (None if unknown)."""
        from okfkit import freshness
        return freshness.is_stale(
            created, freshness.newest_mtime(n.path for n in self.notes.values()))

    def _refs(self, ids) -> list[dict]:
        """Resolve link targets to {id, type, title} (unknown targets kept, untyped)."""
        out = []
        for t in ids:
            n = self.notes.get(t)
            out.append({"id": t, "type": n.type if n else "",
                        "title": n.title if n else t})
        return out

    def _missing(self, nid: str) -> dict:
        close = get_close_matches(nid, list(self.notes), n=5, cutoff=0.5)
        return {
            "error": f"No note with id {nid!r} in the vault.",
            "did_you_mean": close,
            "hint": ("Ids are wikilink targets (file basenames). Use okf_search "
                     "to find notes by content, or okf_list_notes to browse."),
        }


# ---------------------------------------------------------------------------
# MCP wiring (the only part that touches the optional `mcp` SDK)
# ---------------------------------------------------------------------------
def make_service(cfg_or_vault_path, use_rag: bool = True) -> VaultService:
    """Build a `VaultService` from a `config.Config` or a bare vault path."""
    vault_path, base_dir, settings = _resolve(cfg_or_vault_path)
    return VaultService(
        vault_path, base_dir=base_dir, use_rag=use_rag,
        max_note_chars=settings.get("max_note_chars") or DEFAULT_MAX_NOTE_CHARS,
    )


def create_server(cfg_or_vault_path, use_rag: bool = True):
    """Build a FastMCP server exposing the five read-only `okf_*` tools.

    *cfg_or_vault_path* is either a `config.Config` (vault = resolved
    `cfg.output`, index sidecar next to the config, `serve.mcp` settings
    honored) or a path to any built OKF vault. Returns the server without
    running it — call `.run()` (stdio) or pass a transport yourself.
    """
    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.types import ToolAnnotations
    except ImportError:
        raise SystemExit(
            "The 'mcp' package is required for the MCP server: "
            "pip install 'okf-wiki-kit[mcp]'")

    _vault_path, _base_dir, settings = _resolve(cfg_or_vault_path)
    service = make_service(cfg_or_vault_path, use_rag=use_rag)
    server = FastMCP(str(settings.get("name") or DEFAULT_SERVER_NAME),
                     instructions=_INSTRUCTIONS)

    def _read_only(title: str) -> ToolAnnotations:
        return ToolAnnotations(title=title, readOnlyHint=True, openWorldHint=False)

    @server.tool(annotations=_read_only("Search the wiki"))
    def okf_search(query: str, k: int = 8, types: list[str] | None = None) -> dict[str, Any]:
        """Semantic search over the wiki. Returns ranked hits
        {id, type, title, description, snippet, score}; pass a hit's `id` to
        okf_get_note for the full note. `types` optionally restricts results to
        those note types (see okf_vault_info for the available types)."""
        try:
            return {"hits": service.search(query, k=k, types=types)}
        except SearchUnavailable as exc:
            return {"error": str(exc)}

    @server.tool(annotations=_read_only("Read a note"))
    def okf_get_note(id: str, offset: int = 0) -> dict[str, Any]:
        """Fetch one note by id (wikilink target / file basename): frontmatter,
        markdown body, outgoing links and backlinks. Long bodies are windowed:
        when `truncated` is true, call again with the returned `next_offset`."""
        return service.get_note(id, offset=offset)

    @server.tool(annotations=_read_only("List notes"))
    def okf_list_notes(type: str | None = None, tag: str | None = None,
                       limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
        """List notes as {rows, total, next_cursor}, sorted by id, optionally
        filtered by note `type` and/or `tag` (case-insensitive). Paginate by
        passing the returned `next_cursor` back as `cursor` (null = done)."""
        return service.list_notes(type=type, tag=tag, limit=limit, cursor=cursor)

    @server.tool(annotations=_read_only("Graph neighbors"))
    def okf_neighbors(id: str, direction: str = "both") -> dict[str, Any]:
        """Link-graph neighbors of a note: `outgoing` wikilinks and `backlinks`
        (notes linking here), each {id, type, title}. `direction` is
        "outgoing", "backlinks" or "both"."""
        return service.neighbors(id, direction=direction)

    @server.tool(annotations=_read_only("Vault overview"))
    def okf_vault_info() -> dict[str, Any]:
        """Vault orientation (call this first): note counts by type, tag counts,
        total notes, and whether a semantic index is present/fresh for okf_search."""
        return service.vault_info()

    return server


def run(cfg_or_vault_path, use_rag: bool = True) -> int:
    """Create the server and block serving stdio (for `okf serve`).

    stdout belongs to the MCP transport — any CLI diagnostics must go to stderr
    before calling this.
    """
    server = create_server(cfg_or_vault_path, use_rag=use_rag)
    server.run()   # stdio transport
    return 0


def _resolve(cfg_or_vault_path) -> tuple[str, str, dict]:
    """-> (vault_path, base_dir, serve.mcp settings dict)."""
    if isinstance(cfg_or_vault_path, (str, os.PathLike)):
        vault = os.path.abspath(os.path.expanduser(os.fspath(cfg_or_vault_path)))
        return vault, os.path.dirname(vault), {}
    cfg = cfg_or_vault_path
    settings = (getattr(cfg, "serve", None) or {}).get("mcp") or {}
    return cfg.resolve(cfg.output), cfg.base_dir, settings


def _snippet(text: str, limit: int = 240) -> str:
    """Body-only preview of a chunk (drops the '{type}: {title}\\n{desc}' prefix)."""
    body = text.split("\n\n", 1)[-1]
    flat = " ".join(body.split())
    return flat[:limit] + ("…" if len(flat) > limit else "")


def _jsonable(value):
    """Frontmatter can hold YAML dates etc. — coerce to JSON-safe types."""
    return json.loads(json.dumps(value, default=str))
