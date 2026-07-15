"""The `okf` command: build | enrich | validate | init."""

from __future__ import annotations

import argparse
import json
import os
import sys

from okfkit import __version__


def main(argv=None):
    ap = argparse.ArgumentParser(prog="okf", description="Build OKF/Obsidian wikis from any source.")
    ap.add_argument("--version", action="version", version=f"okf-wiki-kit {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("build", "enrich", "validate"):
        p = sub.add_parser(name, help=f"{name} the wiki")
        p.add_argument("-c", "--config", default="okf.config.yaml", help="path to okf.config.yaml")
    # enrich-only overrides
    ep = sub._name_parser_map["enrich"]
    ep.add_argument("--provider", choices=["anthropic", "openai"], default=None)
    ep.add_argument("--model", default=None)
    ep.add_argument("--base-url", default=None)

    ip = sub.add_parser("init", help="scaffold okf.config.yaml (and an adapter stub)")
    ip.add_argument("--adapter-stub", action="store_true", help="also write adapter.py template")

    args = ap.parse_args(argv)
    return {"build": _build, "enrich": _enrich, "validate": _validate, "init": _init}[args.cmd](args)


def _load(args):
    from okfkit import config
    from okfkit.adapters.base import load_adapter
    cfg = config.load(args.config)
    adapter = load_adapter(cfg.adapter, cfg.adapter_options)
    nodes = list(adapter.load())
    if not nodes:
        raise SystemExit(f"Adapter {cfg.adapter!r} produced no nodes — check your source path.")
    return cfg, nodes


def _enrichment_path(cfg):
    return os.path.join(cfg.base_dir, "enrichment.json")


def _build(args):
    from okfkit import engine
    cfg, nodes = _load(args)
    enrichment = None
    ep = _enrichment_path(cfg)
    if os.path.exists(ep):
        with open(ep, encoding="utf-8") as fh:
            enrichment = json.load(fh)
        print(f"(using {os.path.relpath(ep)})")
    result = engine.build(nodes, cfg.resolve(cfg.output),
                          link_style=cfg.link_style,
                          link_inference=cfg.link_inference,
                          enrichment=enrichment)
    print(result.summary())
    print(f"\nVault written to {cfg.resolve(cfg.output)}")
    return 0 if result.ok else 2


def _enrich(args):
    from okfkit import enrich
    cfg, nodes = _load(args)
    e = cfg.enrich or {}
    enrich.run(
        nodes, _enrichment_path(cfg),
        canonicalize_type=e.get("canonicalize_type", ""),
        describe_types=e.get("describe_types", []),
        provider=args.provider or e.get("provider"),
        model=args.model or e.get("model"),
        base_url=args.base_url or e.get("base_url"),
    )
    print("Now run:  okf build")
    return 0


def _validate(args):
    from okfkit import config, engine
    cfg = config.load(args.config)
    output = cfg.resolve(cfg.output)
    if not os.path.isdir(output):
        raise SystemExit(f"No vault at {output}. Run `okf build` first.")
    unresolved, total, counts = engine.validate_vault(output)
    print(f"Vault: {output}")
    for t in sorted(counts):
        print(f"  {t:16s}: {counts[t]}")
    print(f"  {'TOTAL files':16s}: {total}")
    if unresolved:
        print(f"\n!! {len(unresolved)} unresolved wikilink target(s):")
        for tgt, srcs in list(sorted(unresolved.items()))[:25]:
            print(f"   [[{tgt}]]  <- {srcs[0]}")
        return 2
    print("\n  All wikilinks resolve. ✓")
    return 0


def _init(args):
    dst = "okf.config.yaml"
    if os.path.exists(dst):
        print(f"{dst} already exists — leaving it untouched.")
    else:
        with open(dst, "w", encoding="utf-8") as fh:
            fh.write(_CONFIG_TEMPLATE)
        print(f"Wrote {dst}")
    if args.adapter_stub:
        if os.path.exists("adapter.py"):
            print("adapter.py already exists — leaving it untouched.")
        else:
            with open("adapter.py", "w", encoding="utf-8") as fh:
                fh.write(_ADAPTER_TEMPLATE)
            print("Wrote adapter.py")
    print("\nNext: edit okf.config.yaml, then run `okf build`.")
    return 0


_CONFIG_TEMPLATE = """\
adapter: markdown_folder
adapter_options:
  path: ./notes
  default_type: Note
output: ./vault
link_style: wikilink
link_inference:
  concept_type: ""
  scan_types: []
  min_surface_len: 5
  exclude_titles: ["References"]
enrich:
  provider: null
  model: null
  base_url: null
  describe_types: []
  canonicalize_type: ""
"""

_ADAPTER_TEMPLATE = '''\
"""Custom source adapter. Point okf.config.yaml at it: adapter: adapter.py:MyAdapter"""

from okfkit.model import Node, Link
from okfkit.adapters.base import SourceAdapter


class MyAdapter(SourceAdapter):
    def load(self):
        # self.options holds adapter_options from okf.config.yaml
        # Yield one Node per knowledge item:
        yield Node(
            id="example-1",
            type="Article",
            title="Example",
            body="# Example\\n\\nBody markdown here.",
            frontmatter={},
            links=[],           # e.g. [Link(target="example-2", rel="related", section="See also")]
            tags=[],
            aliases=[],
        )
'''


if __name__ == "__main__":
    sys.exit(main())
