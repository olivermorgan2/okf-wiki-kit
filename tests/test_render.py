from collections import OrderedDict

import pytest
import yaml

from okfkit import render


def parse_frontmatter(fm: str) -> dict:
    """yaml.safe_load the emitted block. The closing ``---`` is a YAML document
    marker, so strip the delimiters and load just the payload."""
    assert fm.startswith("---\n") and fm.endswith("---\n")
    return yaml.safe_load(fm[4:-4])


def test_slug():
    assert render.slug("Health Equity") == "health-equity"
    assert render.slug("1.2 Defining Things") == "defining-things"   # leading number stripped
    assert render.slug("DALYs (measure)") == "dalys-measure"
    assert render.slug("") == "untitled"


def test_frontmatter_omission_and_ordering():
    fm = render.frontmatter(OrderedDict(
        [("type", "Concept"), ("title", "A: B"), ("tags", ["x", "y"]), ("empty", None), ("none_list", [])]
    ))
    assert fm.startswith("---\n") and fm.endswith("---\n")
    assert "empty" not in fm                       # None omitted
    assert "none_list" not in fm                   # empty list omitted
    data = parse_frontmatter(fm)
    assert list(data) == ["type", "title", "tags"]  # insertion order preserved
    assert data == {"type": "Concept", "title": "A: B", "tags": ["x", "y"]}


@pytest.mark.parametrize("value", [
    "Fair, reasonable, and clear.",
    "Jidoka: autonomation with a human touch.",
    'He said "stop the line" immediately.',
    "Kaizen — 改善 — continuous improvement.",
    "Use the C:\\path\\to\\file convention.",
    'Escape it as \\"quoted\\" text.',
    "First line.\nSecond line.",
])
def test_frontmatter_scalars_round_trip(value):
    fm = render.frontmatter({"description": value})
    assert parse_frontmatter(fm)["description"] == value
    assert render.split_frontmatter(fm)[0]["description"] == value  # consumer path


def test_frontmatter_unicode_readable():
    fm = render.frontmatter({"description": "Kaizen — 改善 — continuous improvement."})
    assert "改善" in fm                            # allow_unicode: not escaped


def test_frontmatter_list_round_trip():
    fm = render.frontmatter({"tags": ["a: b", 'c "d"', "e\\f"]})
    assert parse_frontmatter(fm)["tags"] == ["a: b", 'c "d"', "e\\f"]


def test_wikilink_styles():
    assert render.wikilink("some-note", "Some Note") == "[[some-note|Some Note]]"
    assert render.wikilink("some-note") == "[[some-note]]"
    assert render.wikilink("n", "N", style="markdown") == "[N](n.md)"


def test_find_wikilinks_and_strip_code():
    text = "See [[alpha|Alpha]] and [[beta]]. `[[not-a-link]]` in code."
    stripped = render.strip_code(text)
    assert render.find_wikilinks(stripped) == ["alpha", "beta"]


def test_split_frontmatter():
    fm, body = render.split_frontmatter("---\ntype: Note\ntitle: X\n---\nHello")
    assert fm == {"type": "Note", "title": "X"}
    assert body.strip() == "Hello"
    fm2, body2 = render.split_frontmatter("No frontmatter here")
    assert fm2 == {} and body2 == "No frontmatter here"


def test_load_vault_names_bad_file(tmp_path):
    from okfkit.serve import vault

    bad = tmp_path / "bad.md"
    bad.write_text('---\ntitle: "unclosed\n---\nBody\n', encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        vault.load_vault(str(tmp_path))
    assert str(bad) in str(exc.value)
    assert "invalid YAML frontmatter" in str(exc.value)
