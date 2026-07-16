"""Offline tests for Phase 8 (serve/mcp): the MCP-free `VaultService` layer plus
one in-process MCP round trip.

The vault is built for real with `engine.build` into tmp_path (as in
test_engine.py) and read back through `VaultService`. Semantic-search tests
reuse the deterministic `FakeEmbedder` approach from test_serve_rag.py (numpy
required); the round-trip test additionally needs the optional `mcp` SDK and is
skipped without it. No network, no models, no subprocesses.
"""

import hashlib
import json
import re
import types

import pytest

from okfkit import engine
from okfkit.model import Link, Node
from okfkit.serve import vault as vaultmod
from okfkit.serve.mcp import SearchUnavailable, VaultService

EXCLUDE = ("Index", "Home")


# ---------------------------------------------------------------------------
# Deterministic offline embedder (same approach as tests/test_serve_rag.py)
# ---------------------------------------------------------------------------
class FakeEmbedder:
    """Hashed bag-of-words vectors (md5-stable): shared vocabulary => higher
    cosine similarity. numpy is imported lazily so importing this module does
    not require the `rag` extra."""

    dim = 64

    def __init__(self, provider="fake", model="bow-64"):
        self.provider = provider
        self.model = model

    def embed(self, texts, input_type=None, batch_size=128):
        import numpy as np
        texts = list(texts)
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        rows = []
        for t in texts:
            v = np.zeros(self.dim, dtype=np.float32)
            for word in re.findall(r"[a-z0-9]+", t.lower()):
                h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
                v[h % self.dim] += 1.0
            rows.append(v)
        return np.asarray(rows, dtype=np.float32)


# ---------------------------------------------------------------------------
# Fixture vault (node pattern from test_engine.py)
# ---------------------------------------------------------------------------
def _nodes():
    return [
        # "a" links out both ways: a body wikilink AND a rendered link-list section
        Node(id="a", type="Topic", title="Alpha",
             body="Alpha discusses [[photosynthesis]] directly in prose.",
             links=[Link("b", rel="related", section="See also")]),
        Node(id="b", type="Topic", title="Beta", body="Beta body.",
             tags=["water"]),
        Node(id="photosynthesis", type="Concept", title="Photosynthesis",
             body="Chlorophyll pigments capture sunlight energy. Photosynthesis "
                  "converts carbon dioxide and water into glucose and oxygen.",
             frontmatter={"description":
                          "How plants turn sunlight into chemical energy."}),
        Node(id="volcano", type="Topic", title="Volcano",
             body="Magma rises through the crust and erupts as lava. Volcanic "
                  "ash and pyroclastic flows reshape the landscape.",
             tags=["geology"]),
        Node(id="glacier", type="Topic", title="Glacier",
             body="Compacted snow forms slow-moving rivers of ice. Glaciers "
                  "carve valleys and deposit moraines as they retreat.",
             tags=["geology", "water"]),
    ]


def _service(tmp_path, **kw):
    """Build the fixture vault under tmp_path/vault and wrap it in a service."""
    vault = str(tmp_path / "vault")
    assert engine.build(_nodes(), vault).ok
    kw.setdefault("use_rag", False)
    return VaultService(vault, exclude_types=EXCLUDE, **kw)


def _fake_index(tmp_path, vault, monkeypatch):
    """Persist a FakeEmbedder index under {tmp_path}/.okf (the service's
    base_dir for a vault at tmp_path/vault) and make the lazy
    `Index.load(base_dir)` path resolve the 'fake' provider to a FakeEmbedder."""
    from okfkit.serve import chunk_notes, load_vault
    from okfkit.serve import embeddings
    from okfkit.serve.rag import Index

    idx = Index(FakeEmbedder(), vault_path=vault)
    idx.build(chunk_notes(load_vault(vault, exclude_types=EXCLUDE)),
              log=lambda *a: None)
    idx.save(str(tmp_path))
    monkeypatch.setattr(
        embeddings, "make_embedder",
        lambda provider=None, model=None, base_url=None: FakeEmbedder())


# ---------------------------------------------------------------------------
# okf_get_note: backlinks from body wikilinks AND link-list sections
# ---------------------------------------------------------------------------
def test_get_note_backlinks_from_body_and_link_sections(tmp_path):
    svc = _service(tmp_path)
    # sanity: the Link really was rendered as a "## See also" link-list section
    assert "## See also" in svc.notes["a"].body
    assert "[[b|Beta]]" in svc.notes["a"].body

    # body-wikilink edge: a's prose [[photosynthesis]] -> backlink on the concept
    photo = svc.get_note("photosynthesis")
    assert [r["id"] for r in photo["backlinks"]] == ["a"]
    assert photo["backlinks"][0] == {"id": "a", "type": "Topic", "title": "Alpha"}

    # link-list-section edge: a's "## See also" [[b|Beta]] -> backlink on b
    beta = svc.get_note("b")
    assert [r["id"] for r in beta["backlinks"]] == ["a"]

    # and a's outgoing covers both kinds of edge
    alpha = svc.get_note("a")
    assert {r["id"] for r in alpha["outgoing"]} == {"photosynthesis", "b"}
    assert alpha["backlinks"] == []
    assert alpha["truncated"] is False and alpha["next_offset"] is None


# ---------------------------------------------------------------------------
# okf_list_notes: pagination + type/tag filters
# ---------------------------------------------------------------------------
def test_list_notes_paginates_with_limit_and_cursor(tmp_path):
    svc = _service(tmp_path)
    seen, cursor, pages = [], None, 0
    while True:
        page = svc.list_notes(limit=2, cursor=cursor)
        assert page["total"] == 5
        assert 1 <= len(page["rows"]) <= 2
        seen += [r["id"] for r in page["rows"]]
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert pages == 3                              # 2 + 2 + 1
    assert seen == sorted(svc.notes)               # every note exactly once, id-sorted
    assert seen == ["a", "b", "glacier", "photosynthesis", "volcano"]


def test_list_notes_filters_by_type_and_tag(tmp_path):
    svc = _service(tmp_path)
    topics = svc.list_notes(type="topic")          # case-insensitive
    assert [r["id"] for r in topics["rows"]] == ["a", "b", "glacier", "volcano"]
    assert topics["total"] == 4 and topics["next_cursor"] is None

    water = svc.list_notes(tag="Water")            # case-insensitive
    assert [r["id"] for r in water["rows"]] == ["b", "glacier"]

    both = svc.list_notes(type="Topic", tag="geology")
    assert [r["id"] for r in both["rows"]] == ["glacier", "volcano"]

    # filtered results paginate too, with total = filtered count
    first = svc.list_notes(type="Topic", limit=3)
    assert first["total"] == 4 and first["next_cursor"] == "3"
    rest = svc.list_notes(type="Topic", limit=3, cursor=first["next_cursor"])
    assert [r["id"] for r in rest["rows"]] == ["volcano"]
    assert rest["next_cursor"] is None


# ---------------------------------------------------------------------------
# okf_neighbors: mirrors the vault's actual link graph
# ---------------------------------------------------------------------------
def test_neighbors_match_vault_links(tmp_path):
    svc = _service(tmp_path)

    both = svc.neighbors("a")
    assert both["id"] == "a" and both["title"] == "Alpha"
    # exactly what serve.vault computes from the files on disk
    assert [r["id"] for r in both["outgoing"]] == vaultmod.outgoing(svc.notes["a"])
    assert {r["id"] for r in both["outgoing"]} == {"photosynthesis", "b"}
    assert both["backlinks"] == []                 # nothing links to a

    out_only = svc.neighbors("b", direction="outgoing")
    assert "backlinks" not in out_only and out_only["outgoing"] == []

    back_only = svc.neighbors("photosynthesis", direction="backlinks")
    assert "outgoing" not in back_only
    assert [r["id"] for r in back_only["backlinks"]] == ["a"]

    # whole-graph consistency: every outgoing edge to a known note shows up
    # as the target's backlink, and vice versa
    for nid in svc.notes:
        for ref in svc.neighbors(nid, direction="outgoing")["outgoing"]:
            if ref["id"] in svc.notes and ref["id"] != nid:
                back = svc.neighbors(ref["id"], direction="backlinks")["backlinks"]
                assert nid in {r["id"] for r in back}

    missing = svc.neighbors("nope")
    assert "error" in missing and "did_you_mean" in missing


# ---------------------------------------------------------------------------
# okf_search: actionable error without an index; ranked hits with one
# ---------------------------------------------------------------------------
def test_search_without_index_raises_run_okf_index(tmp_path):
    pytest.importorskip("numpy")                   # Index.load needs it pre-check
    svc = _service(tmp_path, use_rag=True)         # no index was ever built
    with pytest.raises(SearchUnavailable, match=r"okf index"):
        svc.search("anything")
    # graph tools keep working regardless
    assert svc.get_note("a")["id"] == "a"


def test_search_disabled_with_no_rag(tmp_path):
    svc = _service(tmp_path, use_rag=False)
    with pytest.raises(SearchUnavailable, match=r"--no-rag"):
        svc.search("anything")


def _hosted_index(tmp_path, vault, provider, model):
    """Persist a FakeEmbedder index whose header claims a hosted provider, so the
    lazy `Index.load(base_dir)` calls the real `make_embedder(provider, model)`."""
    from okfkit.serve import chunk_notes, load_vault
    from okfkit.serve.rag import Index

    idx = Index(FakeEmbedder(provider=provider, model=model), vault_path=vault)
    idx.build(chunk_notes(load_vault(vault, exclude_types=EXCLUDE)),
              log=lambda *a: None)
    idx.save(str(tmp_path))


@pytest.mark.parametrize("provider,model,var", [
    ("voyage", "voyage-3.5-lite", "VOYAGE_API_KEY"),
    ("openai", "text-embedding-3-small", "OPENAI_API_KEY"),
])
def test_search_missing_hosted_key_names_the_env_var(tmp_path, monkeypatch,
                                                     provider, model, var):
    """Field report §3: an MCP-spawned server inherits no shell env, so a
    hosted-provider index with the key unset must say WHICH variable is missing
    and why — not the generic 'Could not load the semantic index: ...'."""
    pytest.importorskip("numpy")
    monkeypatch.setenv("OKF_NONINTERACTIVE", "1")   # the key prompt must not fire
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    svc = _service(tmp_path, use_rag=True)
    _hosted_index(tmp_path, svc.vault_path, provider, model)

    with pytest.raises(SearchUnavailable) as ei:
        svc.search("anything")
    msg = str(ei.value)
    assert f"'{provider}' embedding provider needs {var}" in msg
    assert "MCP servers do not inherit your shell env" in msg
    assert ".env" in msg and "okf doctor" in msg
    assert "Could not load the semantic index" not in msg
    # graph tools keep working key-less
    assert svc.get_note("a")["id"] == "a"
    assert svc.neighbors("a")["id"] == "a"
    assert svc.vault_info()["total"] == 5


def test_search_other_load_failure_keeps_generic_message(tmp_path, monkeypatch):
    """A SystemExit that is NOT a missing hosted key (missing numpy/SDK, ...)
    keeps the generic wrapper with the original detail."""
    pytest.importorskip("numpy")
    from okfkit.serve import embeddings

    svc = _service(tmp_path, use_rag=True)
    _hosted_index(tmp_path, svc.vault_path, "local", "minishlab/potion-base-8M")

    def boom(provider=None, model=None, base_url=None):
        raise SystemExit("Missing package(s) for the 'local' embedding provider: "
                         "pip install model2vec numpy")

    monkeypatch.setattr(embeddings, "make_embedder", boom)
    with pytest.raises(SearchUnavailable,
                       match=r"^Could not load the semantic index: "
                             r"Missing package\(s\)"):
        svc.search("anything")


def test_search_with_index_returns_ranked_hits(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    svc = _service(tmp_path, use_rag=True)
    _fake_index(tmp_path, svc.vault_path, monkeypatch)

    hits = svc.search("How does chlorophyll capture sunlight for photosynthesis?", k=3)
    assert hits and hits[0]["id"] == "photosynthesis"
    assert hits[0]["type"] == "Concept"
    assert hits[0]["description"] == "How plants turn sunlight into chemical energy."
    assert "chlorophyll" in hits[0]["snippet"].lower()
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)  # ranked
    assert len(hits) <= 3

    hits = svc.search("magma lava eruption volcanic ash", k=2, types=["topic"])
    assert hits[0]["id"] == "volcano"
    assert all(h["type"] == "Topic" for h in hits) and len(hits) <= 2


# ---------------------------------------------------------------------------
# okf_get_note: oversized bodies are windowed (truncated: true)
# ---------------------------------------------------------------------------
def test_get_note_truncates_oversized_body(tmp_path):
    body = " ".join(f"word{i:03d}" for i in range(120))     # ~960 chars
    assert engine.build([Node(id="big", type="Topic", title="Big", body=body)],
                        str(tmp_path / "vault")).ok
    svc = VaultService(str(tmp_path / "vault"), use_rag=False,
                       exclude_types=EXCLUDE, max_note_chars=150)
    full = svc.notes["big"].body                   # as read back from disk

    first = svc.get_note("big")
    assert first["truncated"] is True
    assert first["body"] == full[:150]
    assert first["body_length"] == len(full) and first["offset"] == 0
    assert first["next_offset"] == 150
    assert "offset=150" in first["hint"]

    # windows walk the whole body and reassemble exactly
    parts, page = [], first
    while True:
        parts.append(page["body"])
        if not page["truncated"]:
            assert page["next_offset"] is None and "hint" not in page
            break
        page = svc.get_note("big", offset=page["next_offset"])
    assert "".join(parts) == full


# ---------------------------------------------------------------------------
# run(): transport threading at the FastMCP boundary (no server ever starts)
# ---------------------------------------------------------------------------
class _FakeFastMCP:
    """Stands in for FastMCP: records .run() calls; .settings mirrors the SDK's
    mutable Settings(host=..., port=...) defaults."""

    def __init__(self):
        self.settings = types.SimpleNamespace(host="127.0.0.1", port=8000)
        self.run_calls = []

    def run(self, *args, **kwargs):
        self.run_calls.append((args, kwargs))


def _fake_server(monkeypatch):
    from okfkit.serve import mcp as mcpmod
    fake = _FakeFastMCP()
    monkeypatch.setattr(mcpmod, "create_server",
                        lambda target, use_rag=True: fake)
    return mcpmod, fake


def test_run_defaults_to_bare_stdio_run(monkeypatch):
    mcpmod, fake = _fake_server(monkeypatch)
    assert mcpmod.run("ignored-vault") == 0
    assert fake.run_calls == [((), {})]            # byte-identical stdio call
    assert (fake.settings.host, fake.settings.port) == ("127.0.0.1", 8000)


def test_run_http_sets_host_port_and_streamable_http(monkeypatch):
    mcpmod, fake = _fake_server(monkeypatch)
    assert mcpmod.run("ignored-vault", transport="http",
                      host="0.0.0.0", port=9321) == 0
    assert fake.run_calls == [((), {"transport": "streamable-http"})]
    assert (fake.settings.host, fake.settings.port) == ("0.0.0.0", 9321)


def test_run_stdio_ignores_host_port(monkeypatch):
    mcpmod, fake = _fake_server(monkeypatch)
    assert mcpmod.run("ignored-vault", transport="stdio",
                      host="0.0.0.0", port=9321) == 0
    assert fake.run_calls == [((), {})]
    assert (fake.settings.host, fake.settings.port) == ("127.0.0.1", 8000)


# ---------------------------------------------------------------------------
# In-process MCP round trip (needs the optional `mcp` SDK)
# ---------------------------------------------------------------------------
def test_mcp_in_process_round_trip(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    pytest.importorskip("mcp")
    import anyio                                   # dependency of mcp
    from mcp.shared.memory import (
        create_connected_server_and_client_session as client_session)
    from okfkit.serve.mcp import create_server

    vault = str(tmp_path / "vault")
    assert engine.build(_nodes(), vault).ok
    _fake_index(tmp_path, vault, monkeypatch)

    server = create_server(vault, use_rag=True)    # bare-path form, no config

    async def main():
        async with client_session(server._mcp_server) as session:
            listed = (await session.list_tools()).tools
            assert {t.name for t in listed} == {
                "okf_search", "okf_get_note", "okf_list_notes",
                "okf_neighbors", "okf_vault_info"}
            assert all(t.annotations and t.annotations.readOnlyHint
                       for t in listed)

            result = await session.call_tool(
                "okf_search",
                {"query": "chlorophyll sunlight photosynthesis", "k": 3})
            assert not result.isError
            payload = (result.structuredContent
                       if result.structuredContent is not None
                       else json.loads(result.content[0].text))
            assert payload["hits"][0]["id"] == "photosynthesis"
            assert payload["hits"][0]["score"] >= payload["hits"][-1]["score"]

    anyio.run(main)
