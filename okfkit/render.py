"""Pure rendering helpers: slugs, YAML frontmatter, wikilinks, file writing.

These are side-effect-free (except `write_note`) and depend only on the stdlib
plus PyYAML (a core dependency), so they are easy to test and reuse. Ported
from the original one-off generator.
"""

from __future__ import annotations

import os
import re

import yaml

_slug_strip = re.compile(r"[^a-z0-9]+")
_lead_num = re.compile(r"^\s*\d+(\.\d+)*\.?\s+")     # strip "1.2 " / "3. " prefixes
_wikilink_re = re.compile(r"\[\[([^\]|#]+)")          # capture the target of [[target|display]]


def slug(text: str) -> str:
    """Filesystem/wikilink-safe slug: lowercase, hyphenated, leading numbers stripped."""
    text = _lead_num.sub("", text or "").lower()
    text = _slug_strip.sub("-", text).strip("-")
    return text or "untitled"


def frontmatter(fields: dict) -> str:
    """Render an ordered YAML frontmatter block. List values become YAML sequences.

    `None` values and empty lists are omitted. Insertion order is preserved.
    Emitted via PyYAML so quoting/escaping is always valid YAML.
    """
    plain = {}
    for k, v in fields.items():
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            if not v:
                continue
            v = list(v)
        plain[k] = v
    if not plain:
        return "---\n---\n"
    dumped = yaml.safe_dump(
        plain, sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    return "---\n" + dumped + "---\n"


def wikilink(basename: str, display: str | None = None, style: str = "wikilink") -> str:
    """Render a link to another node.

    style="wikilink" → Obsidian ``[[basename|display]]`` (unique basename + alias).
    style="markdown" → strict-OKF ``[display](basename.md)``.
    """
    disp = display if display and display != basename else None
    if style == "markdown":
        return f"[{disp or basename}]({basename}.md)"
    return f"[[{basename}|{disp}]]" if disp else f"[[{basename}]]"


# convenient short alias used throughout the engine
wl = wikilink


def find_wikilinks(text: str) -> list[str]:
    """Return the basenames targeted by every ``[[wikilink]]`` in *text*."""
    return [m.strip() for m in _wikilink_re.findall(text)]


def strip_code(text: str) -> str:
    """Remove fenced and inline code spans (so code examples aren't scanned for links)."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`]*`", "", text)


def write_note(path: str, front: dict, body: str) -> None:
    """Write a markdown note: frontmatter block, blank line, then body."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(frontmatter(front))
        fh.write("\n")
        fh.write(body.rstrip() + "\n")


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Split a markdown string into (frontmatter dict, body). Requires PyYAML.

    Returns ({}, text) when there is no leading `---` frontmatter block.
    """
    if not text.startswith("---"):
        return {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    data = yaml.safe_load(m.group(1)) or {}
    if not isinstance(data, dict):
        data = {}
    return data, m.group(2)
