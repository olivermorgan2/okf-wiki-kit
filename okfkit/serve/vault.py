"""Read layer over a built OKF vault on disk.

This is the shared foundation for Phase 7 (RAG) and Phase 8 (MCP): it loads any
OKF/Obsidian vault directory into lightweight `VaultNote`s (same posture as
`engine.validate_vault` — it reads the vault output, not the source, so it works
on any OKF vault regardless of which adapter produced it).

Only stdlib + `okfkit.render` (PyYAML via `split_frontmatter`) — no optional deps.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from okfkit import render


@dataclass
class VaultNote:
    """One markdown note read back from a built vault."""

    id: str                          # basename → wikilink target ("dir/index" for sub-indexes)
    path: str                        # absolute path of the .md file
    type: str                        # frontmatter `type:` ("" if absent)
    title: str                       # frontmatter `title:` (falls back to the basename)
    description: str = ""            # frontmatter `description:` ("" if absent)
    body: str = ""                   # markdown body (frontmatter removed)
    frontmatter: dict = field(default_factory=dict)   # the full frontmatter dict
    tags: list[str] = field(default_factory=list)     # frontmatter `tags:` as strings


def load_vault(path: str, exclude_types: tuple[str, ...] = ()) -> dict[str, VaultNote]:
    """Load every ``*.md`` note under *path* into ``{id: VaultNote}``.

    *exclude_types* drops notes whose frontmatter ``type`` matches
    (case-insensitive) — e.g. ``("Index", "Home")`` to skip generated indexes.
    Sub-directory ``index.md`` files get the id ``"{dir}/index"`` (mirroring
    `engine.validate_vault`) so ids stay unique.
    """
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(path):
        raise SystemExit(f"No vault at {path}. Run `okf build` first.")
    excluded = {t.strip().lower() for t in (exclude_types or ()) if t}
    notes: dict[str, VaultNote] = {}
    for root, _dirs, files in os.walk(path):
        rel = os.path.relpath(root, path)
        for fn in sorted(files):
            if not fn.endswith(".md"):
                continue
            full = os.path.join(root, fn)
            with open(full, encoding="utf-8") as fh:
                fm, body = render.split_frontmatter(fh.read())
            ntype = str(fm.get("type") or "")
            if ntype.lower() in excluded:
                continue
            base = fn[:-3]
            nid = base if (base != "index" or rel == ".") else f"{rel.replace(os.sep, '/')}/index"
            notes[nid] = VaultNote(
                id=nid,
                path=full,
                type=ntype,
                title=str(fm.get("title") or base),
                description=str(fm.get("description") or ""),
                body=body,
                frontmatter=fm,
                tags=[str(t) for t in (fm.get("tags") or [])],
            )
    return notes


def outgoing(note: VaultNote) -> list[str]:
    """Basenames this note links to: body wikilinks (code stripped) plus any
    wikilink-valued frontmatter fields (e.g. ``parent``, ``concepts``, ``chapters``).

    Order-preserving, deduplicated.
    """
    targets = render.find_wikilinks(render.strip_code(note.body))
    for value in note.frontmatter.values():
        items = value if isinstance(value, (list, tuple)) else [value]
        for item in items:
            if isinstance(item, str) and "[[" in item:
                targets += render.find_wikilinks(item)
    seen: set[str] = set()
    out: list[str] = []
    for t in targets:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def backlinks(notes: dict[str, VaultNote]) -> dict[str, list[str]]:
    """Reverse-link map ``{note id: [ids of notes that link to it]}``.

    Accepts the ``load_vault`` dict (or any iterable of `VaultNote`). Only edges
    whose target is a known note are recorded; self-links are ignored. Source
    lists are sorted and deduplicated.
    """
    if not isinstance(notes, dict):
        notes = {n.id: n for n in notes}
    incoming: dict[str, list[str]] = {nid: [] for nid in notes}
    for nid in sorted(notes):
        for target in outgoing(notes[nid]):
            if target != nid and target in incoming and nid not in incoming[target]:
                incoming[target].append(nid)
    return incoming
