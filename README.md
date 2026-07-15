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

## Optional: LLM enrichment

```bash
pip install -e ".[openai]"           # or ".[anthropic]"
export OPENROUTER_API_KEY=...        # or ANTHROPIC_API_KEY
okf enrich                           # writes enrichment.json (canonical concepts + descriptions)
okf build                            # rebuild, applying the enrichment
```

Enrichment is **provider-flexible**: Anthropic (`claude-sonnet-4-6`) or any OpenAI-compatible
endpoint such as **OpenRouter** (`qwen/qwen3.7-plus`). Provider is auto-detected from your env keys.

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
| `id` | stable unique id → becomes the filename / wikilink target |
| `type` | OKF `type:` value (required) — `"Chapter"`, `"Concept"`, or anything you invent |
| `title` | human-readable name (wikilink display) |
| `body` | markdown body (no frontmatter) |
| `frontmatter` | any extra YAML fields (may contain `[[wikilinks]]`) |
| `links` | edges to other nodes; each `Link(target, rel, section)` renders under a `## section` heading |
| `tags`, `aliases` | Obsidian-native tags and aliases |

## Roadmap

- **Now:** engine, markdown-folder adapter, custom adapters, link inference, LLM enrichment, CLI.
- **Planned (Phase 7):** semantic RAG — embeddings index + `okf ask` for meaning-based Q&A.
- **Planned (Phase 8):** MCP server — expose the vault as tools for Claude Code / Desktop / any client.

## License

MIT — see [LICENSE](LICENSE).
