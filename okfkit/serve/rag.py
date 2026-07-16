"""Semantic RAG over a built OKF vault: chunking, a numpy brute-force index, and
retrieve-then-answer.

- `chunk_notes` — one chunk per note; only oversized notes are split at ##/###
  headings. Generated link-list sections (e.g. "## Related Concepts",
  "## Appears in") are stripped before embedding.
- `Index` — build/refresh (incremental by content hash), save/load to
  `{base_dir}/.okf/embeddings.npz` + `chunks.json`, cosine `search`.
  Deliberately OUTSIDE the vault: `engine.build(clean=True)` rmtree's the vault.
- `ask` — retrieve top-k chunks, answer with an `enrich.Backend` chat model,
  citing notes as `[[basename|title]]` wikilinks.

numpy is lazy-imported (via `embeddings.require_numpy`) so the core kit stays
dependency-lean.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from okfkit.serve.embeddings import require_numpy

INDEX_DIR = ".okf"
EMBEDDINGS_FILE = "embeddings.npz"
CHUNKS_FILE = "chunks.json"

# a line that is nothing but a wikilink bullet — the shape of generated link lists
_link_item_re = re.compile(r"^\s*[-*]\s*\[\[[^\]]+\]\]\s*\.?\s*$")
_section_split_re = re.compile(r"(?m)^(?=#{2,6} )")     # any ##+ heading starts a section
_chunk_split_re = re.compile(r"(?m)^(?=#{2,3} )")       # oversized notes split at ##/###
_heading_re = re.compile(r"(?m)^#{2,3}\s+(.+?)\s*$")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
@dataclass
class Chunk:
    node_id: str                 # vault note basename (wikilink target)
    type: str
    title: str
    heading: str | None          # first ##/### heading of this chunk (None if whole note)
    text: str                    # the exact text that gets embedded (with context prefix)
    content_hash: str            # sha256[:16] of `text` — drives incremental refresh


def chunk_notes(notes, max_chars: int = 4000,
                exclude_types: tuple[str, ...] = ("Index", "Home")) -> list[Chunk]:
    """Turn `VaultNote`s (dict from `vault.load_vault` or iterable) into chunks.

    One chunk per note; notes whose stripped body exceeds *max_chars* are split
    at ##/### headings (greedy packing). Each chunk's embedded text is prefixed
    with "{type}: {title}\\n{description}\\n\\n{body}" for context.
    """
    if isinstance(notes, dict):
        notes = notes.values()
    excluded = {t.strip().lower() for t in (exclude_types or ()) if t}
    chunks: list[Chunk] = []
    for note in sorted(notes, key=lambda n: n.id):
        if note.type.lower() in excluded:
            continue
        body = _strip_link_sections(note.body).strip()
        prefix = f"{note.type}: {note.title}" if note.type else note.title
        if note.description:
            prefix += f"\n{note.description}"
        pieces = ([body] if len(prefix) + len(body) + 2 <= max_chars
                  else _split_at_headings(body, max_chars))
        for piece in pieces:
            piece = piece.strip()
            text = f"{prefix}\n\n{piece}" if piece else prefix
            m = _heading_re.search(piece)
            chunks.append(Chunk(
                node_id=note.id, type=note.type, title=note.title,
                heading=(m.group(1) if (m and len(pieces) > 1) else None),
                text=text,
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
            ))
    return chunks


def _strip_link_sections(body: str) -> str:
    """Drop ##+ sections whose entire content is wikilink bullets (generated
    link lists like "## Related Concepts" / "## Appears in") — pure noise for
    embeddings, and already captured by the graph."""
    parts = _section_split_re.split(body)
    if len(parts) <= 1:
        return body
    kept = [parts[0]]
    for seg in parts[1:]:
        lines = seg.splitlines()
        content = [ln for ln in lines[1:] if ln.strip()]
        if content and all(_link_item_re.match(ln) for ln in content):
            continue
        kept.append(seg)
    return "".join(kept)


def _split_at_headings(body: str, max_chars: int) -> list[str]:
    """Greedily pack ##/### sections into pieces of at most *max_chars*. A section
    that is itself oversized (e.g. a long headingless references list) falls back
    to splitting at blank-line paragraph boundaries; only a single oversized
    paragraph stays whole. Note: `chunk_notes` prepends the context prefix AFTER
    this split (only the whole-note path budgets for the prefix), so an emitted
    chunk's embedded text can be up to ``max_chars + len(prefix) + 2`` chars."""
    pieces = _greedy_pack(_chunk_split_re.split(body), max_chars)
    out = []
    for piece in pieces:
        if len(piece) <= max_chars:
            out.append(piece)
        else:
            out += _greedy_pack(re.split(r"(?<=\n)\s*\n", piece), max_chars)
    return out


def _greedy_pack(segments: list[str], max_chars: int) -> list[str]:
    pieces, cur, cur_len = [], [], 0
    for seg in segments:
        if cur and cur_len + len(seg) > max_chars:
            pieces.append("".join(cur))
            cur, cur_len = [], 0
        cur.append(seg)
        cur_len += len(seg)
    if cur:
        pieces.append("".join(cur))
    return pieces


# ---------------------------------------------------------------------------
# Index — numpy brute-force cosine over L2-normalized float32 vectors
# ---------------------------------------------------------------------------
@dataclass
class Hit:
    node_id: str
    type: str
    title: str
    heading: str | None
    text: str
    score: float                 # cosine similarity in [-1, 1]


class Index:
    """Embedding index persisted OUTSIDE the vault, under `{base_dir}/.okf/`."""

    def __init__(self, backend, chunks=None, vectors=None, meta=None, vault_path=None):
        self.backend = backend                      # EmbeddingBackend
        self.chunks: list[Chunk] = list(chunks or [])
        self.vectors = vectors                      # np.ndarray float32 L2-normalized, or None
        self.meta: dict = dict(meta or {})          # {provider, model, dim, vault_path, created}
        self.vault_path = vault_path or self.meta.get("vault_path")

    # -- persistence --------------------------------------------------------
    @staticmethod
    def paths(base_dir: str) -> tuple[str, str]:
        """(embeddings.npz path, chunks.json path) under `{base_dir}/.okf/`."""
        d = os.path.join(base_dir, INDEX_DIR)
        return os.path.join(d, EMBEDDINGS_FILE), os.path.join(d, CHUNKS_FILE)

    @classmethod
    def load(cls, base_dir: str, backend=None) -> "Index":
        """Load a saved index. With no *backend*, one matching the index header's
        {provider, model} is created (so queries can never mismatch); an explicit
        mismatched backend raises SystemExit."""
        np = require_numpy()
        npz_path, chunks_path = cls.paths(base_dir)
        if not (os.path.exists(npz_path) and os.path.exists(chunks_path)):
            raise FileNotFoundError(
                f"No index under {os.path.join(base_dir, INDEX_DIR)}. Run `okf index` first.")
        with open(chunks_path, encoding="utf-8") as fh:
            data = json.load(fh)
        meta = data.get("header") or {}
        chunks = [Chunk(**c) for c in data.get("chunks", [])]
        vectors = np.load(npz_path)["vectors"].astype(np.float32)
        if backend is None:
            from okfkit.serve.embeddings import make_embedder
            backend = make_embedder(provider=meta.get("provider"), model=meta.get("model"))
        idx = cls(backend, chunks=chunks, vectors=vectors, meta=meta)
        idx._check_compat()
        return idx

    def save(self, base_dir: str) -> tuple[str, str]:
        """Write embeddings.npz + chunks.json (with header) under `{base_dir}/.okf/`."""
        np = require_numpy()
        npz_path, chunks_path = self.paths(base_dir)
        os.makedirs(os.path.dirname(npz_path), exist_ok=True)
        dim = int(self.vectors.shape[1]) if self.vectors is not None and self.vectors.size else 0
        self.meta = {
            "provider": self.backend.provider,
            "model": self.backend.model,
            "dim": dim,
            "vault_path": self.vault_path,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        np.savez_compressed(npz_path, vectors=self.vectors.astype(np.float32))
        with open(chunks_path, "w", encoding="utf-8") as fh:
            json.dump({"header": self.meta, "chunks": [asdict(c) for c in self.chunks]},
                      fh, ensure_ascii=False, indent=1)
        return npz_path, chunks_path

    # -- building -----------------------------------------------------------
    def build(self, chunks, force=False, log=print) -> dict:
        """(Re)index *chunks*. Incremental: rows whose `content_hash` already
        exists are reused; only new/changed chunks are embedded; removed chunks
        are dropped. *force* re-embeds everything.

        Returns ``{"total": n, "embedded": n_new, "reused": n_reused}``.
        """
        np = require_numpy()
        chunks = list(chunks)
        old: dict[str, int] = {}
        if not force and self.vectors is not None and len(self.chunks):
            self._check_compat()
            old = {c.content_hash: i for i, c in enumerate(self.chunks)}
        rows: list = [None] * len(chunks)
        new_texts, new_positions = [], []
        for i, c in enumerate(chunks):
            if c.content_hash in old:
                rows[i] = self.vectors[old[c.content_hash]]
            else:
                new_texts.append(c.text)
                new_positions.append(i)
        if new_texts:
            log(f"  embedding {len(new_texts)}/{len(chunks)} chunk(s) "
                f"({self.backend.provider} · {self.backend.model}) ...")
            embedded = _normalize(self.backend.embed(new_texts, input_type="document"))
            for pos, vec in zip(new_positions, embedded):
                rows[pos] = vec
        self.chunks = chunks
        self.vectors = (np.vstack(rows).astype(np.float32) if rows
                        else np.zeros((0, 0), dtype=np.float32))
        return {"total": len(chunks), "embedded": len(new_texts),
                "reused": len(chunks) - len(new_texts)}

    # -- querying -----------------------------------------------------------
    def search(self, query: str, k: int = 8, types=None) -> list[Hit]:
        """Top-*k* notes by cosine similarity (best chunk per note; one Hit per
        note). *types* optionally restricts to those note types (case-insensitive)."""
        np = require_numpy()
        self._check_compat()
        if self.vectors is None or not len(self.chunks):
            return []
        q = _normalize(self.backend.embed([query], input_type="query"))[0]
        scores = self.vectors @ q
        allowed = {t.strip().lower() for t in types} if types else None
        hits: list[Hit] = []
        seen: set[str] = set()
        for i in np.argsort(-scores):
            c = self.chunks[int(i)]
            if allowed is not None and c.type.lower() not in allowed:
                continue
            if c.node_id in seen:
                continue
            seen.add(c.node_id)
            hits.append(Hit(node_id=c.node_id, type=c.type, title=c.title,
                            heading=c.heading, text=c.text, score=float(scores[int(i)])))
            if len(hits) >= k:
                break
        return hits

    def _check_compat(self):
        p, m = self.meta.get("provider"), self.meta.get("model")
        if p and (p != self.backend.provider or (m and m != self.backend.model)):
            raise SystemExit(
                f"Index was built with provider={p!r} model={m!r} but the current embedder is "
                f"provider={self.backend.provider!r} model={self.backend.model!r}. "
                f"Use matching --provider/--model, or rebuild with `okf index --force`.")


def _normalize(mat):
    """L2-normalize rows (zero rows left untouched); float32."""
    np = require_numpy()
    mat = np.asarray(mat, dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (mat / norms).astype(np.float32)


# ---------------------------------------------------------------------------
# Retrieve-then-answer
# ---------------------------------------------------------------------------
_ASK_SYSTEM = (
    "You answer questions about a knowledge wiki using ONLY the notes provided. "
    "Cite every note you draw on inline with its wikilink exactly as given, e.g. "
    "[[basename|Title]]. If the notes do not contain the answer, say so briefly "
    "instead of guessing."
)


def ask(question: str, index: Index, backend, k: int = 8, types=None) -> tuple[str, list[Hit]]:
    """Retrieve the top-*k* chunks for *question* and answer with *backend*
    (an `enrich.Backend` chat model, via its `text()` method). *types* optionally
    restricts retrieval to those note types (as in `Index.search`).

    Returns ``(answer, hits)``; the answer cites notes as [[basename|title]].
    """
    hits = index.search(question, k=k, types=types)
    if not hits:
        return "No relevant notes found in the index.", []
    blocks = []
    for h in hits:
        label = f"[[{h.node_id}|{h.title}]]"
        head = f" — {h.heading}" if h.heading else ""
        blocks.append(f"### Note {label}{head} (type: {h.type})\n\n{h.text}")
    user = (
        f"Question: {question}\n\n"
        "Notes retrieved from the wiki:\n\n" + "\n\n---\n\n".join(blocks) +
        "\n\nAnswer the question using only these notes. Cite the notes you use "
        "as [[basename|title]] wikilinks."
    )
    answer = backend.text(_ASK_SYSTEM, user, max_tokens=2000)
    return answer.strip(), hits
