import pytest

from okfkit.adapters.base import SourceAdapter, load_adapter


def test_markdown_folder_adapter(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "alpha.md").write_text("---\ntype: Topic\ntitle: Alpha\ntags: [demo]\n---\n"
                                    "Alpha links to [[beta]].")
    (notes / "beta.md").write_text("Plain note, no frontmatter.")
    ad = load_adapter("markdown_folder", {"path": str(notes), "default_type": "Note"})
    nodes = {n.id: n for n in ad.load()}
    assert set(nodes) == {"alpha", "beta"}
    assert nodes["alpha"].type == "Topic" and nodes["alpha"].tags == ["demo"]
    assert nodes["beta"].type == "Note" and nodes["beta"].title == "beta"
    # inline links are preserved in body, not lifted into Link objects
    assert "[[beta]]" in nodes["alpha"].body
    assert nodes["alpha"].links == []


def test_load_adapter_rejects_bad_spec():
    with pytest.raises(ValueError):
        load_adapter("not_a_builtin_no_colon")


def test_load_adapter_from_path(tmp_path):
    mod = tmp_path / "myadapter.py"
    mod.write_text(
        "from okfkit.adapters.base import SourceAdapter\n"
        "from okfkit.model import Node\n"
        "class A(SourceAdapter):\n"
        "    def load(self):\n"
        "        return [Node(id='n1', type='X', title='N1')]\n"
    )
    ad = load_adapter(f"{mod}:A")
    assert isinstance(ad, SourceAdapter)
    nodes = list(ad.load())
    assert nodes[0].id == "n1"
