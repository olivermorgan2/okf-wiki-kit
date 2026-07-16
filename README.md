# okf-wiki-kit

Build a cross-linked **[Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
(OKF)** knowledge wiki — browsable in **Obsidian** and consumable by **LLMs/agents** — from *any*
source material.

OKF represents knowledge as a directory of markdown files: each file is a typed node with YAML
frontmatter (only `type` is required) and `[[wikilinks]]` that form a knowledge graph richer than
the folder hierarchy. `okf-wiki-kit` gives you a small, dependency-light engine that turns your
content into such a bundle, with optional LLM enrichment.

## How it works

```
your source ──► SourceAdapter.load() ──► [Node, Node, …] ──► engine ──► OKF/Obsidian vault
                (you write ~40 lines,        (normalized)      (generic: frontmatter, wikilinks,
                 or use a built-in one)                          indexes, link-inference, validate)
```

You implement **one method** — `load() -> Iterable[Node]` — that turns your source into a list of
`Node`s. The engine does everything else: unique filenames, frontmatter, wikilinks, per-type and
root `index.md` files, optional mention-based link inference, validation, and optional LLM
enrichment.

## Quickstart (zero code)

Point the built-in *markdown-folder* adapter at any folder of `.md` files:

```bash
pip install -e .                     # or: pip install okf-wiki-kit
cp okf.config.example.yaml okf.config.yaml
# edit okf.config.yaml -> adapter_options.path: ./my-notes
okf build                            # writes ./vault
okf validate                         # every node typed, every wikilink resolves
```

Open the `./vault` folder in Obsidian and look at the Graph View.

Nested folders work, with one wrinkle: repeated filenames are disambiguated — the first
`notes.md` keeps the id `notes`, a second one in another folder gets a parent-dir-prefixed id
like `projects-notes` (a warning names both files). A source note named `index.md` is renamed
(`index-2`) so it doesn't collide with the generated type index.

## Optional: LLM enrichment

```bash
pip install -e ".[openai]"           # or ".[anthropic]"  ([openrouter] is an alias of [openai])
export OPENROUTER_API_KEY=...        # or ANTHROPIC_API_KEY
okf enrich                           # writes enrichment.json (canonical concepts + descriptions)
okf build                            # rebuild, applying the enrichment
```

Order matters: the pipeline is **`enrich → build → index → serve`**. `enrich` writes
`enrichment.json`, which `build` consumes; `index` embeds the built vault. Running steps out of
order silently produces stale output (the CLI warns when it detects this).

Enrichment is **provider-flexible**: Anthropic (`claude-sonnet-4-6`) or any OpenAI-compatible
endpoint such as **OpenRouter** (`qwen/qwen3.7-plus`). Provider is auto-detected from your env keys.

## Optional: semantic search

```bash
pip install -e ".[rag,local-embeddings]"
okf index                            # embeds the built vault into .okf/
okf search "how does delegation build trust?"
```

The default embedding provider is `local` (`potion-base-8M`): no API key and nothing downloaded
at install (the model fetches on first use), but it is a static model — expect soft ranking on
topically homogeneous vaults. If retrieval feels vague, set `serve.rag.embedding.provider: voyage`
(or `openai`) in `okf.config.yaml`.

## Writing your own adapter

For structured sources (JSON, a database, a CMS), write a small adapter:

```python
from okfkit.model import Node, Link
from okfkit.adapters.base import SourceAdapter

class MyAdapter(SourceAdapter):
    def load(self):
        for row in my_source():
            yield Node(
                id=row["slug"], type="Article", title=row["title"],
                body=row["markdown"],
                frontmatter={"author": row["author"]},
                links=[Link(target=t, rel="related", section="See also")
                       for t in row["related_slugs"]],
                tags=row["tags"],
            )
```

Point `okf.config.yaml` at it: `adapter: path/to/my_adapter.py:MyAdapter`. See
[`docs/writing-an-adapter.md`](docs/writing-an-adapter.md) and the worked example in
[`examples/textbook/`](examples/textbook/).

## The `Node` model

| field | meaning |
|-------|---------|
| `id` | stable unique id → becomes the filename / wikilink target. Exception: when `enrich.canonicalize_type` is set, nodes of that type are merged under a canonical name and their ids/filenames may be rewritten (e.g. `concept-progressive-trust` → `progressive-trust`) |
| `type` | OKF `type:` value (required) — `"Chapter"`, `"Concept"`, or anything you invent |
| `title` | human-readable name (wikilink display) |
| `body` | markdown body (no frontmatter) |
| `frontmatter` | any extra YAML fields (may contain `[[wikilinks]]`) |
| `links` | edges to other nodes; each `Link(target, rel, section)` renders under a `## section` heading |
| `tags`, `aliases` | Obsidian-native tags and aliases |

## Use with Claude Code / Claude Desktop

Serve a built vault as a read-only MCP server so agents can query it as tools:

```bash
pip install -e ".[mcp]"
claude mcp add okf-wiki -- /path/to/venv/bin/python -m okfkit.cli serve -c /abs/path/okf.config.yaml
```

MCP clients spawn servers without your shell's PATH, so point at your venv's `python` directly —
running `okf serve` prints the exact command for your install.

The same applies to environment: the client spawns `okf serve` with no shell, no venv activation,
and no inherited environment, so keys exported in `.zshrc` never reach the server. Put keys in a
`.env` next to your config (the kit loads it automatically), and run `okf doctor` to check what
the server will actually see.

The server exposes five read-only tools: `okf_vault_info` (orientation — call first),
`okf_search` (semantic; needs a prior `okf index`), `okf_list_notes` (browse/paginate by type or
tag), `okf_get_note` (full note with links and backlinks), and `okf_neighbors` (walk the link
graph). The graph tools need no API keys. Use `okf serve --vault /abs/path/vault` to serve any
OKF vault without a config, and `--no-rag` for graph tools only.

## Roadmap

- **Build** — engine, markdown-folder adapter, custom adapters, link inference, LLM enrichment, CLI.
- **Semantic RAG (Phase 7) ✓** — `okf index` / `okf search` / `okf ask`: embeddings index + retrieval-augmented Q&A.
- **MCP server (Phase 8) ✓** — `okf serve`: expose the vault as read-only tools for Claude Code / Desktop / any MCP client.

See [`docs/roadmap.md`](docs/roadmap.md) for details.

## License

MIT — see [LICENSE](LICENSE).
