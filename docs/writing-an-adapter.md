# Writing an adapter

An adapter turns *your* source into `Node`s. The engine does everything else. You implement
exactly one method.

## The contract

```python
from okfkit.model import Node, Link
from okfkit.adapters.base import SourceAdapter

class MyAdapter(SourceAdapter):
    def load(self):                 # -> Iterable[Node]
        ...
```

`self.options` holds the `adapter_options:` block from `okf.config.yaml`.

## The `Node`

| field | required | notes |
|-------|----------|-------|
| `id` | ✅ | Stable, unique. Becomes the filename and wikilink target. Safe ids (`[A-Za-z0-9 _-.]`) are preserved verbatim; others are slugged. |
| `type` | ✅ | OKF `type:` — any string. Nodes are grouped into a folder per type. |
| `title` | ✅ | Display name (used as wikilink text). |
| `body` | | Markdown body. If it doesn't start with an H1, the engine adds `# {title}`. |
| `frontmatter` | | Any extra YAML fields. A `description` key is rendered near the top. Values may contain `[[wikilinks]]`. |
| `links` | | `Link(target, rel, section, display)` edges. Rendered as a `## {section}` list of wikilinks in the body. |
| `tags`, `aliases` | | Obsidian-native. |

## The `Link`

```python
Link(target="other-node-id", rel="related", section="See also", display="Custom text")
```

- `target` — the `id` of another node (validated: must resolve).
- `section` — the `## heading` this link is listed under. If omitted, `rel` is used.
- `display` — link text; defaults to the target node's title.

## Two ways to model relationships

1. **Explicit links** — emit `Link`s. Best for structured sources where you know the edges
   (a chapter's sections, a case study's source). Rendered into `## section` lists.
2. **Inline wikilinks in `body`** — if your source already contains `[[Note]]` links (e.g. an
   existing Obsidian vault), just keep them in `body`; the built-in `markdown_folder` adapter
   does this. Set node ids to the target filenames so they resolve.

Don't do both for the same edge, or it renders twice.

## Let the engine infer concept links

Instead of hand-linking every concept mention, define concept nodes and enable inference in
`okf.config.yaml`:

```yaml
link_inference:
  concept_type: Concept       # nodes of this type…
  scan_types: [Section]       # …are matched (by title + aliases) inside these node bodies
  exclude_titles: [References]
```

The engine adds `Section → Concept` and `Concept → Section` links automatically.

## Worked example

See [`examples/textbook/adapter.py`](../examples/textbook/adapter.py): it reads
`chapter_NN_*.md` + `chapter_NN_metadata.json` files with inconsistent schemas and emits
Part / Chapter / Section / Concept / Case Study nodes. Point a config at it:

```yaml
adapter: examples/textbook/adapter.py:TextbookAdapter
adapter_options: { chapters_dir: /path/to/chapters }
link_inference: { concept_type: Concept, scan_types: [Section], exclude_titles: [References] }
enrich: { canonicalize_type: Concept, describe_types: [Chapter, "Case Study"] }
```

## Tips

- **Unique ids.** Duplicate ids raise an error. Prefix by type if needed (`concept-…`, `ch01-…`).
- **Keep domain logic in the adapter.** The engine stays generic — no source-specific code there.
- **Test with `okf validate`** after `okf build`: it reports any wikilink that doesn't resolve.
