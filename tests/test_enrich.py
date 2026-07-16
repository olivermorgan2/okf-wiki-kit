"""Offline tests for enrich: JSON extraction/repair and canonicalization batching.

No network, no SDKs: `FakeBackend` overrides `Backend._complete` with scripted
responses, so the fence-stripping, self-repair retry, non-fatal fallback, and
batch-size behaviour are all testable.
"""

import json
import re

import pytest

from okfkit import enrich
from okfkit.model import Node


# ---------------------------------------------------------------------------
# extract_json
# ---------------------------------------------------------------------------
def test_extract_json_plain():
    assert enrich.extract_json('{"a": 1}') == {"a": 1}
    assert enrich.extract_json("[1, 2, 3]") == [1, 2, 3]


def test_extract_json_fenced():
    assert enrich.extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_fenced_with_language_tag():
    assert enrich.extract_json('```json\n[{"x": 1}]\n```') == [{"x": 1}]


def test_extract_json_leading_prose():
    text = 'Here is the JSON you asked for:\n{"concept_clusters": []}'
    assert enrich.extract_json(text) == {"concept_clusters": []}


def test_extract_json_trailing_commas():
    assert enrich.extract_json('{"a": [1, 2,],}') == {"a": [1, 2]}
    assert enrich.extract_json("```json\n[1, 2,]\n```") == [1, 2]


def test_extract_json_prose_and_fences_and_commas():
    text = 'Sure! Here you go:\n```json\n{"ids": ["a", "b",]}\n```\nHope that helps.'
    assert enrich.extract_json(text) == {"ids": ["a", "b"]}


def test_extract_json_garbage_raises_with_snippet():
    with pytest.raises(ValueError, match="no parseable JSON"):
        enrich.extract_json("Sorry, I cannot help with that.")
    with pytest.raises(ValueError):
        enrich.extract_json("")


# ---------------------------------------------------------------------------
# Scripted chat backend (no SDK, no network)
# ---------------------------------------------------------------------------
class FakeBackend(enrich.Backend):
    """`Backend` with `_complete` replaced by a script: one callable per LLM
    call, each given the conversation turns and returning the raw model text.
    Keeps `Backend.json`'s real extraction + self-repair retry logic."""

    def __init__(self, script):
        self.provider, self.model = "fake", "fake-model"   # skip real __init__/clients
        self.script = list(script)
        self.turns_seen = []                               # turns of every _complete call

    def _complete(self, system, turns, max_tokens, json_mode=True):
        self.turns_seen.append(turns)
        return self.script.pop(0)(turns)


def _nodes(n):
    return [Node(id=f"c{i:03d}", type="Concept", title=f"Concept {i:03d}") for i in range(n)]


def _valid_clusters_reply(turns, dress=lambda s: s):
    """Answer a canonicalization prompt correctly: one cluster per input id."""
    user = turns[0][1]
    items = json.loads(user[user.index("Input nodes:") + len("Input nodes:"):])
    payload = {"concept_clusters": [
        {"canonical_title": it["title"], "aliases": [],
         "member_ids": [it["id"]], "definition": f"Definition of {it['title']}."}
        for it in items
    ]}
    return dress(json.dumps(payload))


# ---------------------------------------------------------------------------
# canonicalize: extraction handles dirty output, retry repairs, fallback warns
# ---------------------------------------------------------------------------
def test_canonicalize_survives_fenced_dirty_json_without_retry():
    dress = lambda s: f"Here are the clusters:\n```json\n{s}\n```\nLet me know!"
    backend = FakeBackend([lambda t: _valid_clusters_reply(t, dress)])
    clusters = enrich.canonicalize(backend, _nodes(5), log=lambda *a: None)
    assert len(backend.turns_seen) == 1                    # no repair retry needed
    assert len(clusters) == 5
    assert all(c["definition"] for c in clusters)


def test_canonicalize_repair_retry_succeeds():
    backend = FakeBackend([
        lambda t: "Sorry, something went wrong.",          # unparseable first answer
        _valid_clusters_reply,                             # fixed on the repair turn
    ])
    clusters = enrich.canonicalize(backend, _nodes(4), log=lambda *a: None)
    assert len(backend.turns_seen) == 2                    # exactly one retry
    repair_turns = backend.turns_seen[1]
    assert repair_turns[1][0] == "assistant"               # model shown its own output
    assert "Sorry, something went wrong." in repair_turns[1][1]
    assert "not valid JSON" in repair_turns[2][1]
    assert len(clusters) == 4


def test_canonicalize_double_failure_falls_back_and_warns(capsys):
    backend = FakeBackend([
        lambda t: "garbage one",
        lambda t: "garbage two",
    ])
    clusters = enrich.canonicalize(backend, _nodes(3), log=lambda *a: None)
    assert len(backend.turns_seen) == 2
    # non-fatal: every concept kept, unmerged
    assert sorted(m for c in clusters for m in c["member_ids"]) == ["c000", "c001", "c002"]
    assert all(c["aliases"] == [] and c["definition"] == "" for c in clusters)
    err = capsys.readouterr().err
    assert "batch 1" in err
    assert "no parseable JSON" in err
    assert "unmerged" in err


def test_canonicalize_default_batch_size_is_30():
    assert enrich.CANON_BATCH_SIZE == 30
    backend = FakeBackend([_valid_clusters_reply] * 3)
    clusters = enrich.canonicalize(backend, _nodes(65), log=lambda *a: None)
    assert len(backend.turns_seen) == 3                    # 65 concepts -> 30 + 30 + 5
    assert len(clusters) == 65
    sizes = [len(json.loads(u[u.index("Input nodes:") + len("Input nodes:"):]))
             for u in (turns[0][1] for turns in backend.turns_seen)]
    assert sizes == [30, 30, 5]


def test_canonicalize_batch_size_override():
    backend = FakeBackend([_valid_clusters_reply] * 2)
    enrich.canonicalize(backend, _nodes(20), batch_size=10, log=lambda *a: None)
    assert len(backend.turns_seen) == 2


def test_canonicalize_prompt_demands_bare_json():
    backend = FakeBackend([_valid_clusters_reply])
    enrich.canonicalize(backend, _nodes(2), log=lambda *a: None)
    user = backend.turns_seen[0][0][1]
    assert re.search(r"Return ONLY a JSON object", user)
    assert "no markdown code fences" in user and "no commentary" in user
