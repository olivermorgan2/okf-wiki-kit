# Roadmap

`okf-wiki-kit` covers the full **build** pipeline: a generic engine plus
swappable source adapters that turn any source material into an Open Knowledge Format (OKF)
/ Obsidian vault, with optional LLM enrichment (`okf build | enrich | validate | init`).

Both phases below shipped in **v0.2.0**, behind the `okfkit/serve/` package. All their
dependencies are **optional extras** — the core stays PyYAML-only.

## Phase 7 — Semantic RAG ✓ (shipped v0.2.0)

Add an embeddings index over a built vault plus retrieval, exposed as new CLI commands:

- **`okf index`** — build/refresh an embeddings index for a vault (incremental; only
  re-embeds changed notes).
- **`okf search`** — semantic search over the vault. Works fully offline.
- **`okf ask`** — retrieve-then-answer, citing the notes it used as wikilinks.

Design direction:

- **Swappable embedding backends**, mirroring the existing provider-flexible enrichment:
  a hosted option, an OpenAI-compatible option, and a **local/offline** option so the kit
  works with zero API keys.
- **Lightweight vector store** appropriate to personal-knowledge scale (hundreds–thousands
  of notes) — no external vector database required. The index is stored *alongside* your
  config, never inside the vault (a rebuild wipes vault output).
- **Vault-granular chunking**: OKF vaults are already note-per-section, so most notes embed
  as a single chunk; only oversized notes are split at headings.

## Phase 8 — MCP Server ✓ (shipped v0.2.0)

Expose a vault (and Phase 7 retrieval) over the Model Context Protocol so any MCP client
(e.g. Claude Code / Claude Desktop) can query the knowledge graph as tools:

- **`okf serve`** — launch a read-only MCP server for a vault.

Tool surface (read-only): semantic `search`, `get_note`, `list_notes` (by type/tag,
paginated), `neighbors` (links + backlinks), and `vault_info` (orientation). stdio transport
first, with room for HTTP later.

---

*Phases 7 and 8 shipped in v0.2.0. Contributions and feedback welcome — see [CONTRIBUTING.md](../CONTRIBUTING.md).*
