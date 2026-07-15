import pytest

from okfkit import engine
from okfkit.model import Link, Node


def _nodes():
    return [
        Node(id="a", type="Topic", title="Alpha", body="Alpha discusses Photosynthesis.",
             links=[Link("b", rel="related", section="See also")]),
        Node(id="b", type="Topic", title="Beta"),
        Node(id="photosynthesis", type="Concept", title="Photosynthesis",
             aliases=["photosynthetic process"]),
    ]


def test_build_counts_and_resolution(tmp_path):
    res = engine.build(_nodes(), str(tmp_path / "vault"))
    assert res.ok
    assert res.counts == {"Topic": 2, "Concept": 1}
    # 3 nodes + 2 type indexes + 1 root index
    assert res.total_files == 6


def test_node_requires_type_and_id():
    with pytest.raises(ValueError):
        Node(id="x", type="", title="No type")
    with pytest.raises(ValueError):
        Node(id="", type="T", title="No id")


def test_duplicate_ids_rejected(tmp_path):
    dup = [Node(id="x", type="T", title="One"), Node(id="x", type="T", title="Two")]
    with pytest.raises(ValueError):
        engine.build(dup, str(tmp_path / "v"))


def test_link_inference(tmp_path):
    cfg = {"concept_type": "Concept", "scan_types": ["Topic"], "min_surface_len": 5}
    res = engine.build(_nodes(), str(tmp_path / "v"), link_inference=cfg)
    assert res.inferred_links == 1
    alpha = (tmp_path / "v" / "topic" / "a.md").read_text()
    assert "[[photosynthesis|Photosynthesis]]" in alpha
    concept = (tmp_path / "v" / "concept" / "photosynthesis.md").read_text()
    assert "[[a|Alpha]]" in concept          # back-link


def test_unresolved_link_is_reported(tmp_path):
    nodes = [Node(id="a", type="T", title="A", links=[Link("ghost", section="Refs")])]
    res = engine.build(nodes, str(tmp_path / "v"))
    assert not res.ok
    assert "ghost" in res.unresolved


def test_canonicalization_merges_and_redirects(tmp_path):
    nodes = [
        Node(id="c-he", type="Concept", title="health equity"),
        Node(id="c-HE", type="Concept", title="Health Equity"),
        Node(id="ch1", type="Chapter", title="Ch1",
             links=[Link("c-he", section="Concepts"), Link("c-HE", section="Concepts")]),
    ]
    enrichment = {"canonical": {"clusters": [{
        "canonical_title": "Health Equity", "canonical_id": "concept-health-equity",
        "member_ids": ["c-he", "c-HE"], "aliases": ["health equity"],
        "definition": "Fair opportunity to be healthy.",
    }]}}
    res = engine.build(nodes, str(tmp_path / "v"), enrichment=enrichment)
    assert res.ok
    assert res.counts["Concept"] == 1        # two merged into one
    ch1 = (tmp_path / "v" / "chapter" / "ch1.md").read_text()
    assert "concept-health-equity" in ch1    # links redirected
    concept = (tmp_path / "v" / "concept" / "concept-health-equity.md").read_text()
    assert "Fair opportunity" in concept     # definition applied
