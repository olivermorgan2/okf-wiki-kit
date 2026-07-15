"""Serve an OKF vault to LLMs/agents.

Phase 7 (implemented):
  * `vault.py`      — read layer over a built vault: `VaultNote`, `load_vault`,
    `outgoing`, `backlinks`. Stdlib + PyYAML only.
  * `embeddings.py` — `EmbeddingBackend`/`make_embedder` (voyage | openai | local),
    mirroring `enrich.Backend`; all SDKs (and numpy) optional + lazy-imported.
  * `rag.py`        — `chunk_notes`, `Index` (build/refresh/save/load/search under
    `{base_dir}/.okf/`), and `ask` (retrieve-then-answer via `enrich.Backend.text`).

Phase 8 (implemented):
  * `mcp.py`        — read-only MCP server: `VaultService` (all logic, MCP-free,
    unit-testable) + `create_server`/`run` registering the five `okf_*` tools
    (search, get_note, list_notes, neighbors, vault_info) for Claude Code /
    Desktop / any MCP client. The `mcp` SDK is optional + lazy-imported.
"""

from okfkit.serve.embeddings import DEFAULT_EMBED_MODELS, EmbeddingBackend, make_embedder
from okfkit.serve.mcp import SearchUnavailable, VaultService, create_server, make_service
from okfkit.serve.mcp import run as run_mcp
from okfkit.serve.rag import Chunk, Hit, Index, ask, chunk_notes
from okfkit.serve.vault import VaultNote, backlinks, load_vault, outgoing

__all__ = [
    "VaultNote", "load_vault", "outgoing", "backlinks",
    "EmbeddingBackend", "make_embedder", "DEFAULT_EMBED_MODELS",
    "Chunk", "Hit", "Index", "chunk_notes", "ask",
    "VaultService", "SearchUnavailable", "make_service", "create_server", "run_mcp",
]
