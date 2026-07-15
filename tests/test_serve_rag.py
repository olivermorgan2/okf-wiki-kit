"""Offline tests for Phase 7 (serve/rag): chunking, indexing, search, ask-plumbing.

No network, no models: `FakeEmbedder` produces deterministic hashed bag-of-words
vectors, so cosine ranking is fully testable. Requires numpy (the `rag` extra).
"""

import hashlib
import re

import pytest

np = pytest.importorskip("numpy")

from okfkit import config, engine
from okfkit.model import Node
from okfkit.serve import Index, VaultNote, chunk_notes, load_vault


# ---------------------------------------------------------------------------
# Deterministic offline embedder
# ---------------------------------------------------------------------------
class FakeEmbedder:
    """Hashed bag-of-words vectors: each word bumps one of `dim` buckets (md5,
    so stable across processes). Shared vocabulary => higher cosine similarity.
    Counts every embedded text so incremental-refresh reuse is assertable."""

    dim = 64

    def __init__(self, provider="fake", model="bow-64"):
        self.provider = provider
        self.model = model
        self.embedded_texts = []          # every text ever passed to embed()

    def embed(self, texts, input_type=None, batch_size=128):
        texts = list(texts)
        self.embedded_texts += texts
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


def _note(nid, ntype, title, body, description=""):
    return VaultNote(id=nid, path="", type=ntype, title=title,
                     description=description, body=body)


def _corpus():
    """Three notes with distinct vocabularies for unambiguous cosine ranking."""
    return [
        _note("photosynthesis", "Concept", "Photosynthesis",
              "Chlorophyll pigments capture sunlight energy. Photosynthesis "
              "converts carbon dioxide and water into glucose and oxygen.",
              description="How plants turn sunlight into chemical energy."),
        _note("volcano", "Topic", "Volcano",
              "Magma rises through the crust and erupts as lava. Volcanic ash "
              "and pyroclastic flows reshape the landscape."),
        _note("glacier", "Topic", "Glacier",
              "Compacted snow forms slow-moving rivers of ice. Glaciers carve "
              "valleys and deposit moraines as they retreat."),
    ]


# ---------------------------------------------------------------------------
# load_vault
# ---------------------------------------------------------------------------
def test_load_vault_skips_index_and_home(tmp_path):
    nodes = [Node(id="a", type="Topic", title="Alpha", body="Alpha body."),
             Node(id="b", type="Concept", title="Beta", body="Beta body.")]
    res = engine.build(nodes, str(tmp_path / "vault"))
    assert res.ok

    everything = load_vault(str(tmp_path / "vault"))
    assert {n.type for n in everything.values()} >= {"Index", "Home"}

    notes = load_vault(str(tmp_path / "vault"), exclude_types=("Index", "Home"))
    assert sorted(notes) == ["a", "b"]
    assert all(n.type not in ("Index", "Home") for n in notes.values())
    assert notes["a"].title == "Alpha" and "Alpha body." in notes["a"].body


# ---------------------------------------------------------------------------
# chunk_notes
# ---------------------------------------------------------------------------
def test_chunk_notes_small_notes_stay_whole():
    chunks = chunk_notes(_corpus(), max_chars=4000)
    assert [c.node_id for c in chunks] == ["glacier", "photosynthesis", "volcano"]
    assert all(c.heading is None for c in chunks)          # unsplit => no heading
    photo = next(c for c in chunks if c.node_id == "photosynthesis")
    assert photo.text.startswith("Concept: Photosynthesis\n"
                                 "How plants turn sunlight into chemical energy.")
    assert photo.content_hash == hashlib.sha256(
        photo.text.encode("utf-8")).hexdigest()[:16]


def test_chunk_notes_splits_only_oversized_notes_at_headings():
    big_body = ("An introduction to plate tectonics.\n\n"
                "## Subduction\n" + "Oceanic plates dive under continents. " * 8 +
                "\n\n## Rifting\n" + "Continental crust stretches and thins. " * 8)
    notes = [_note("tectonics", "Topic", "Tectonics", big_body),
             _note("volcano", "Topic", "Volcano", "Short note.\n\n## Lava\nHot rock.")]
    chunks = chunk_notes(notes, max_chars=300)

    small = [c for c in chunks if c.node_id == "volcano"]
    assert len(small) == 1 and small[0].heading is None    # small note untouched

    big = [c for c in chunks if c.node_id == "tectonics"]
    assert len(big) > 1                                    # oversized note split
    assert {c.heading for c in big} >= {"Subduction", "Rifting"}
    assert all(c.text.startswith("Topic: Tectonics") for c in big)   # context prefix
    assert len({c.content_hash for c in chunks}) == len(chunks)


def test_chunk_notes_excludes_types():
    notes = _corpus() + [_note("home", "Home", "Home", "Welcome."),
                         _note("topics", "Index", "Topic Index", "- [[volcano]]")]
    chunks = chunk_notes(notes, max_chars=4000, exclude_types=("Index", "Home"))
    assert {c.node_id for c in chunks} == {"photosynthesis", "volcano", "glacier"}


# ---------------------------------------------------------------------------
# Index: build / save / load / search
# ---------------------------------------------------------------------------
def test_index_build_save_load_round_trip(tmp_path):
    backend = FakeEmbedder()
    idx = Index(backend, vault_path=str(tmp_path / "vault"))
    stats = idx.build(chunk_notes(_corpus()), log=lambda *a: None)
    assert stats == {"total": 3, "embedded": 3, "reused": 0}

    npz_path, chunks_path = idx.save(str(tmp_path))
    assert npz_path.endswith("embeddings.npz") and chunks_path.endswith("chunks.json")
    assert idx.meta["provider"] == "fake" and idx.meta["model"] == "bow-64"
    assert idx.meta["dim"] == FakeEmbedder.dim

    loaded = Index.load(str(tmp_path), backend=FakeEmbedder())
    assert loaded.chunks == idx.chunks
    assert np.allclose(loaded.vectors, idx.vectors)
    assert loaded.meta["vault_path"] == str(tmp_path / "vault")

    # searching a freshly loaded index gives the same ranking
    hits = loaded.search("chlorophyll sunlight photosynthesis", k=3)
    assert hits[0].node_id == "photosynthesis"


def test_index_load_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="okf index"):
        Index.load(str(tmp_path), backend=FakeEmbedder())


def test_search_returns_expected_node_first():
    idx = Index(FakeEmbedder())
    idx.build(chunk_notes(_corpus()), log=lambda *a: None)

    hits = idx.search("How does chlorophyll capture sunlight for photosynthesis?", k=3)
    assert [h.node_id for h in hits][0] == "photosynthesis"
    assert hits[0].score > hits[-1].score
    assert -1.0 <= hits[-1].score <= 1.0

    hits = idx.search("magma lava eruption volcanic ash", k=2)
    assert hits[0].node_id == "volcano"
    assert len(hits) == 2                                   # k honored


def test_search_types_filter():
    idx = Index(FakeEmbedder())
    idx.build(chunk_notes(_corpus()), log=lambda *a: None)
    # photosynthesis is the best match, but it's a Concept — filter it out
    hits = idx.search("chlorophyll sunlight photosynthesis", k=5, types=["topic"])
    assert hits and all(h.type == "Topic" for h in hits)
    assert "photosynthesis" not in {h.node_id for h in hits}


def test_incremental_refresh_reembeds_only_changed_note():
    backend = FakeEmbedder()
    idx = Index(backend)
    idx.build(chunk_notes(_corpus()), log=lambda *a: None)
    assert len(backend.embedded_texts) == 3

    notes = _corpus()
    notes[1].body += " A new eruption was observed in the caldera."   # volcano only
    stats = idx.build(chunk_notes(notes), log=lambda *a: None)
    assert stats == {"total": 3, "embedded": 1, "reused": 2}
    assert len(backend.embedded_texts) == 4                 # exactly one new embed call text
    assert "caldera" in backend.embedded_texts[-1]

    # --force re-embeds everything even with nothing changed
    stats = idx.build(chunk_notes(notes), force=True, log=lambda *a: None)
    assert stats == {"total": 3, "embedded": 3, "reused": 0}


def test_provider_or_model_mismatch_raises_clear_error(tmp_path):
    idx = Index(FakeEmbedder())
    idx.build(chunk_notes(_corpus()), log=lambda *a: None)
    idx.save(str(tmp_path))

    with pytest.raises(SystemExit, match="Index was built with provider"):
        Index.load(str(tmp_path), backend=FakeEmbedder(provider="voyage"))
    with pytest.raises(SystemExit, match="okf index --force"):
        Index.load(str(tmp_path), backend=FakeEmbedder(model="bow-128"))
    # matching backend loads fine
    Index.load(str(tmp_path), backend=FakeEmbedder())


def test_index_dir_lands_next_to_config_not_in_vault(tmp_path):
    (tmp_path / "okf.config.yaml").write_text("output: ./vault\n", encoding="utf-8")
    cfg = config.load(str(tmp_path / "okf.config.yaml"))
    assert cfg.base_dir == str(tmp_path)
    vault = cfg.resolve(cfg.output)
    engine.build([Node(id="a", type="Topic", title="Alpha", body="Alpha body.")], vault)

    idx = Index(FakeEmbedder(), vault_path=vault)
    idx.build(chunk_notes(load_vault(vault, exclude_types=("Index", "Home"))),
              log=lambda *a: None)
    idx.save(cfg.base_dir)

    assert (tmp_path / ".okf" / "embeddings.npz").is_file()
    assert (tmp_path / ".okf" / "chunks.json").is_file()
    assert not (tmp_path / "vault" / ".okf").exists()       # never inside the vault
