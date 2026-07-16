"""`okf doctor`: preflight checks for the silent failure modes, each with a remedy.

Every serious failure in this kit is silent by default: an MCP server that was
never registered, an API key exported in the shell that an MCP-client-spawned
`okf serve` can never see, an index that quietly went stale. Each check here
detects one of those and prints the exact command that fixes it.

The headline check is key PROVENANCE, not key presence: `os.environ` alone
would green-light a shell-exported key that is invisible to MCP-spawned
servers, so keys are only "ok" when `okfkit.envfile` loaded them from a .env
file (or found them there).
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass

from okfkit import envfile, freshness

_ICONS = {"ok": "✓", "warn": "⚠", "fail": "✗"}


@dataclass
class Check:
    status: str          # "ok" | "warn" | "fail"
    label: str
    detail: str
    remedy: str = ""


def run(config_path: str = "okf.config.yaml") -> int:
    """Run every check, print one line each (+ indented remedy), return 1 on any fail."""
    envfile.load_default(config_path)   # idempotent; populates provenance for key checks
    cfg, cfg_check = _load_config(config_path)

    checks: list[Check] = []
    checks += _guarded("okf executable", _check_okf)
    checks += _guarded("MCP registration", _check_mcp, cfg)
    checks.append(cfg_check)
    checks += _guarded("API keys", _check_keys, cfg)
    checks += _guarded("vault", _check_vault, cfg)
    checks += _guarded("enrichment", _check_enrichment, cfg)
    checks += _guarded("semantic index", _check_index, cfg)
    checks += _guarded("models", _check_models, cfg)

    for c in checks:
        print(f"{_ICONS.get(c.status, '?')} {c.label}: {c.detail}")
        if c.remedy and c.status != "ok":
            print(f"    {c.remedy}")
    return 1 if any(c.status == "fail" for c in checks) else 0


def _guarded(label, fn, *args) -> list[Check]:
    """A crashing check becomes a warn line, never a dead report."""
    try:
        result = fn(*args)
    except Exception as exc:
        result = Check("warn", label, f"check crashed: {exc}")
    return result if isinstance(result, list) else [result]


# ---------------------------------------------------------------------------
# 1. okf executable
# ---------------------------------------------------------------------------
def _check_okf() -> Check:
    path = shutil.which("okf")
    if path:
        return Check("ok", "okf executable", path)
    return Check(
        "warn", "okf executable", "not on PATH",
        "MCP clients spawn servers without your PATH; register with: "
        f"{sys.executable} -m okfkit.cli serve --register  (or `okf serve --register`)")


# ---------------------------------------------------------------------------
# 2. MCP registration (claude CLI)
# ---------------------------------------------------------------------------
def _check_mcp(cfg) -> Check:
    from okfkit.serve.mcp import DEFAULT_SERVER_NAME   # constant only; mcp SDK stays lazy
    name = DEFAULT_SERVER_NAME
    if cfg is not None:
        name = str(((cfg.serve or {}).get("mcp") or {}).get("name") or name)

    listed = _claude("mcp", "list")
    if listed is None:
        return Check("warn", "MCP registration", "claude CLI not found — skipping MCP checks")
    if not re.search(rf"^\s*{re.escape(name)}\b", listed, re.M):
        return Check("warn", "MCP registration",
                     f"server {name!r} is not registered — MCP clients cannot see this vault",
                     "okf serve --register")

    # registered — verify the spawn command actually resolves (a bad path never
    # errors visibly: the client just shows no okf tools)
    detail = _claude("mcp", "get", name) or ""
    exe = _registered_command(detail)
    if exe and not _resolves(exe):
        return Check("fail", "MCP registration",
                     f"{name!r} is registered but its command {exe!r} does not resolve "
                     "— the server silently never starts",
                     "re-register: okf serve --register")
    return Check("ok", "MCP registration",
                 f"{name!r} registered" + (f" ({exe})" if exe else ""))


def _claude(*args) -> str | None:
    """stdout of `claude ...`, or None when the CLI is missing/hanging."""
    try:
        proc = subprocess.run(["claude", *args], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return proc.stdout or ""


def _registered_command(text: str) -> str | None:
    """First executable token of the 'Command: ...' line in `claude mcp get` output."""
    for line in text.splitlines():
        s = line.strip()
        if s.lower().startswith("command:"):
            rest = s.split(":", 1)[1].strip()
            try:
                tokens = shlex.split(rest)
            except ValueError:
                tokens = rest.split()
            return tokens[0] if tokens else None
    return None


def _resolves(exe: str) -> bool:
    if os.path.isabs(exe) or os.sep in exe:
        return os.path.isfile(exe) and os.access(exe, os.X_OK)
    return shutil.which(exe) is not None


# ---------------------------------------------------------------------------
# 3. config
# ---------------------------------------------------------------------------
def _load_config(config_path):
    """-> (Config | None, the config Check). Never raises."""
    from okfkit import config
    try:
        cfg = config.load(config_path)
    except FileNotFoundError:
        return None, Check("warn", "config",
                           f"not found at {os.path.abspath(config_path)}",
                           "run `okf init`, or pass -c path/to/okf.config.yaml")
    except Exception as exc:
        return None, Check("fail", "config", f"could not parse: {exc}")
    serve_note = "serve: block present" if cfg.serve else "no serve: block (defaults)"
    return cfg, Check("ok", "config",
                      f"{os.path.join(cfg.base_dir, os.path.basename(config_path))} ({serve_note})")


# ---------------------------------------------------------------------------
# 4. API keys — provenance, not mere presence (the headline check)
# ---------------------------------------------------------------------------
def _check_keys(cfg) -> list[Check]:
    from okfkit import enrich
    from okfkit.serve import embeddings

    config_dir = cfg.base_dir if cfg is not None else os.getcwd()
    checks: list[Check] = []

    # enrichment key: only required when the config actually enables enrichment
    e = (cfg.enrich or {}) if cfg is not None else {}
    if e:
        provider, _model = enrich.resolve_provider_model(e.get("provider"), e.get("model"))
        vars_ = {"anthropic": ["ANTHROPIC_API_KEY"],
                 "openai": ["OPENROUTER_API_KEY", "OPENAI_API_KEY"]}.get(provider, [])
        checks.append(_key_check(f"enrich key ({provider})", vars_, config_dir))
    else:
        checks.append(Check("ok", "enrich key", "enrichment not configured — no key needed"))

    # embedding key: always relevant (index/search), "local" needs none
    rag = ((cfg.serve or {}).get("rag") or {}) if cfg is not None else {}
    emb = rag.get("embedding") or {}
    provider, _model = embeddings.resolve_provider_model(emb.get("provider"), emb.get("model"))
    vars_ = {"voyage": ["VOYAGE_API_KEY"], "openai": ["OPENAI_API_KEY"]}.get(provider, [])
    checks.append(_key_check(f"embedding key ({provider})", vars_, config_dir))
    return checks


def _key_check(label: str, vars_: list[str], config_dir: str) -> Check:
    """Provenance verdict for one key requirement (any var in *vars_* satisfies it)."""
    if not vars_:
        return Check("ok", label, "no key needed")
    var = next((v for v in vars_ if os.environ.get(v) or v in envfile.found), None)
    if var is None:
        alts = " (or ".join(vars_) + ")" * (len(vars_) - 1)
        return Check("fail", label,
                     f"Set {alts} in {os.path.join(config_dir, '.env')}")
    if var in envfile.applied or (var in os.environ and var in envfile.found):
        return Check("ok", label,
                     f"{var} loaded from {envfile.applied.get(var) or envfile.found[var]} "
                     "— works for MCP-spawned servers too")
    return Check("warn", label,
                 f"{var} is set in this shell only — an MCP-spawned `okf serve` "
                 "will NOT see it",
                 f"add it to {os.path.join(config_dir, '.env')}")


# ---------------------------------------------------------------------------
# 5. vault
# ---------------------------------------------------------------------------
def _check_vault(cfg) -> Check:
    if cfg is None:
        return Check("warn", "vault", "skipped: no config")
    from okfkit import engine
    output = cfg.resolve(cfg.output)
    if not os.path.isdir(output):
        return Check("fail", "vault", f"no vault at {output}", "run `okf build`")
    unresolved, total, counts = engine.validate_vault(output)
    parts = [f"{t}: {counts[t]}" for t in sorted(counts)]
    detail = f"{total} files at {output}" + (f" ({', '.join(parts)})" if parts else "")
    if unresolved:
        return Check("warn", "vault",
                     f"{detail}; {len(unresolved)} unresolved wikilink target(s)",
                     "run `okf validate` for the list")
    return Check("ok", "vault", detail)


# ---------------------------------------------------------------------------
# 6. enrichment freshness
# ---------------------------------------------------------------------------
def _check_enrichment(cfg) -> Check:
    if cfg is None:
        return Check("warn", "enrichment", "skipped: no config")
    ep = os.path.join(cfg.base_dir, "enrichment.json")   # cli._enrichment_path
    if not os.path.exists(ep):
        return Check("ok", "enrichment", "no enrichment.json (optional)")
    src = cfg.adapter_options.get("path")                # already config-resolved
    if src and os.path.exists(src) and \
            os.path.getmtime(ep) < freshness.newest_mtime_under(src):
        return Check("warn", "enrichment", "enrichment.json is older than the sources",
                     "re-run `okf enrich` (then `okf build`)")
    return Check("ok", "enrichment", ep)


# ---------------------------------------------------------------------------
# 7. semantic index freshness
# ---------------------------------------------------------------------------
def _check_index(cfg) -> Check:
    if cfg is None:
        return Check("warn", "semantic index", "skipped: no config")
    header = freshness.index_header(cfg.base_dir)
    if header is None:
        return Check("warn", "semantic index", "none built — okf_search will be unavailable",
                     "run `okf index`")
    if freshness.index_staleness(cfg.base_dir, cfg.resolve(cfg.output)):
        return Check("warn", "semantic index", "vault is newer than the index",
                     "re-run `okf index`")
    return Check("ok", "semantic index",
                 f"{header.get('provider')} · {header.get('model')}")


# ---------------------------------------------------------------------------
# 8. models
# ---------------------------------------------------------------------------
def _check_models(cfg) -> Check:
    from okfkit import enrich
    from okfkit.serve import embeddings

    e = (cfg.enrich or {}) if cfg is not None else {}
    en_provider, en_model = enrich.resolve_provider_model(e.get("provider"), e.get("model"))
    rag = ((cfg.serve or {}).get("rag") or {}) if cfg is not None else {}
    emb = rag.get("embedding") or {}
    em_provider, em_model = embeddings.resolve_provider_model(emb.get("provider"),
                                                              emb.get("model"))
    detail = f"enrich {en_provider}/{en_model} · embeddings {em_provider}/{em_model}"
    if em_provider == "local":
        if _hf_cache_has(em_model):
            return Check("ok", "models", f"{detail} (local model cache warm)")
        return Check("warn", "models", f"{detail} (local model cache cold)",
                     "first `okf index`/search downloads ~30 MB")
    return Check("ok", "models", detail)


def _hf_cache_has(model: str) -> bool:
    """Is *model* already in a Hugging Face hub cache? (`models--org--name` dir)"""
    dirname = "models--" + model.replace("/", "--")
    roots = []
    if os.environ.get("HF_HOME"):
        roots += [os.path.join(os.environ["HF_HOME"], "hub"), os.environ["HF_HOME"]]
    if os.environ.get("HUGGINGFACE_HUB_CACHE"):
        roots.append(os.environ["HUGGINGFACE_HUB_CACHE"])
    roots.append(os.path.expanduser(os.path.join("~", ".cache", "huggingface", "hub")))
    return any(os.path.isdir(os.path.join(r, dirname)) for r in roots)
