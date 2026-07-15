"""Example adapter: a structured textbook → OKF nodes.

Worked reference for writing a `SourceAdapter` against a real, messy source. It reads
a folder of `chapter_NN_*.md` content files plus `chapter_NN_metadata.json` sidecars and
emits five node types — Part, Chapter, Section, Concept, Case Study — with the relationships
between them. This is a refactor of the original one-off generator into the adapter interface.

No data ships with the kit. Point it at your own data via okf.config.yaml:

    adapter: examples/textbook/adapter.py:TextbookAdapter
    adapter_options:
      chapters_dir: /path/to/your/chapters
    link_inference:
      concept_type: Concept
      scan_types: [Section]
      exclude_titles: [References]
"""

from __future__ import annotations

import glob
import json
import os
import re

from okfkit import render
from okfkit.adapters.base import SourceAdapter
from okfkit.model import Link, Node

CONCEPT_KEYS = ["key_concepts", "key_topics", "key_terms", "keywords", "key_frameworks", "key_themes"]
CONCEPT_SUBKEYS = ["concept", "topic", "term", "keyword", "framework", "name", "title", "theme", "text"]


class TextbookAdapter(SourceAdapter):
    def load(self):
        chapters_dir = self.options.get("chapters_dir")
        if not chapters_dir or not os.path.isdir(chapters_dir):
            raise NotADirectoryError(
                f"TextbookAdapter: set adapter_options.chapters_dir to a real folder "
                f"(got {chapters_dir!r})."
            )
        chapters = _discover(chapters_dir)

        concept_reg: dict[str, dict] = {}   # slug -> {name, chapters:set, aliases:set}
        part_reg: dict[int, dict] = {}      # part_number -> {title, chapters:[]}
        ch_ids: dict[int, str] = {}
        ch_titles: dict[int, str] = {}

        # ---- pass 1: chapter/part/section/case nodes + concept aggregation ----
        deferred = []   # (kind, payload) emitted after concept nodes are known
        for n, ch in chapters.items():
            meta, content = ch["meta"], ch["content"]
            title = meta.get("title", f"Chapter {n}")
            cid = f"ch{n:02d}-{render.slug(title)}"
            ch_ids[n] = cid
            ch_titles[n] = f"Chapter {n}: {title}"
            part = meta.get("part") or {}
            pnum = part.get("part_number")
            if pnum is not None:
                part_reg.setdefault(pnum, {"title": part.get("part_title", ""), "chapters": []})
                part_reg[pnum]["chapters"].append(n)

            # concepts declared by this chapter
            ch_concepts = []
            for key in CONCEPT_KEYS:
                for c in _as_str_list(meta.get(key)):
                    s = render.slug(c)
                    reg = concept_reg.setdefault(s, {"name": c, "chapters": set(), "aliases": set()})
                    reg["chapters"].add(n)
                    if len(c) < len(reg["name"]):
                        reg["aliases"].add(reg["name"]); reg["name"] = c
                    elif c != reg["name"]:
                        reg["aliases"].add(c)
                    if s not in [x[0] for x in ch_concepts]:
                        ch_concepts.append((s, c))

            # sections (split on H2 headings; route Learning Objectives to the chapter)
            lo_block, secs = _split_sections(content)
            sec_links = []
            for i, s in enumerate(secs, start=1):
                sid = f"ch{n:02d}-s{i:02d}-{render.slug(s['heading'])}"
                tags = ["section"] + (["references"] if s["heading"].strip().lower() == "references" else [])
                deferred.append(("section", dict(
                    id=sid, n=n, cid=cid, ch_title=ch_titles[n], heading=s["heading"],
                    body=s["body"], index=i, tags=tags)))
                sec_links.append(Link(sid, rel="section", section="Sections", display=s["heading"]))

            # case studies
            case_links = []
            for j, cs in enumerate(meta.get("case_studies") or [], start=1):
                ctitle = cs.get("title") or f"Case Study {n}.{j}"
                caseid = f"case-{n:02d}-{j:02d}-{render.slug(ctitle)}"
                deferred.append(("case", dict(id=caseid, n=n, cid=cid, ch_title=ch_titles[n],
                                              cs=cs, title=ctitle)))
                case_links.append(Link(caseid, rel="case", section="Case Studies", display=ctitle))

            related = set()
            for rk in ("prerequisite_chapters", "prerequisites", "related_chapters",
                       "preceding_chapter", "following_chapter", "cross_references"):
                for r in _ints(meta.get(rk)):
                    if r != n and r in chapters:
                        related.add(r)

            deferred.append(("chapter", dict(
                id=cid, n=n, title=ch_titles[n], meta=meta, pnum=pnum,
                lo=meta.get("learning_objectives") or [], concepts=ch_concepts,
                sec_links=sec_links, case_links=case_links, related=sorted(related))))

        # ---- parts ----
        for pnum, p in sorted(part_reg.items()):
            pid = f"part-{pnum:02d}-{render.slug(p['title'])}"
            links = [Link(ch_ids[cn], rel="chapter", section="Chapters", display=ch_titles[cn])
                     for cn in sorted(p["chapters"])]
            yield Node(id=pid, type="Part", title=f"Part {pnum}: {p['title']}",
                       frontmatter={"part_number": pnum}, links=links, tags=["part"])

        part_id = {pn: f"part-{pn:02d}-{render.slug(p['title'])}" for pn, p in part_reg.items()}

        # ---- concepts ----
        for s, reg in sorted(concept_reg.items()):
            links = [Link(ch_ids[c], rel="chapter", section="Appears in", display=ch_titles[c])
                     for c in sorted(reg["chapters"])]
            yield Node(id=f"concept-{s}", type="Concept", title=reg["name"],
                       aliases=sorted(a for a in reg["aliases"] if a and a != reg["name"]),
                       links=links, tags=["concept"])

        # ---- chapters / sections / cases ----
        for kind, d in deferred:
            if kind == "chapter":
                yield _chapter_node(d, part_id, ch_ids, ch_titles)
            elif kind == "section":
                yield _section_node(d)
            elif kind == "case":
                yield _case_node(d)


# ---------------------------------------------------------------------------
# Node builders
# ---------------------------------------------------------------------------
def _chapter_node(d, part_id, ch_ids, ch_titles):
    body_lines = []
    bloom_tags = []
    if d["lo"]:
        body_lines.append("## Learning Objectives\n")
        for lo in d["lo"]:
            if isinstance(lo, dict):
                bl = lo.get("bloom_level")
                tag = f" `#bloom/{bl.strip().lower()}`" if bl else ""
                if bl:
                    bloom_tags.append("bloom/" + bl.strip().lower())
                body_lines.append(f"- {lo.get('text','')}{tag}")
            else:
                body_lines.append(f"- {lo}")
    links = []
    if d["pnum"] in part_id:
        links.append(Link(part_id[d["pnum"]], rel="part", section="Part"))
    links += d["sec_links"]
    links += [Link(f"concept-{s}", rel="concept", section="Key Concepts", display=name)
              for s, name in d["concepts"]]
    links += d["case_links"]
    links += [Link(ch_ids[r], rel="related", section="Related Chapters", display=ch_titles[r])
              for r in d["related"]]
    fm = {"chapter_number": d["n"], "part_number": d["pnum"],
          "sdg_alignment": _as_str_list(d["meta"].get("sdg_alignment")) or None,
          "reading_time": d["meta"].get("estimated_reading_time")}
    return Node(id=d["id"], type="Chapter", title=d["title"], body="\n".join(body_lines),
                frontmatter={k: v for k, v in fm.items() if v is not None},
                links=links, tags=["chapter"] + sorted(set(bloom_tags)))


def _section_node(d):
    return Node(id=d["id"], type="Section", title=f"Ch{d['n']} · {d['heading']}",
                body=f"# {d['heading']}\n\n{d['body']}".strip(),
                frontmatter={"chapter_number": d["n"], "section_number": d["index"]},
                links=[Link(d["cid"], rel="parent", section="Part of", display=d["ch_title"])],
                tags=d["tags"])


def _case_node(d):
    cs = d["cs"]
    geo = _first(cs, "geographic_focus", "focus", "countries", "country", "population_focus")
    geo = _flat(geo)
    rows = [("WHO region", _flat(cs.get("who_region"))), ("Income level", _flat(cs.get("income_level"))),
            ("Geography", geo), ("Period", _flat(cs.get("time_period")))]
    body = ["| | |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows if v] + [""]
    labels = {"key_lessons": "Key lessons", "outcomes": "Outcomes", "key_findings": "Key findings",
              "key_interventions": "Key interventions", "key_themes": "Key themes"}
    for lk, label in labels.items():
        vals = _as_str_list(cs.get(lk))
        if vals:
            body += [f"## {label}", ""] + [f"- {v}" for v in vals] + [""]
    fm = {"who_region": _flat(cs.get("who_region")), "income_level": _flat(cs.get("income_level")),
          "geography": geo, "time_period": _flat(cs.get("time_period"))}
    tags = ["case-study"] + ([f"who/{render.slug(_flat(cs.get('who_region')))}"] if cs.get("who_region") else [])
    return Node(id=d["id"], type="Case Study", title=d["title"], body="\n".join(body),
                frontmatter={k: v for k, v in fm.items() if v},
                links=[Link(d["cid"], rel="source", section="Source", display=d["ch_title"])],
                tags=tags)


# ---------------------------------------------------------------------------
# Source parsing helpers (mirrors the original generator)
# ---------------------------------------------------------------------------
def _discover(chapters_dir):
    chapters = {}
    for mf in glob.glob(os.path.join(chapters_dir, "*_metadata.json")):
        m = re.search(r"chapter_(\d+)_metadata", os.path.basename(mf), re.I)
        if m:
            chapters[int(m.group(1))] = {"meta": json.load(open(mf, encoding="utf-8")), "content": ""}
    for cf in glob.glob(os.path.join(chapters_dir, "*.md")):
        m = re.search(r"chapter[_ ](\d+)", os.path.basename(cf), re.I)
        if m and int(m.group(1)) in chapters and not chapters[int(m.group(1))]["content"]:
            chapters[int(m.group(1))]["content"] = open(cf, encoding="utf-8").read()
    return dict(sorted(chapters.items()))


def _split_sections(content):
    if not content:
        return "", []
    lo_block, sections, cur_head, cur = "", [], None, []

    def flush():
        nonlocal cur_head, cur, lo_block
        if cur_head is None:
            return
        body = "\n".join(cur).strip()
        if cur_head.strip().lower() == "learning objectives":
            lo_block = body
        else:
            sections.append({"heading": cur_head.strip(), "body": body})
        cur_head, cur = None, []

    for line in content.splitlines():
        m = re.match(r"^##\s+(.*)$", line)
        if m and not line.startswith("###"):
            flush(); cur_head = m.group(1); cur = []
        elif cur_head is not None:
            cur.append(line)
    flush()
    return lo_block, sections


def _as_str_list(value):
    out = []
    if value is None:
        return out
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        value = [value]
    for item in value if isinstance(value, list) else []:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            for k in CONCEPT_SUBKEYS:
                if isinstance(item.get(k), str) and item[k].strip():
                    out.append(item[k].strip()); break
    return out


def _first(d, *keys):
    for k in keys:
        if d.get(k):
            return d[k]
    return None


def _flat(v):
    if v is None:
        return None
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    if isinstance(v, dict):
        return ", ".join(str(x) for x in v.values())
    return str(v)


def _ints(value):
    found = []
    def scan(x):
        if isinstance(x, bool):
            return
        if isinstance(x, int):
            found.append(x)
        elif isinstance(x, str):
            found.extend(int(m) for m in re.findall(r"\b(\d{1,2})\b", x))
        elif isinstance(x, list):
            [scan(i) for i in x]
        elif isinstance(x, dict):
            [scan(i) for i in x.values()]
    scan(value)
    return [n for n in found if 1 <= n <= 60]
