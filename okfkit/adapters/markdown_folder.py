"""Built-in zero-code adapter: turn a folder of markdown files into OKF nodes.

Each `.md` file becomes one node. `type`, `title`, `tags`, and `aliases` are read
from YAML frontmatter if present (falling back to sensible defaults). The file's
existing inline `[[wikilinks]]` are left in the body untouched — filenames are
preserved as node ids so those links keep resolving.
"""

from __future__ import annotations

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

        for f in sorted(root.glob("**/*.md")):
            if f.name.lower() == "readme.md":
                continue
            fm, body = render.split_frontmatter(f.read_text(encoding="utf-8"))
            node_id = str(fm.get("id") or f.stem)      # preserve filename → inline links resolve
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
