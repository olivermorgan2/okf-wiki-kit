from okfkit import render


def test_slug():
    assert render.slug("Health Equity") == "health-equity"
    assert render.slug("1.2 Defining Things") == "defining-things"   # leading number stripped
    assert render.slug("DALYs (measure)") == "dalys-measure"
    assert render.slug("") == "untitled"


def test_frontmatter_ordering_and_quoting():
    fm = render.frontmatter({"type": "Concept", "title": "A: B", "tags": ["x", "y"], "empty": None})
    assert fm.startswith("---\ntype: Concept\n")
    assert 'title: "A: B"' in fm          # colon forces quoting
    assert "tags:\n  - x\n  - y" in fm
    assert "empty" not in fm              # None omitted


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
