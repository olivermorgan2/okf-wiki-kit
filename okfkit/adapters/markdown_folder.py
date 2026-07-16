"""Built-in zero-code adapter: turn a folder of markdown files into OKF nodes.

Each `.md` file becomes one node. `type`, `title`, `tags`, and `aliases` are read
from YAML frontmatter if present (falling back to sensible defaults). The file's
existing inline `[[wikilinks]]` are left in the body untouched — filenames are
preserved as node ids so those links keep resolving, with one exception: when two
files in different folders share a filename, the first (in sorted path order) keeps
the plain stem id and later ones are disambiguated with their parent directory slug
(e.g. `archive/notes.md` → `archive-notes`), falling back to a slug of the full
relative path. A warning is printed to stderr whenever this happens. Explicit
frontmatter `id:` values are never rewritten.
"""

from __future__ import annotations

import sys
from pathlib import Path

from okfkit import render
from okfkit.adapters.base import SourceAdapter
from okfkit.model import Node


class MarkdownFolderAdapter(SourceAdapter):
    def load(self):
        root = Path(self.options.get("path", ".")).expanduser()
        if not root.is_dir():
            raise NotADirectoryError(f"markdown_folder: path is not a directory: {root}")
        default_type = self.options.get("default_type", "Note")

        seen: dict[str, Path] = {}                     # id -> first file that claimed it
        for f in sorted(root.glob("**/*.md")):
            if f.name.lower() == "readme.md":
                continue
            fm, body = render.split_frontmatter(f.read_text(encoding="utf-8"))
            explicit = fm.get("id")
            node_id = str(explicit or f.stem)          # preserve filename → inline links resolve
            if not explicit and node_id in seen:       # stem collision: disambiguate, first wins
                rel = f.relative_to(root)
                new_id = f"{render.slug(f.parent.name)}-{f.stem}"
                if new_id in seen:
                    new_id = render.slug(str(rel.with_suffix("")))
                print(f"Warning: markdown_folder: '{rel}' collides with "
                      f"'{seen[node_id].relative_to(root)}'; using id '{new_id}'.",
                      file=sys.stderr)
                node_id = new_id
            seen.setdefault(node_id, f)
            yield Node(
                id=node_id,
                type=str(fm.get("type") or default_type),
                title=str(fm.get("title") or f.stem),
                body=body.strip(),
                frontmatter={k: v for k, v in fm.items()
                             if k not in ("id", "title", "type", "tags", "aliases")},
                links=[],   # inline [[wikilinks]] already live in the body
                tags=_as_list(fm.get("tags")),
                aliases=_as_list(fm.get("aliases")),
            )


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    return [str(v)]
