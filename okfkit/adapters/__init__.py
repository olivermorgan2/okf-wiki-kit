"""Source adapters — turn a specific source into `Node`s.

Built-in adapters are resolved by short name (e.g. "markdown_folder"). Custom
adapters are resolved by "path/to/file.py:ClassName".
"""

from okfkit.adapters.base import SourceAdapter, load_adapter

__all__ = ["SourceAdapter", "load_adapter"]
