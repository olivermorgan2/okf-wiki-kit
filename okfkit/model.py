"""The normalized data model shared between adapters and the engine.

An adapter's only job is to turn a source into `Node`s. The engine turns `Node`s
into an OKF/Obsidian vault. `Node` and `Link` are the entire contract between them.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Link:
    """A directed edge from one node to another.

    Rendered by the engine as a wikilink in a ``## {section}`` list within the
    source node's body. Links also participate in validation (the target must
    resolve to a real node).
    """

    target: str                      # id of another Node
    rel: str = "related"             # relation label (free text): "parent", "concept", "case", …
    section: str | None = None       # heading to group this link under; None → rel is used
    display: str | None = None       # link display text; None → target node's title


@dataclass
class Node:
    """A single typed knowledge node — becomes one markdown file in the vault."""

    id: str                          # stable unique id → filename basename & wikilink target
    type: str                        # OKF `type:` (required). "Chapter", "Concept", anything.
    title: str                       # human-readable name (wikilink display)
    body: str = ""                   # markdown body (no frontmatter, no leading H1 required)
    frontmatter: dict = field(default_factory=dict)   # extra YAML fields (may contain wikilinks)
    links: list[Link] = field(default_factory=list)   # edges rendered into the body
    tags: list[str] = field(default_factory=list)     # Obsidian tags (without leading '#')
    aliases: list[str] = field(default_factory=list)  # Obsidian aliases

    def __post_init__(self) -> None:
        if not self.type:
            raise ValueError(f"Node {self.id!r} has no `type` (OKF requires it).")
        if not self.id:
            raise ValueError(f"Node with title {self.title!r} has no `id`.")
