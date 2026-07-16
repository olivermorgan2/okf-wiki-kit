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


def test_markdown_folder_nested_duplicate_stems(tmp_path, capsys):
    (tmp_path / "projects").mkdir()
    (tmp_path / "archive").mkdir()
    (tmp_path / "projects" / "notes.md").write_text("Project notes.")
    (tmp_path / "archive" / "notes.md").write_text("Archived notes.")
    ad = load_adapter("markdown_folder", {"path": str(tmp_path)})
    nodes = {n.id: n for n in ad.load()}
    # sorted glob order: archive/ before projects/, so archive keeps the plain stem
    assert set(nodes) == {"notes", "projects-notes"}
    assert nodes["notes"].body == "Archived notes."
    assert nodes["projects-notes"].body == "Project notes."
    err = capsys.readouterr().err
    assert "Warning: markdown_folder:" in err
    assert "'projects/notes.md' collides with 'archive/notes.md'" in err
    assert "using id 'projects-notes'" in err


def test_markdown_folder_explicit_id_duplicates_not_disambiguated(tmp_path, capsys):
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    (tmp_path / "one" / "first.md").write_text("---\nid: same\n---\nBody one.")
    (tmp_path / "two" / "second.md").write_text("---\nid: same\n---\nBody two.")
    ad = load_adapter("markdown_folder", {"path": str(tmp_path)})
    ids = [n.id for n in ad.load()]
    assert ids == ["same", "same"]           # engine, not adapter, flags this user mistake
    assert capsys.readouterr().err == ""


def test_markdown_folder_triple_collision_relative_path_fallback(tmp_path, capsys):
    (tmp_path / "a" / "x").mkdir(parents=True)
    (tmp_path / "b" / "x").mkdir(parents=True)
    (tmp_path / "a" / "notes.md").write_text("A notes.")
    (tmp_path / "a" / "x" / "notes.md").write_text("AX notes.")
    (tmp_path / "b" / "x" / "notes.md").write_text("BX notes.")
    ad = load_adapter("markdown_folder", {"path": str(tmp_path)})
    nodes = {n.id: n for n in ad.load()}
    # a/notes.md keeps 'notes'; a/x/notes.md takes the parent slug 'x-notes';
    # b/x/notes.md finds 'x-notes' taken too and falls back to the full relative path
    assert set(nodes) == {"notes", "x-notes", "b-x-notes"}
    assert nodes["b-x-notes"].body == "BX notes."
    err = capsys.readouterr().err
    assert err.count("Warning: markdown_folder:") == 2
    assert "using id 'b-x-notes'" in err


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
