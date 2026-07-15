"""Optional LLM enrichment: canonicalize a node type + write one-line descriptions.

Provider-flexible: Anthropic (`claude-sonnet-4-6`) or any OpenAI-compatible
endpoint such as OpenRouter (`qwen/qwen3.7-plus`). Writes `enrichment.json`,
which `engine.build()` consumes on the next build.

Output schema:
    {
      "canonical": {"clusters": [
          {"canonical_title", "canonical_id", "member_ids": [...], "aliases": [...], "definition"}
      ]},
      "descriptions": {node_id: "one-line description"}
    }
"""

from __future__ import annotations

import json
import os
import re
import sys

from okfkit import render

DEFAULT_MODELS = {"anthropic": "claude-sonnet-4-6", "openai": "qwen/qwen3.7-plus"}
DEFAULT_OPENAI_BASE_URL = "https://openrouter.ai/api/v1"


# ---------------------------------------------------------------------------
# Model backend — Anthropic OR any OpenAI-compatible endpoint (e.g. OpenRouter)
# ---------------------------------------------------------------------------
class Backend:
    def __init__(self, provider, model, api_key=None, base_url=None):
        self.provider = provider
        self.model = model
        if provider == "anthropic":
            from anthropic import Anthropic
            self.client = Anthropic(api_key=api_key) if api_key else Anthropic()
        elif provider == "openai":
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key, base_url=base_url or DEFAULT_OPENAI_BASE_URL)
        else:
            raise ValueError(f"unknown provider: {provider}")

    def json(self, system, user, max_tokens=16000):
        turns = [("user", user)]
        for _ in range(2):
            text = self._complete(system, turns, max_tokens)
            parsed = _extract_json(text)
            if parsed is not None:
                return parsed
            turns = [("user", user), ("assistant", text),
                     ("user", "That was not valid JSON. Reply with ONLY the JSON value, "
                              "no prose, no code fences.")]
        raise ValueError("Could not parse JSON from model after 2 attempts.")

    def _complete(self, system, turns, max_tokens):
        if self.provider == "anthropic":
            messages = [{"role": r, "content": c} for r, c in turns]
            with self.client.messages.stream(
                model=self.model, max_tokens=max_tokens, system=system,
                thinking={"type": "adaptive"}, messages=messages,
            ) as stream:
                msg = stream.get_final_message()
            return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        messages = [{"role": "system", "content": system}]
        messages += [{"role": r, "content": c} for r, c in turns]
        kwargs = dict(model=self.model, max_tokens=max_tokens, messages=messages)
        try:
            resp = self.client.chat.completions.create(
                response_format={"type": "json_object"}, **kwargs)
        except Exception:
            resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""


def _extract_json(text: str):
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = text.find(opener), text.rfind(closer)
        if 0 <= i < j:
            try:
                return json.loads(text[i:j + 1])
            except json.JSONDecodeError:
                pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------
def make_backend(provider=None, model=None, base_url=None) -> Backend:
    provider = provider or _autodetect_provider()
    model = model or DEFAULT_MODELS[provider]
    api_key = None
    if provider == "openai":
        api_key = (os.environ.get("OPENROUTER_API_KEY")
                   or os.environ.get("OPENAI_API_KEY") or "").strip()
        if not api_key:
            raise SystemExit("Set OPENROUTER_API_KEY (or OPENAI_API_KEY) for the openai provider.")
        if "..." in api_key or api_key.lower() in ("sk-or-", "your_key"):
            raise SystemExit(f"OPENROUTER_API_KEY is a placeholder ({api_key!r}), not a real key.")
    try:
        return Backend(provider, model, api_key=api_key, base_url=base_url)
    except ImportError:
        pkg = "anthropic" if provider == "anthropic" else "openai"
        raise SystemExit(f"The '{pkg}' package is required: pip install {pkg}")


def _autodetect_provider() -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "anthropic"


# ---------------------------------------------------------------------------
# Canonicalization (batched, with a no-loss fallback)
# ---------------------------------------------------------------------------
_CANON_SYSTEM = (
    "You are a knowledge engineer curating a concept index for a wiki. You merge "
    "duplicate/near-duplicate node titles into canonical concepts and write crisp definitions."
)


def _canon_batch(backend, chunk):
    user = f"""Below are {len(chunk)} node titles (each with a stable id). Many are duplicates,
synonyms, or near-duplicates that should be merged (e.g. "health security" and "Global health
security"). Produce canonical concepts. Merge where titles denote the same concept; do NOT merge
genuinely distinct concepts.

Return ONLY a JSON object of this exact shape (no prose, no code fences):
{{
  "concept_clusters": [
    {{
      "canonical_title": "Clearest standard name",
      "aliases": ["merged variant titles"],
      "member_ids": ["<every input id, verbatim, that maps to this concept>"],
      "definition": "One or two sentences defining the concept."
    }}
  ]
}}

Rules:
- Every input id must appear in exactly one cluster's "member_ids" (verbatim).
- A title with no duplicates is still its own cluster (member_ids = [that one id]).
- "definition" must be 1-2 sentences, factual, no citations.

Input nodes:
{json.dumps([{"id": c["id"], "title": c["title"]} for c in chunk], ensure_ascii=False)}
"""
    result = backend.json(_CANON_SYSTEM, user, max_tokens=16000)
    clusters = result.get("concept_clusters", []) if isinstance(result, dict) else result
    out = []
    for cl in clusters or []:
        title = (cl.get("canonical_title") or "").strip()
        if not title:
            continue
        out.append({
            "canonical_title": title,
            "aliases": [a.strip() for a in cl.get("aliases", []) if a and a.strip()],
            "member_ids": [m for m in cl.get("member_ids", []) if m],
            "definition": (cl.get("definition") or "").strip(),
        })
    return out


def canonicalize(backend, nodes, batch_size=100, log=print):
    items = sorted(({"id": n.id, "title": n.title} for n in nodes),
                   key=lambda x: x["title"].lower())
    valid_ids = {n.id for n in nodes}
    raw = []
    for start in range(0, len(items), batch_size):
        chunk = items[start:start + batch_size]
        try:
            raw += _canon_batch(backend, chunk)
        except ValueError as e:   # parse failure only — auth/API errors propagate
            log(f"    !! batch {start}-{start + len(chunk)} unparseable ({e}); keeping unmerged")
            raw += [{"canonical_title": c["title"], "aliases": [],
                     "member_ids": [c["id"]], "definition": ""} for c in chunk]
        log(f"    canonicalized {min(start + batch_size, len(items))}/{len(items)}")

    # merge clusters that share a canonical id, and keep only valid member ids
    merged = {}
    for cl in raw:
        cid = render.slug(cl["canonical_title"])
        m = merged.setdefault(cid, {"canonical_title": cl["canonical_title"], "canonical_id": cid,
                                    "aliases": set(), "member_ids": [], "definition": ""})
        m["aliases"].update(cl["aliases"])
        m["member_ids"].extend(x for x in cl["member_ids"] if x in valid_ids)
        if not m["definition"] and cl["definition"]:
            m["definition"] = cl["definition"]
    return [{"canonical_title": m["canonical_title"], "canonical_id": m["canonical_id"],
             "aliases": sorted(m["aliases"]), "member_ids": _dedup(m["member_ids"]),
             "definition": m["definition"]} for m in merged.values() if m["member_ids"]]


def _dedup(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


# ---------------------------------------------------------------------------
# Descriptions (batched, best-effort)
# ---------------------------------------------------------------------------
def describe(backend, nodes, batch=25, log=print):
    system = ("You write concise, informative one-sentence descriptions (max ~25 words) for "
              "entries in a knowledge wiki. No citations, no fluff.")
    items = {n.id: f"[{n.type}] {n.title}: {_snippet(n.body)}" for n in nodes}
    keys = list(items)
    out = {}
    for start in range(0, len(keys), batch):
        chunk = keys[start:start + batch]
        payload = [{"id": k, "context": items[k]} for k in chunk]
        user = ("Write a one-sentence description for each entry below. Return ONLY a JSON object "
                f"mapping each id to its description string.\n\n{json.dumps(payload, ensure_ascii=False)}")
        try:
            res = backend.json(system, user, max_tokens=8000)
            if isinstance(res, dict):
                for k in chunk:
                    if isinstance(res.get(k), str):
                        out[k] = res[k].strip()
            log(f"    described {min(start + batch, len(keys))}/{len(keys)}")
        except ValueError as e:
            log(f"    !! describe batch {start}-{start + batch} unparseable: {e}")
    return out


def _snippet(body: str, n: int = 400) -> str:
    return re.sub(r"\s+", " ", re.sub(r"^#.*$", "", body or "", flags=re.M)).strip()[:n]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run(nodes, out_path, *, canonicalize_type="", describe_types=None,
        provider=None, model=None, base_url=None, log=print):
    nodes = list(nodes)
    if not canonicalize_type and not (describe_types or []):
        raise SystemExit(
            "Nothing to enrich. Set `enrich.canonicalize_type` and/or `enrich.describe_types` "
            "in okf.config.yaml (e.g. canonicalize_type: Concept, describe_types: [Chapter])."
        )
    backend = make_backend(provider, model, base_url)
    log(f"Provider: {backend.provider} · model: {backend.model}")

    payload = {"canonical": {"clusters": []}, "descriptions": {}}

    if canonicalize_type:
        subset = [n for n in nodes if n.type == canonicalize_type]
        log(f"[canonicalize] {len(subset)} {canonicalize_type!r} nodes ...")
        clusters = canonicalize(backend, subset, log=log)
        payload["canonical"]["clusters"] = clusters
        absorbed = sum(len(c["member_ids"]) for c in clusters)
        log(f"    -> {len(clusters)} canonical (absorbed {absorbed})")

    for t in (describe_types or []):
        subset = [n for n in nodes if n.type == t]
        if not subset:
            continue
        log(f"[describe] {len(subset)} {t!r} nodes ...")
        payload["descriptions"].update(describe(backend, subset, log=log))

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    log(f"Wrote {out_path}: {len(payload['canonical']['clusters'])} clusters, "
        f"{len(payload['descriptions'])} descriptions.")
    return payload
