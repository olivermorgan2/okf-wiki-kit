"""Opt-in integration tests against a REAL built OKF vault.

These complement the fake-based unit tests (tests/test_serve_rag.py,
tests/test_serve_mcp.py) by exercising `load_vault`, `VaultService`, and — when
an embedding provider is available — a real `rag.Index` over a full-size vault.
Every assertion is a behavioral invariant, not a content assertion, so the
suite must pass on ANY built OKF vault.

Everything here is gated and skips (never errors) when prerequisites are
missing, so plain CI runs show the whole module as skipped.

Usage
-----
Point ``OKF_TEST_VAULT`` at a *built* vault — the output directory that
contains the per-type note folders (i.e. what `okf build` writes, the path
your `okf.config.yaml` calls ``output``)::

    OKF_TEST_VAULT=/abs/path/to/vault python3 -m pytest tests/test_integration.py -q

Layered skips:

* **Graph-only tests** (load_vault / vault_info / neighbors / get_note /
  did-you-mean) need only ``OKF_TEST_VAULT``.
* **Embedding tests** (Index build + search / save-load round trip /
  staleness) additionally need an embedding provider, chosen with
  ``OKF_TEST_PROVIDER`` (default ``local``):

  - ``local``  — needs ``model2vec`` + ``numpy`` importable
    (``pip install 'okf-wiki-kit[local-embeddings]'``); downloads the ~30 MB
    model2vec model on first use (cached by huggingface afterwards).
  - ``voyage`` — needs ``VOYAGE_API_KEY`` set (and the ``voyageai`` package).
  - ``openai`` — needs ``OPENAI_API_KEY`` set (and the ``openai`` package).

  Hosted-provider tests make real (billable) embedding API calls.

The embedding index is always built into a pytest tmp dir — the real vault
and any real ``.okf/`` sidecar next to it are never written to. The staleness
test briefly bumps one note file's mtime with ``os.utime`` and restores it;
note contents are never modified.

All tests carry the ``integration`` marker (registered in tests/conftest.py),
so they can be selected/deselected with ``-m integration`` / ``-m "not
integration"``.
"""

import os
import random
import time
from collections import Counter

import pytest

from okfkit.serve import Index, chunk_notes, load_vault
from okfkit.serve import vault as vaultmod
from okfkit.serve.mcp import VaultService

EXCLUDE = ("Index", "Home")

VAULT = os.environ.get("OKF_TEST_VAULT", "").strip()
PROVIDER = (os.environ.get("OKF_TEST_PROVIDER") or "local").strip().lower()
_KEY_ENVS = {"voyage": "VOYAGE_API_KEY", "openai": "OPENAI_API_KEY"}

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not VAULT,
        reason="integration tests are opt-in: set OKF_TEST_VAULT to the path "
               "of a built OKF vault (see the module docstring)"),
]


def _embedding_skip_reason():
    """None if embedding tests can run, else a human-readable skip reason."""
    try:
        import numpy  # noqa: F401
    except ImportError:
        return "numpy is required for embedding tests (pip install 'okf-wiki-kit[rag]')"
    if PROVIDER == "local":
        try:
            import model2vec  # noqa: F401
        except ImportError:
            return ("OKF_TEST_PROVIDER=local needs model2vec "
                    "(pip install 'okf-wiki-kit[local-embeddings]')")
    elif PROVIDER in _KEY_ENVS:
        if not (os.environ.get(_KEY_ENVS[PROVIDER]) or "").strip():
            return (f"{_KEY_ENVS[PROVIDER]} is not set "
                    f"(required for OKF_TEST_PROVIDER={PROVIDER})")
    else:
        return (f"unknown OKF_TEST_PROVIDER {PROVIDER!r} "
                "(use 'local', 'voyage' or 'openai')")
    return None


_EMBED_SKIP = _embedding_skip_reason()
needs_embeddings = pytest.mark.skipif(
    _EMBED_SKIP is not None, reason=_EMBED_SKIP or "embedding prerequisites met")


# ---------------------------------------------------------------------------
# Fixtures (module-scoped: the real vault is loaded / indexed once)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def all_notes():
    """Every note in the vault, including generated Index/Home pages."""
    return load_vault(VAULT)


@pytest.fixture(scope="module")
def notes(all_notes):
    """Content notes only (same exclusion the service and chunker use)."""
    excluded = {t.lower() for t in EXCLUDE}
    return {nid: n for nid, n in all_notes.items() if n.type.lower() not in excluded}


@pytest.fixture(scope="module")
def service():
    return VaultService(VAULT, use_rag=False, exclude_types=EXCLUDE)


@pytest.fixture(scope="module")
def index_base_dir(tmp_path_factory):
    """A tmp base_dir for the index sidecar — NEVER the real vault's .okf."""
    return str(tmp_path_factory.mktemp("okf-integration-index"))


@pytest.fixture(scope="module")
def built_index(index_base_dir, notes):
    """A real Index over the vault, built with the selected provider and
    saved under the tmp base_dir."""
    from okfkit.serve.embeddings import make_embedder
    backend = make_embedder(provider=PROVIDER)
    idx = Index(backend, vault_path=os.path.abspath(os.path.expanduser(VAULT)))
    stats = idx.build(chunk_notes(notes, exclude_types=EXCLUDE), log=lambda *a: None)
    assert stats["total"] >= 1 and stats["embedded"] >= 1
    idx.save(index_base_dir)
    return idx


# ---------------------------------------------------------------------------
# Layer 1: graph-only (needs just OKF_TEST_VAULT)
# ---------------------------------------------------------------------------
def test_load_vault_loads_sound_structure(all_notes, notes):
    assert len(notes) >= 1, f"no content notes loaded from {VAULT}"
    for n in notes.values():
        assert n.type, f"{n.id}: built vault note has no frontmatter type"
        assert n.title, f"{n.id}: built vault note has no title"
        assert os.path.isfile(n.path)
        assert n.id  # ids are wikilink targets and must be non-empty

    # Wikilink targets in note bodies/frontmatter should mostly resolve to
    # loaded ids. A few dangling links are tolerated (any real vault may have
    # some); a majority unresolved means the vault structure is broken.
    targets = [t for n in notes.values() for t in vaultmod.outgoing(n)]
    if targets:
        resolved = sum(1 for t in targets if t in all_notes)
        rate = resolved / len(targets)
        assert rate >= 0.5, (
            f"only {resolved}/{len(targets)} ({rate:.0%}) wikilink targets "
            "resolve to loaded note ids")


def test_vault_info_counts_match_load_vault(service, notes):
    info = service.vault_info()
    assert info["vault_path"] == service.vault_path
    assert info["total"] == len(notes)
    assert sum(info["types"].values()) == len(notes)
    assert info["types"] == dict(Counter(n.type or "(untyped)" for n in notes.values()))
    assert info["tags"] == dict(Counter(t for n in notes.values() for t in n.tags))
    assert info["search_enabled"] is False          # service built with use_rag=False


def test_neighbors_entries_are_valid_and_symmetric(service):
    linked = [nid for nid in sorted(service.notes)
              if vaultmod.outgoing(service.notes[nid])]
    if not linked:
        pytest.skip("vault has no notes with outgoing wikilinks")

    round_tripped = 0
    for nid in linked[:25]:                         # bound the work on huge vaults
        res = service.neighbors(nid)
        assert res["id"] == nid and "error" not in res
        for ref in res["outgoing"]:
            assert set(ref) == {"id", "type", "title"} and ref["id"]
            if ref["id"] in service.notes and ref["id"] != nid:
                # every resolvable outgoing edge appears as the target's backlink
                back = service.neighbors(ref["id"], direction="backlinks")["backlinks"]
                assert nid in {r["id"] for r in back}, (
                    f"{nid} -> {ref['id']} edge missing from target's backlinks")
                round_tripped += 1
        for ref in res["backlinks"]:                # backlinks only cite known notes
            assert ref["id"] in service.notes
    if round_tripped == 0:
        pytest.skip("no wikilink edges between loaded notes to round-trip")


def test_get_note_round_trips_title_and_body(service):
    nid = sorted(service.notes)[0]
    note = service.notes[nid]
    res = service.get_note(nid)
    assert res["id"] == nid
    assert res["title"] == note.title and res["type"] == note.type
    assert res["body_length"] == len(note.body)
    assert res["body"] == note.body[:service.max_note_chars]
    if res["truncated"]:
        assert res["next_offset"] == service.max_note_chars
    else:
        assert res["body"] == note.body and res["next_offset"] is None


def test_missing_id_offers_did_you_mean(service):
    real = max(service.notes, key=len)              # longest id: best fuzzy signal
    for typo in (real + "x", real[:-1] + ("q" if real.endswith("x") else "x")):
        if typo not in service.notes:
            break
    else:
        pytest.skip("could not construct an id missing from the vault")

    for res in (service.get_note(typo), service.neighbors(typo)):
        assert "error" in res and typo in res["error"]
        assert real in res["did_you_mean"]


# ---------------------------------------------------------------------------
# Layer 2: embeddings (additionally needs a provider — see module docstring)
# ---------------------------------------------------------------------------
@needs_embeddings
def test_search_returns_ranked_hits_with_sane_scores(built_index, index_base_dir):
    # exercises the full lazy path: VaultService -> Index.load -> make_embedder
    svc = VaultService(VAULT, base_dir=index_base_dir, use_rag=True,
                       exclude_types=EXCLUDE)
    hits = svc.search("What are the main themes and ideas in these notes?", k=5)
    assert hits and len(hits) <= 5
    scores = [h["score"] for h in hits]
    assert all(-1.0001 <= s <= 1.0001 for s in scores)   # cosine similarity range
    assert scores == sorted(scores, reverse=True)        # ranked descending
    for h in hits:
        assert h["id"] in svc.notes
        assert h["title"] == svc.notes[h["id"]].title


@needs_embeddings
def test_exact_title_query_ranks_note_in_top5(built_index, notes):
    # Weak but real relevance signal that must hold on any vault: querying a
    # note's exact title should rank that note among the top 5. Prefer
    # multi-word titles (single common words can legitimately be ambiguous).
    pool = sorted(notes.values(), key=lambda n: n.id)
    multi = [n for n in pool if len(n.title.split()) >= 2]
    note = random.Random(20260716).choice(multi or pool)
    hits = built_index.search(note.title, k=5)
    assert note.id in [h.node_id for h in hits], (
        f"searching the exact title {note.title!r} did not rank {note.id!r} "
        f"in the top 5 (got {[h.node_id for h in hits]})")


@needs_embeddings
def test_index_save_load_round_trip(built_index, index_base_dir):
    import numpy as np
    # Index.load runs _check_compat against the supplied backend
    loaded = Index.load(index_base_dir, backend=built_index.backend)
    assert loaded.meta["provider"] == built_index.backend.provider
    assert loaded.meta["model"] == built_index.backend.model
    assert loaded.meta["vault_path"] == os.path.abspath(os.path.expanduser(VAULT))
    assert loaded.chunks == built_index.chunks
    assert np.allclose(loaded.vectors, built_index.vectors)
    loaded._check_compat()                               # explicit, for clarity


@needs_embeddings
def test_index_staleness_flips_after_touching_a_note(built_index, index_base_dir, notes):
    from okfkit import freshness
    vault_abs = os.path.abspath(os.path.expanduser(VAULT))
    # the index was built after every note file was written -> fresh
    assert freshness.index_staleness(index_base_dir, vault_abs) is False

    victim = notes[sorted(notes)[0]].path
    st = os.stat(victim)
    try:
        # bump mtime safely past the index's second-resolution timestamp
        os.utime(victim, (st.st_atime, time.time() + 5))
        assert freshness.index_staleness(index_base_dir, vault_abs) is True
    finally:
        os.utime(victim, (st.st_atime, st.st_mtime))     # restore the real vault
    assert freshness.index_staleness(index_base_dir, vault_abs) is False
