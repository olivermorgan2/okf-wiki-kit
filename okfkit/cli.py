"""The `okf` command: build | enrich | validate | init | index | search | ask | serve | doctor."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys

from okfkit import __version__, envfile


def main(argv=None):
    envfile.load(envfile.candidates(os.getcwd()))
    ap = argparse.ArgumentParser(prog="okf", description="Build OKF/Obsidian wikis from any source.")
    ap.add_argument("--version", action="version", version=f"okf-wiki-kit {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    helps = {
        "build": "build the wiki",
        "enrich": "enrich the wiki",
        "validate": "validate the wiki",
        "index": "build/refresh the semantic embeddings index over the built vault",
        "search": "semantic search over the indexed vault (offline)",
        "ask": "answer a question from the vault (retrieve + LLM)",
        "serve": "run a read-only MCP server over the built vault (stdio, or --transport http)",
        "doctor": "check environment, config, keys, vault, and index health",
    }
    for name in ("build", "enrich", "validate", "index", "search", "ask", "serve", "doctor"):
        p = sub.add_parser(name, help=helps[name])
        p.add_argument("-c", "--config", default="okf.config.yaml", help="path to okf.config.yaml")
    # enrich-only overrides
    ep = sub._name_parser_map["enrich"]
    ep.add_argument("--provider", choices=["anthropic", "openai"], default=None)
    ep.add_argument("--model", default=None)
    ep.add_argument("--base-url", default=None)
    # index-only flags
    xp = sub._name_parser_map["index"]
    xp.add_argument("--force", action="store_true", help="re-embed everything (ignore cached rows)")
    # search/ask shared flags
    for name in ("search", "ask"):
        qp = sub._name_parser_map[name]
        qp.add_argument("query", help="natural-language query")
        qp.add_argument("-k", type=int, default=None, help="number of notes to retrieve (default: config top_k, else 8)")
        qp.add_argument("--type", action="append", default=None, metavar="TYPE",
                        help="restrict to this note type (repeatable)")
    # ask-only chat-backend overrides (mirrors `okf enrich`)
    kp = sub._name_parser_map["ask"]
    kp.add_argument("--provider", choices=["anthropic", "openai"], default=None)
    kp.add_argument("--model", default=None)
    kp.add_argument("--base-url", default=None)
    # serve-only flags
    sp = sub._name_parser_map["serve"]
    sp.add_argument("--vault", default=None, metavar="PATH",
                    help="serve this OKF vault directly (bypasses the config)")
    sp.add_argument("--no-rag", action="store_true",
                    help="disable okf_search (graph tools only; no index needed)")
    sp.add_argument("--register", action="store_true",
                    help="register this server with Claude Code via `claude mcp add`, "
                         "print the command, and exit")
    sp.add_argument("--transport", choices=["stdio", "http"], default="stdio",
                    help="MCP transport: stdio (default; what MCP clients spawn) "
                         "or http (FastMCP streamable-http on --host/--port)")
    sp.add_argument("--host", default="127.0.0.1", metavar="HOST",
                    help="bind address for --transport http (default: 127.0.0.1)")
    sp.add_argument("--port", type=int, default=8000, metavar="PORT",
                    help="port for --transport http (default: 8000)")

    ip = sub.add_parser("init", help="scaffold okf.config.yaml (and an adapter stub)")
    ip.add_argument("--adapter-stub", action="store_true", help="also write adapter.py template")

    args = ap.parse_args(argv)
    envfile.load_default(getattr(args, "config", None))
    return {"build": _build, "enrich": _enrich, "validate": _validate, "init": _init,
            "index": _index, "search": _search, "ask": _ask, "serve": _serve,
            "doctor": _doctor}[args.cmd](args)


def _load(args):
    from okfkit import config
    cfg = config.load(args.config)
    return cfg, _load_nodes(cfg)


def _load_nodes(cfg):
    from okfkit.adapters.base import load_adapter
    adapter = load_adapter(cfg.adapter, cfg.adapter_options)
    nodes = list(adapter.load())
    if not nodes:
        raise SystemExit(f"Adapter {cfg.adapter!r} produced no nodes — check your source path.")
    return nodes


def _enrichment_path(cfg):
    return os.path.join(cfg.base_dir, "enrichment.json")


def _guard_output(cfg, output):
    """Refuse an output whose clean-wipe would take the config or source with it."""
    out = os.path.normpath(output)
    targets = [(os.path.normpath(cfg.base_dir), "the config's own directory")]
    src = cfg.adapter_options.get("path")
    if src:
        targets.append((os.path.normpath(cfg.resolve(src)), "the adapter source path"))
    for target, name in targets:
        if out == target:
            raise SystemExit(f"output: resolves to {name} ({target}) — "
                             f"a clean build would wipe it.")
        if target.startswith(out + os.sep):
            raise SystemExit(f"output: ({out}) contains {name} ({target}) — "
                             f"a clean build would wipe it.")


def _build(args):
    from okfkit import config, engine
    cfg = config.load(args.config)
    output = cfg.resolve(cfg.output)
    _guard_output(cfg, output)
    nodes = _load_nodes(cfg)
    enrichment = None
    ep = _enrichment_path(cfg)
    if os.path.exists(ep):
        with open(ep, encoding="utf-8") as fh:
            enrichment = json.load(fh)
        print(f"(using {os.path.relpath(ep)})")
        src = cfg.adapter_options.get("path")
        if src and os.path.isdir(cfg.resolve(src)):
            from okfkit import freshness
            if os.path.getmtime(ep) < freshness.newest_mtime_under(cfg.resolve(src)):
                print("Warning: enrichment.json is older than the newest source file — "
                      "consider re-running `okf enrich`.")
    result = engine.build(nodes, output,
                          link_style=cfg.link_style,
                          link_inference=cfg.link_inference,
                          enrichment=enrichment,
                          clean=cfg.clean)
    print(result.summary())
    print(f"\nVault written to {output}")
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


def _rag_settings(cfg):
    """The `serve.rag` block of the config (all keys optional)."""
    return (cfg.serve or {}).get("rag") or {}


def _load_index(cfg, backend=None):
    from okfkit.serve import Index
    try:
        return Index.load(cfg.base_dir, backend=backend)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc))


def _warn_stale_index(cfg):
    """Stderr nudge when the vault outran the index (stdout stays pipeable)."""
    from okfkit import freshness
    if freshness.index_staleness(cfg.base_dir, cfg.resolve(cfg.output)):
        print("Warning: vault is newer than the index — run `okf index` to refresh.",
              file=sys.stderr)


def _chunk_max_chars(rag, provider):
    """Config value wins; otherwise 1000 for the static local model (mean-pooling
    long chunks blurs its vectors), 4000 for contextual hosted models."""
    return rag.get("chunk_max_chars") or (1000 if provider == "local" else 4000)


def _index(args):
    from okfkit import config
    from okfkit.serve import Index, chunk_notes, load_vault, make_embedder
    from okfkit.serve.embeddings import resolve_provider_model
    cfg = config.load(args.config)
    vault = cfg.resolve(cfg.output)
    rag = _rag_settings(cfg)
    emb = rag.get("embedding") or {}
    backend = make_embedder(provider=emb.get("provider"), model=emb.get("model"),
                            base_url=emb.get("base_url"))
    notes = load_vault(vault)
    provider, _ = resolve_provider_model(emb.get("provider"), emb.get("model"))
    chunks = chunk_notes(
        notes,
        max_chars=_chunk_max_chars(rag, provider),
        exclude_types=tuple(rag.get("exclude_types") or ("Index", "Home")),
    )
    try:
        idx = (Index(backend, vault_path=vault) if args.force
               else Index.load(cfg.base_dir, backend=backend))
    except FileNotFoundError:
        idx = Index(backend, vault_path=vault)
    idx.vault_path = vault
    print(f"Vault: {vault}  ({len(notes)} notes -> {len(chunks)} chunks)")
    stats = idx.build(chunks, force=args.force)
    npz_path, chunks_path = idx.save(cfg.base_dir)
    print(f"  embedded {stats['embedded']}, reused {stats['reused']}, total {stats['total']}")
    print(f"Index written to {os.path.dirname(npz_path)}")
    return 0


def _search(args):
    from okfkit import config
    cfg = config.load(args.config)
    k = args.k or _rag_settings(cfg).get("top_k") or 8
    idx = _load_index(cfg)
    _warn_stale_index(cfg)
    hits = idx.search(args.query, k=k, types=args.type)
    if not hits:
        print("No matches.")
        return 2
    for h in hits:
        head = f"  · {h.heading}" if h.heading else ""
        print(f"  {h.score:6.3f}  [{h.type or '-'}] {h.node_id} — {h.title}{head}")
    return 0


def _ask(args):
    from okfkit import config, enrich
    from okfkit.serve import ask
    cfg = config.load(args.config)
    rag = _rag_settings(cfg)
    k = args.k or rag.get("top_k") or 8
    idx = _load_index(cfg)
    _warn_stale_index(cfg)
    e = cfg.enrich or {}
    backend = enrich.make_backend(
        provider=args.provider or e.get("provider"),
        model=args.model or e.get("model"),
        base_url=args.base_url or e.get("base_url"),
    )
    answer, hits = ask(args.query, idx, backend, k=k, types=args.type)
    print(answer)
    if not hits:
        return 2
    print("\nSources:")
    for h in hits:
        print(f"  {h.score:6.3f}  [[{h.node_id}]] {h.title}")
    return 0


def _register_hint(*serve_args):
    """A `claude mcp add` line pinned to this exact interpreter. MCP clients
    spawn servers with no shell/venv/PATH, so a bare `okf` would silently
    never start for a venv install. `_register` runs the equivalent command
    for `okf serve --register` — keep the two in sync."""
    exe = shlex.quote(sys.executable)
    return f"claude mcp add okf-wiki -- {exe} -m okfkit.cli serve " + " ".join(serve_args)


def _register(args):
    """Run `claude mcp add` for this server and report the outcome.

    Builds the same pinned-interpreter command as `_register_hint` — keep the
    two in sync. Safe to print to stdout: the MCP transport never starts here.
    """
    from okfkit.serve.mcp import DEFAULT_SERVER_NAME
    if args.vault:
        name = DEFAULT_SERVER_NAME
        tail = ["--vault", os.path.abspath(os.path.expanduser(args.vault))]
    else:
        from okfkit import config
        cfg = config.load(args.config)
        name = str(((cfg.serve or {}).get("mcp") or {}).get("name") or DEFAULT_SERVER_NAME)
        tail = ["-c", os.path.abspath(args.config)]
    cmd = ["claude", "mcp", "add", name, "--",
           sys.executable, "-m", "okfkit.cli", "serve"] + tail
    if args.no_rag:
        cmd.append("--no-rag")
    print("Running:", " ".join(shlex.quote(c) for c in cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        print("claude CLI not found on PATH. Install Claude Code, or run the "
              "command above manually.", file=sys.stderr)
        return 1
    if proc.returncode != 0:
        if "already exists" in (proc.stderr or "").lower():
            print(f"Server {name!r} is already registered. Remove it first: "
                  f"claude mcp remove {name}", file=sys.stderr)
        else:
            sys.stderr.write(proc.stderr or "")
        return 1
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    print(f"Registered {name!r}.")
    return 0


def _serve(args):
    """Run the read-only MCP server (stdio by default, or streamable HTTP with
    --transport http). Under stdio, stdout belongs to the MCP transport once
    `run()` starts — all diagnostics go to stderr (kept for http too, for
    consistency)."""
    if args.register:
        if args.transport == "http":
            print("Note: --register always registers the stdio form (Claude Code "
                  "spawns MCP servers over stdio); ignoring --transport http.")
        return _register(args)
    # never prompt for keys, and keep model-download progress off stdout
    os.environ["OKF_NONINTERACTIVE"] = "1"
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    from okfkit.serve import mcp as mcpmod
    if args.vault:
        target = os.path.abspath(os.path.expanduser(args.vault))
        if not os.path.isdir(target):
            raise SystemExit(f"No vault at {target}.")
        register = _register_hint("--vault", target)
    else:
        from okfkit import config
        target = config.load(args.config)
        register = _register_hint("-c", os.path.abspath(args.config))
    if args.no_rag:
        register += " --no-rag"
    if args.transport == "http":
        print(f"okf MCP server starting (streamable HTTP) at "
              f"http://{args.host}:{args.port}/mcp", file=sys.stderr)
    else:
        print("okf MCP server starting (stdio). Register it with e.g.:", file=sys.stderr)
        print(f"  {register}", file=sys.stderr)
    return mcpmod.run(target, use_rag=not args.no_rag,
                      transport=args.transport, host=args.host, port=args.port)


def _doctor(args):
    from okfkit import doctor
    return doctor.run(args.config)


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
# clean: true              # wipe the output dir before each build (false = keep stray files)
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
# Serving the built vault to LLMs/agents (optional) — see okf.config.example.yaml.
# serve:
#   rag:                   # `okf index` / `okf search` / `okf ask` (needs the "rag" extra)
#     embedding:
#       provider: null     # "voyage" | "openai" | "local" ; null = auto-detect from env keys
#       model: null
#       base_url: null
#     chunk_max_chars: 4000  # default: 1000 for provider local, else 4000
#     exclude_types: [Index, Home]
#     top_k: 8
#   mcp:                   # `okf serve` (needs the "mcp" extra)
#     name: okf-wiki
#     max_note_chars: 20000
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
