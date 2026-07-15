"""Load and normalize `okf.config.yaml`."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    adapter: str = "markdown_folder"
    adapter_options: dict = field(default_factory=dict)
    output: str = "./vault"
    link_style: str = "wikilink"
    link_inference: dict = field(default_factory=dict)
    enrich: dict = field(default_factory=dict)
    base_dir: str = "."          # directory the config lives in (for resolving relative paths)

    def resolve(self, path: str) -> str:
        """Resolve a config-relative path against the config file's directory."""
        path = os.path.expanduser(path)
        return path if os.path.isabs(path) else os.path.normpath(os.path.join(self.base_dir, path))


def load(path: str = "okf.config.yaml") -> Config:
    import yaml

    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No config at {path}. Copy okf.config.example.yaml to okf.config.yaml, "
            f"or run `okf init`."
        )
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    cfg = Config(base_dir=os.path.dirname(path))
    cfg.adapter = data.get("adapter", cfg.adapter)
    cfg.adapter_options = data.get("adapter_options") or {}
    cfg.output = data.get("output", cfg.output)
    cfg.link_style = data.get("link_style", cfg.link_style)
    cfg.link_inference = data.get("link_inference") or {}
    cfg.enrich = data.get("enrich") or {}

    # resolve any path-like adapter option relative to the config file
    if "path" in cfg.adapter_options:
        cfg.adapter_options["path"] = cfg.resolve(cfg.adapter_options["path"])
    return cfg
