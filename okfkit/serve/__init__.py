"""Reserved extension point for serving an OKF vault to LLMs/agents.

Planned (see README "Roadmap"):
  * Phase 7 — `rag.py`: embeddings index over nodes + retrieve-then-answer (`okf ask`).
  * Phase 8 — `mcp.py`: an MCP server exposing `search`, `get_node`, `nodes_by_field`,
    `concept_lookup` as tools for Claude Code / Desktop / any MCP client.

Not implemented yet — this package exists so those modules slot in without restructuring.
"""
