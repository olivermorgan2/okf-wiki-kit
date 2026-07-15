"""The SourceAdapter contract and the resolver that loads one by name/path."""

from __future__ import annotations

import importlib
import importlib.util
import os
from abc import ABC, abstractmethod
from collections.abc import Iterable

from okfkit.model import Node

# short name -> "module:Class" for built-in adapters
BUILTINS = {
    "markdown_folder": "okfkit.adapters.markdown_folder:MarkdownFolderAdapter",
}


class SourceAdapter(ABC):
    """Subclass this and implement `load()`. That is the entire contract.

    Options from `okf.config.yaml`'s `adapter_options:` are passed as keyword
    arguments and stored on `self.options`.
    """

    def __init__(self, **options):
        self.options = options

    @abstractmethod
    def load(self) -> Iterable[Node]:
        """Yield (or return a list of) `Node`s built from the source."""
        raise NotImplementedError


def load_adapter(spec: str, options: dict | None = None) -> SourceAdapter:
    """Instantiate an adapter from a built-in name or a "path.py:Class" / "module:Class" spec."""
    options = options or {}
    if spec in BUILTINS:
        spec = BUILTINS[spec]
    if ":" not in spec:
        raise ValueError(
            f"Adapter spec {spec!r} must be a built-in name ({', '.join(BUILTINS)}) "
            f"or 'module_or_path:ClassName'."
        )
    target, class_name = spec.rsplit(":", 1)

    if target.endswith(".py") or os.path.sep in target or os.path.exists(target):
        module = _import_from_path(target)
    else:
        module = importlib.import_module(target)

    cls = getattr(module, class_name, None)
    if cls is None or not (isinstance(cls, type) and issubclass(cls, SourceAdapter)):
        raise ValueError(f"{class_name!r} in {target!r} is not a SourceAdapter subclass.")
    return cls(**options)


def _import_from_path(path: str):
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(path):
        raise FileNotFoundError(f"Adapter file not found: {path}")
    name = "okfkit_adapter_" + os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
