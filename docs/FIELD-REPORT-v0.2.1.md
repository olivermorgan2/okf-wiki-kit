# Field report — okf-wiki-kit v0.2.1 in real use

Findings from a from-scratch inspection of v0.2.1 as deployed on a real project
("The Managed Agent" book, 18 chapters → 54-note vault at `../wiki/`). The reader
was a fresh session with no memory of building the kit — so this doubles as a test
of whether the kit explains itself to a newcomer.

**Verdict: the pipeline works on the path this project takes — and has three serious bugs
on the path it doesn't.**

`build` → `enrich` → `index` → `serve` all ran correctly here, `okf validate` reported all
54 notes typed and every wikilink resolving, and the MCP `VaultService` answered
`vault_info` / `search` / `neighbors` correctly on the first try. The architecture note in
`serve/mcp.py` (all logic in an MCP-free `VaultService`) paid off immediately — it let the
whole server be smoke-tested in one `python -c` with no MCP handshake.

The report has two passes:

- **§§1–9 — setup, MCP, and docs friction.** Everything *around* the working core.
  The headline: the kit prints a `claude mcp add` command that doesn't work on the
  documented install, which is why this project has a complete vault, enrichment, and index
  but never had a registered server.
- **§§10–14 — the engine and the zero-code quickstart.** Written after going back for what
  the first pass admitted it hadn't read. **This is where the real bugs are**, all verified
  by execution:
  - **§10** — `okf build` can `rm -rf` arbitrary unrelated files and report success. 🔴
  - **§11** — a source note named `index.md` is silently dropped from the vault. 🔴
  - **§12** — the built-in adapter hard-crashes on any nested folder with repeated filenames. 🟠
  - **§15** — the hand-rolled YAML emitter writes invalid YAML for backslashes/newlines. 🔴

The pattern connecting nearly everything here: **this kit fails silently.** Bad register
hint, un-inherited env, stale-but-successful builds, quiet id rewrites, a wiped directory,
a dropped note, an unparseable vault — all of them report success. In §15 the kit's own
`okf validate` green-lights a vault that `okf serve` then dies on. That's the argument for
`okf doctor` (§4a), and it's why so many fixes below are "make it say something".

Legend: **[verified]** = I reproduced it, usually by executing it. **[unverified]** =
reasoned from the code, needs a check before acting. **Two unverified items remain:** §8
(the stdout question — my probe was declined) and the second half of §3 (the exact error a
voyage-configured MCP server surfaces). Everything else in this report was executed.

---

## 1. The MCP register hint is unusable on the most common install path [verified]

**The single biggest friction. The kit told me to run a command that does not work.**

`cli.py:222` and `cli.py:226` build the registration hint with a bare `okf`:

```python
register = f"claude mcp add okf-wiki -- okf serve -c {os.path.abspath(args.config)}"
```

`README.md:94` prints the same bare form. But the documented install (`pip install -e .`)
into a venv leaves `okf` **off PATH** unless that venv is active. On this machine:

```
$ which okf
okf not found
$ ls okf-wiki-kit/.venv/bin/okf
-rwxr-xr-x  ... .venv/bin/okf          # only exists here
```

So the copy-pasteable command fails, and — worse — it fails *later and invisibly*:
`claude mcp add` accepts it happily, and the server only shows up broken at client
startup. This is very likely why the server was **never registered** on this project
despite the vault, enrichment, and index all being built. The user got all the way to
the last step and silently fell off.

An MCP server is spawned by a client with **no shell, no venv activation, no PATH
guarantees** — so a bare command name is close to a worst-case default here. It needs
an absolute interpreter path.

**Fix:** emit a path that actually resolves, from the running process:

```python
register = f"claude mcp add okf-wiki -- {shlex.quote(sys.executable)} -m okfkit.cli serve -c {cfg_abspath}"
```

`sys.executable -m okfkit.cli` is the most robust form: correct by construction, and
immune to console-script/PATH issues. (`sys.argv[0]` also works when invoked via the
console script, but not under `python -m`.) Requires `okfkit/cli.py` to keep its
`if __name__ == "__main__"` block — it does, `cli.py:297`.

**Bigger win — close the loop entirely.** Add `okf serve --register` (or `okf install-mcp`)
that shells out to `claude mcp add` with the correct absolute path, and prints what it
ran. The kit already knows the config path, the vault path, and its own interpreter;
making the user hand-assemble that string is the only reason this step failed.

**Why this survived to release — worth internalizing.** `CONTRIBUTING.md:10` prescribes
the dev setup:

```bash
python -m venv .venv && source .venv/bin/activate     # <-- activate
pip install -e ".[dev,openai,anthropic]"
```

With the venv **activated**, `okf` is on PATH and the hint works perfectly. The
maintainer's own documented workflow makes this bug **structurally invisible** — it
cannot be caught by dogfooding, only by installing the way the *README* describes
(`README.md:30`: `pip install -e .`, no venv mentioned, no activation step). The two
documents disagree about the install, and the bug lives exactly in the gap.

The general lesson for the next version: **the maintainer is the one user who never
experiences the PATH problem.** Any fix should be verified from a non-activated shell,
and ideally there should be one test that shells out to the printed register command's
executable and asserts it resolves — otherwise this regresses the moment someone
"tidies" the hint back to a bare `okf`.

---

## 2. `okf init` scaffolds a config that cannot serve or index [verified]

`_CONFIG_TEMPLATE` (`cli.py:253-271`) emits `adapter`, `adapter_options`, `output`,
`link_style`, `link_inference`, `enrich` — and **no `serve:` block at all**.

`okf.config.example.yaml:52-63` has a well-commented `serve:` block with `rag` and
`mcp` settings. But a user who follows `okf init` (the command *named* for starting a
project) never sees it, and the two files silently disagree about what a config
contains. Phases 7 and 8 shipped in v0.2.0; the init template looks like it was left
at v0.1.

Defaults do save this at runtime — `_rag_settings` returns `{}` and every key has a
fallback — so `index`/`serve` still *work*. The cost is discoverability: nothing in the
scaffolded file hints that `okf index` or `okf serve` exist. On this project the user
was only correctly configured because the config was hand-written from the example,
not from `init`.

**Fix:** bring `_CONFIG_TEMPLATE` to parity with the example (commented-out is fine —
the point is that the keys are *visible*). Better: have `init` copy/render
`okf.config.example.yaml` so the two can never drift again. A test asserting that
every top-level key in the example appears in the template would pin it.

---

## 3. No `.env` support — and for MCP this is a genuine trap, not a convenience [verified + unverified]

Every key is read as a bare `os.environ.get`: `embeddings.py:92,96,108-111`, plus the
enrich path. Nothing loads a `.env`. **[verified]** `python-dotenv` is *already installed*
in the venv (transitive: `mcp` → `pydantic-settings` → `python-dotenv`) but `okfkit`
never references it — `grep -rn dotenv okfkit/` is empty.

The convenience angle is obvious. The **sharp** angle is MCP-specific:

> A server spawned by Claude Code **does not inherit your interactive shell env.**
> `export VOYAGE_API_KEY=…` in `.zshrc` does not reach `okf serve`.

So any user who configures `voyage` or `openai` embeddings gets a server whose
`okf_search` fails — while the CLI `okf search` works fine in their terminal. That
divergence is nasty to debug: same config, same vault, different result depending on
who launched the process. It's masked on *this* project only because it uses
`provider: local` (no key), and the graph tools never need keys.

**[unverified]** Worth confirming with an actual `voyage`-configured server before
acting — the failure path *looks* like `make_embedder` → `SystemExit` → caught at
`mcp.py:183` → surfaced as `SearchUnavailable("Could not load the semantic index: …")`.
If so the user sees a *"no index"*-flavored message for what is really a *missing key in
the child process* — an error that points at the wrong problem. Worth a dedicated
message if confirmed.

**Fix:** `load_dotenv()` early in `cli.main()`, searching cwd → config dir → upward.
Note the core is deliberately PyYAML-only (`pyproject.toml:22-24`), so either add
`python-dotenv` as an optional dep and import it defensively, or hand-roll the ~10-line
`KEY=value` parser and keep the zero-dep promise. Given the stated design constraint,
hand-rolling is probably more in keeping.

Also document the env-inheritance rule in the README's MCP section — it's the kind of
thing that costs an hour if you don't know it and ten seconds if you do.

---

## 4. Keys fail hard and late, and never prompt [verified]

`embeddings.py:94` / `:98` do `raise SystemExit("Set VOYAGE_API_KEY …")`. The messages
are genuinely good — actionable, and the OpenRouter-has-no-embeddings note at `:99`
pre-empts a real mistake. But:

- The check happens **at first use**, not upfront. `okf index` on a large vault can
  chunk everything and *then* die on a missing key.
- Nothing offers to *fix* it. The user is bounced to the shell to hand-export a var
  that, per §3, may not even reach the process that needs it.

**Fix — two pieces:**

**(a) `okf doctor` — the highest-leverage item in this report.**

The case is stronger than "nice for debugging". **Every finding above is a *silent*
failure.** §1 fails invisibly at client startup. §3 works in your terminal and fails
under MCP. §5 produces stale output with no error. §6 rewrites ids quietly. §8 stalls
without explanation. Not one of them announces itself — which is precisely how this
project ended up with a complete vault, enrichment, and index, and no registered server,
without anyone noticing.

That makes `doctor` not a convenience but the **general antidote to the kit's
characteristic failure mode**. It's tempting to scope it to newcomers doing a cold audit;
that's backwards. The user who configured everything last week is *more* exposed, because
they have no reason to suspect anything broke.

Concrete spec — each check maps to a finding above, and each is a step I ran by hand:

| Check | Catches |
|---|---|
| Resolved `okf` path (`shutil.which` vs `sys.executable`); warn if not on PATH | §1 |
| MCP registration status (`claude mcp list`), and whether the registered command still resolves | §1 |
| Config found + parses; `serve:` block present or defaulted | §2 |
| Key **presence** — never echo values — *and where each key came from* | §3, §4 |
| Vault present, note count by type, wikilinks resolve | — |
| `enrichment.json` present; older than sources? | §5 |
| Index present; `_newer_than()` → fresh/stale | §5 |
| Resolved provider + model for enrich and for embeddings | §4, §7 |
| Local embedding model cached, or cold (first search will download ~30 MB) | §8 |

**The trap inside the fix — do not skip this.** A naive `doctor` reads `os.environ` and
prints `VOYAGE_API_KEY: ✓ set`. Run from the user's shell, that is **actively
misleading**: it reports the key the *shell* can see, which is not what a client-spawned
`okf serve` can see (§3). Such a `doctor` would confidently green-light the exact bug it
exists to catch. It must distinguish:

- **exported in this shell only** → CLI works, **MCP will fail** ⚠️
- **present in `.env` / a file the process loads** → both work ✓

Which is also the tell that §3 and §4 are one fix, not two: `doctor` can only report this
honestly once `.env` loading exists to report *about*.

**(b) Interactive prompt on missing key — with a hard constraint:**

> **Never prompt on stdin from `okf serve`.** stdin/stdout are the MCP transport
> (`mcp.py:323-331`, and the docstring at `cli.py:215` already flags stdout). A prompt
> there corrupts the protocol stream and hangs the client.

So gate prompting on `sys.stdin.isatty() and cmd not in ("serve",)`, and keep the
current `SystemExit` for every non-TTY path (CI, MCP, pipes). When it does prompt,
offer to persist to `.env` — which is what makes §3 and §4 compose into one fix rather
than two.

---

## 5. `enrich → build → index` ordering is load-bearing and undocumented [verified]

The dependency is real: `enrich` writes `enrichment.json`, `_build` consumes it
(`cli.py:84-88`), `index` reads the built vault (`cli.py:157-158`). Run them out of
order and you get **stale output, no error**. Nothing states the order — I inferred it
by reading `cli.py`. `README.md:39-46` shows `enrich` → `build` but never says why
order matters, and `index` isn't in that sequence at all.

Meanwhile **the staleness machinery already exists** — `mcp.py:209-224` `_newer_than()`
compares note mtimes to the index timestamp, and `vault_info` surfaces `stale`. It's
just not used anywhere in the CLI, where it would do the most good.

**Fix:** reuse `_newer_than` to warn (not fail) in the CLI:
- `okf build` → "enrichment.json is older than your sources; re-run `okf enrich`"
- `okf index` / `okf search` → "vault is newer than the index; re-run `okf index`"

Cheap, and turns a silent-wrong-answer into a nudge. Document the ordering as a
one-line pipeline in the README (`enrich → build → index → serve`), since it's the
kit's central workflow and currently has to be reverse-engineered.

---

## 6. Enrichment silently rewrites node ids [verified]

Canonicalization changes ids. `book_adapter.py:110` emits `concept-progressive-trust`;
the enriched vault has the note at `concept/progressive-trust.md`, and links point to
`[[progressive-trust]]`. The id in the adapter is **not** the id on disk.

**This is worse than undocumented — the docs actively promise the opposite, in two
places, and one of them then demonstrates the feature that breaks the promise.**

- `README.md:80` — "`id` | stable unique id → **becomes the filename / wikilink target**"
- `docs/writing-an-adapter.md:23` — "`id` | ✅ | Stable, unique. **Becomes the filename
  and wikilink target.** Safe ids (`[A-Za-z0-9 _-.]`) are preserved verbatim; others are
  slugged."

That second one is the adapter-author's contract, stated as an exhaustive rule: ids are
either *preserved verbatim* or *slugged*. Canonicalization is a third outcome the
contract doesn't admit exists. And then **52 lines later, the same page's worked example
turns it on** (`writing-an-adapter.md:75`):

```yaml
enrich: { canonicalize_type: Concept, describe_types: [Chapter, "Case Study"] }
```

So the document teaches a rule and then, on the same page, hands you a config that
violates it — without noting the interaction. An adapter author who follows this page
end-to-end gets ids that don't match what the page told them to expect, which is exactly
the situation where you doubt your own adapter rather than the docs.

The behavior itself is arguably correct — it's what canonicalization *means*. The cost is
that it silently breaks anything holding an id: external scripts, saved queries,
bookmarks, and hand-written `[[wikilinks]]` in prose that isn't regenerated.

**Fix:** correct the `id` row in both files to state the `canonicalize_type` exception,
and annotate the worked example where it enables it. Consider having `okf enrich` print
an id-rewrite map (`concept-progressive-trust → progressive-trust`), and/or emit
`aliases:` covering the *old id* so stale wikilinks still resolve. (Aliases *are* already
written — `progressive-trust.md` carries `aliases: [progressive trust]` — but that's the
human-readable surface form, not the old id, so it doesn't help a stale
`[[concept-progressive-trust]]`.)

---

## 7. Local embedding quality — field evidence for an existing TODO [verified, one query]

Overlaps your existing TODO item *"Embeddings: evaluate `fastembed` (ONNX)"* — treat
this as supporting data, not a new finding.

Against this 54-note vault with the default `local` / `potion-base-8M`, the query
*"how should an agent earn more autonomy over time?"* — a near-paraphrase of Chapter
10's thesis (*Delegation and Progressive Trust*) — returned:

```
0.518  [Chapter] ch09-accountability-raci
0.509  [Chapter] ch14-servant-leadership
0.504  [Chapter] ch10-delegation-progressive-trust   ← the right answer, 3rd
0.502  [Chapter] ch16-understanding-organizational-structures
```

Right answer 3rd, and the whole spread is **0.016 wide**. That score compression is the
tell: a static embedding model in a topically homogeneous corpus (every note is about
agent management) has little room to discriminate. This is the regime where a
retrieval-tuned model earns its keep, and it's precisely the regime OKF vaults live in —
a vault is by construction a pile of closely-related notes.

**Caveat: one query, one vault. Not a benchmark.** But it suggests the eval should
weight *within-topic* discrimination rather than generic STS-style pairs, and that
`potion-base-8M`-as-default deserves a doc note ("zero-key default; expect soft ranking
on homogeneous vaults — set `provider: voyage` if retrieval feels vague") even before
`fastembed` lands.

---

## 8. First `okf_search` in a fresh env downloads ~30 MB inside the MCP process [verified stall / unverified stream]

**[verified]** The first search triggered a model2vec fetch — `Fetching 10 files: …` plus
`Warning: You are sending unauthenticated requests to the HF Hub…` — a multi-second
stall on a cold cache.

**[unverified, and the important half]** I could not determine whether that output goes
to **stdout**. My smoke test merged the streams (`2>&1`), and the cache is now warm so
it won't reproduce without a scratch `HF_HOME`. tqdm and HF warnings *conventionally*
use stderr, which would make this harmless — but `okf serve` is exactly the context
where being wrong is unrecoverable: **stdout is the MCP transport**, and one stray byte
corrupts the stream. Under stdio, a cold-cache first search is also a silent multi-second
hang, and offline it fails inside a tool call rather than at startup.

**Worth verifying explicitly** — it's cheap and the downside is bad:

```bash
HF_HOME=$(mktemp -d) .venv/bin/python -c "
from okfkit.serve.embeddings import make_embedder
make_embedder(provider='local').embed(['x'])" 2>/dev/null
# any output here = it reached stdout = MCP stream corruption under `okf serve`
```

If it does reach stdout, redirect it during `serve` (contextlib.redirect_stdout around
backend construction, or force `HF_HUB_DISABLE_PROGRESS_BARS=1`). Regardless: pre-warm
the model during `okf index` (where stdout is free and a stall is expected) so the
server never downloads mid-tool-call, and note the cold-start cost in the docs.

---

## 9. `adapter:` resolves against CWD; every other path resolves against the config [verified]

The config has three path-like values, and they don't agree on what they're relative to:

| Config key | Resolved against | Where |
|---|---|---|
| `output` | **config dir** | `config.py:20-23` via `cfg.resolve()` |
| `adapter_options.path` | **config dir** | `config.py:48-49` (special-cased by name) |
| `adapter` | **CWD** ⚠️ | never resolved; `base.py:59` `os.path.abspath()` |

`cli._load` passes `cfg.adapter` to `load_adapter` untouched, and `_import_from_path`
calls `os.path.abspath()` — which resolves against the **current working directory**, not
the config's directory. Verified: the same config file loads a different adapter, or
fails, depending on where you stand.

```
# config lives in wiki/, adapter file is wiki/book_adapter.py
$ cd book-project      && okf ... 'book_adapter.py:BookAdapter'  -> FileNotFoundError
$ cd book-project      && okf ... 'wiki/book_adapter.py:BookAdapter' -> OK
$ cd book-project/wiki && okf ... 'book_adapter.py:BookAdapter'  -> OK
```

Meanwhile `output: ./vault` in that same config resolves to `wiki/vault` from anywhere.
So `okf build` is CWD-independent in its output and CWD-dependent in its input.

This is documented *as relative* — `writing-an-adapter.md:72` shows
`adapter: examples/textbook/adapter.py:TextbookAdapter`, which only works from the repo
root. And `adapter_options.path` being resolved *by key name* (`config.py:48`) means the
textbook example's own `chapters_dir` option (`writing-an-adapter.md:73`) would **not**
be resolved — it works only because the example passes an absolute path.

Not what bit this project (its config uses absolute paths throughout — possibly a
workaround, possibly just caution; I can't tell). But it's a latent trap for exactly the
`okf serve` case, where **the client chooses the CWD**, not the user. A relative `adapter:`
that works in your terminal can fail under MCP for reasons that look like nothing.

**Fix:** resolve `adapter`'s path component against `base_dir` in `config.load()`, the
same way `output` is. For `adapter_options`, name-based special-casing doesn't scale —
either document that only `path` is resolved, or let adapters opt in (e.g. a
`PATH_OPTIONS = ("chapters_dir",)` class attribute the loader consults).

---

# Second pass — the engine and the zero-code quickstart

The findings above came from the setup/serve path. This second pass covers what the first
one explicitly disclaimed: `engine.py`, `render.py`, `model.py`, `markdown_folder.py`,
`rag.py`, `vault.py`, and the tests. **It found the three worst bugs in the report**, all
verified by execution, all on the built-in quickstart path — the one this book project
never used, because it has a custom adapter.

---

## 10. 🔴 `okf build` can delete arbitrary user files, silently, and report success [verified]

**The most severe finding here. This one destroys data that has nothing to do with the wiki.**

`engine.py:72-73` wipes the output directory with no guard whatsoever:

```python
if clean and os.path.isdir(output):
    shutil.rmtree(output)
```

Nothing checks that `output` is a vault, that it was generated by okf, that it isn't the
source folder, or that it isn't the config's own directory. `config.resolve()` happily maps
`output: .` to the directory the config lives in. So a one-character config edit turns
`okf build` into `rm -rf` on your project.

Verified, in a throwaway temp project containing `notes/`, `okf.config.yaml`, and an
unrelated `thesis.docx`:

| `output:` | Result |
|---|---|
| `./vault` | ✅ normal build, nothing lost |
| `./notes` (= source) | ⚠️ source folder wiped and replaced in-place. Content survives *only* because the adapter had already read it into memory; frontmatter and structure are silently rewritten. |
| `.` (config's dir) | 🔴 **`okf.config.yaml` and `thesis.docx` both deleted.** `build` then printed a normal success summary. |

```
=== C. output: .  (the config's own directory) ===
  before: ['alpha.md', 'beta.md', 'okf.config.yaml', 'thesis.docx']
  build -> completed
  after:  ['alpha.md', 'beta.md', 'index.md', 'index.md']
  *** DESTROYED: ['okf.config.yaml', 'thesis.docx'] ***
```

`thesis.docx` is the point: **an unrelated file, in a folder the user merely pointed at,
gone without a prompt, a warning, or a non-zero exit.** The build then reports success,
because from the engine's perspective nothing failed.

Note this isn't an unknown behavior — `docs/roadmap.md:26-27` says "The index is stored
*alongside* your config, never inside the vault (a rebuild wipes vault output)." The wipe
is deliberate and `.okf/` was deliberately protected from it. **The gap is that the user
was never protected from aiming it at the wrong place.** The shipped defaults
(`output: ./vault` in both the init template and the example) are safe, so you only reach
this by editing the config — which is exactly what every real project does.

**Fix — a marker file is the robust general guard (~5 lines):**

```python
MARKER = ".okf-vault"

if clean and os.path.isdir(output):
    if os.listdir(output) and not os.path.exists(os.path.join(output, MARKER)):
        raise SystemExit(
            f"Refusing to wipe {output}: it is not an okf-generated vault "
            f"(no {MARKER} marker) and is not empty. Delete it yourself if you "
            f"really mean to, or point `output:` somewhere else.")
    shutil.rmtree(output)
os.makedirs(output, exist_ok=True)
open(os.path.join(output, MARKER), "w").close()   # claim it for future builds
```

This is strictly better than blacklisting specific paths: it fails safe on *every*
not-a-vault directory, including ones nobody thought to enumerate. Add cheap explicit
checks too (`output` == `base_dir`, == `adapter_options.path`, or an ancestor of either),
since those give better error messages. Also worth honoring `clean: false` from the config
— it's already a `build()` kwarg (`engine.py:52`) but no config key exposes it.

---

## 11. 🔴 A source note named `index.md` is silently dropped from the vault [verified]

**Triggered by what is plausibly the single most common filename in a notes folder.**

Two code paths collide:

1. `markdown_folder.py:29` — `node_id = str(fm.get("id") or f.stem)`, so `index.md` → id `index`, written to `vault/note/index.md` (`engine.py:81-84`, step 4).
2. `engine.py:190` — `_write_type_indexes` writes the generated per-type index to `os.path.join(output, folder, "index.md")` — **the same path** — in step 5, *after* the nodes.

Last writer wins. The user's note is overwritten by a generated index. Verified:

```
adapter emitted ids: ['index', 'other']
build -> OK (no error), counts: {'Note': 2}      <-- claims 2 Note nodes
build reports total_files: 3

--- contents of vault2/note/index.md ---
  | type: Index
  | title: Note Index
  | # Note index
  | 2 note node(s).
  | - [[index|My Home Page]]                      <-- links to ITSELF, titled with the note it destroyed
  | - [[other|Other]]

--- did the hand-written note survive the build? ---
  *** NOT FOUND: the hand-written note was silently overwritten ***
```

Every layer reports success. `counts` says 2 Note nodes. `okf validate` passes, because
`known` (`engine.py:92`) contains `"index"` unconditionally, so the self-link resolves.
The generated index cheerfully lists `[[index|My Home Page]]` — a link that points at the
file that replaced the note, carrying the dead note's title.

**Precisely what is and isn't lost:** the *source* file (`notes/index.md`) is untouched —
this is not destruction of originals, and a fixed rebuild recovers it. What's lost is its
presence in the vault, and the loss is undetectable from any output the kit produces. So
it's silently-wrong rather than catastrophic — but the user has no way to notice.

`_unique_basename` (`engine.py:118-126`) exists precisely to resolve basename collisions,
but its `taken` map only ever contains *node* ids. Generated index filenames are never
registered in it, so it cannot see this collision.

**Fix:** seed `taken` with the reserved names before assigning node basenames — `"index"`
for every type folder, plus root `index`. The user's note then becomes `index-2.md` and
survives. That's a two-line change at the `_basename_stream` call site, and it composes
with the existing collision suffixing. Consider warning when it fires (`note 'index'
renamed to 'index-2' to avoid the generated type index`), since it silently changes a
wikilink target — and any inline `[[index]]` in the user's other notes would still point
at the generated index. That caveat deserves a line in the docs regardless.

The adapter already skips `readme.md` (`markdown_folder.py:26-27`), which shows this class
of problem was anticipated — just for the wrong filename. `index.md` is far likelier in a
notes folder than `README.md`.

---

## 12. 🟠 `markdown_folder` hard-crashes on any nested folder with repeated filenames [verified]

`markdown_folder.py:25` recurses (`root.glob("**/*.md")`) but derives ids from `f.stem`
(`:29`), which discards the directory. So the very common shape below is a hard failure:

```
adapter emitted ids: ['notes', 'notes']
build -> ValueError: Duplicate node id: 'notes'. Adapter must emit unique ids.
```

That was `projects/notes.md` + `archive/notes.md`. Any repeated filename does it:
`index.md`, `todo.md`, `notes.md`, `2024/summary.md` + `2025/summary.md`. Real note
collections are *full* of these — it's what folders are for.

`README.md:26-27` promises "Point the built-in *markdown-folder* adapter at **any folder**
of `.md` files". For any nested folder with a repeated basename, that's false, and the
error blames the adapter ("Adapter must emit unique ids") for what is really a built-in
adapter's own design choice. A new user reading that has no idea what to do next.

**Fix — pick one and document it:**
- **Derive ids from the relative path** (`projects/notes` → `projects-notes`, or keep the
  slash). Preserves uniqueness, but breaks the adapter's stated contract that filenames are
  preserved so inline `[[wikilinks]]` keep resolving (`markdown_folder.py:5-6`) — a real
  tension worth deciding deliberately rather than by default.
- **Disambiguate only on collision** (first `notes` wins, second becomes `archive-notes`).
  Keeps flat vaults working exactly as today; only nested collisions change. Probably the
  right call, and mirrors `_unique_basename`'s existing suffixing philosophy.
- **At minimum**, catch it in the adapter and raise a message that names *both files* and
  explains the fix, instead of surfacing a generic engine error.

Either way, add `default_type`/nesting to the docs — `README.md`'s "any folder" needs a
caveat, or the bug needs to go.

---

## 13. §7 revisited — the ranking code is correct; the mechanism is mean-pooling [upgraded]

§7 flagged weak retrieval and honestly noted I hadn't read the ranking code, so "the model
is weak" and "the ranking has a bug" were equally consistent with my one data point. **I've
now read it, and can retire the second hypothesis.**

`rag.py:237-260` is a textbook brute-force cosine search: L2-normalize the query
(`_normalize`, `:271-277`), `scores = self.vectors @ q`, `argsort(-scores)`, dedupe to the
best chunk per note. Vectors are normalized at build time too (`:227`). **There is no bug
here.** `_check_compat` (`:262-268`) even prevents querying an index with a mismatched
model — a good guard.

So the weak ranking is the model, and reading `chunk_notes` explains *why* specifically:

- `potion-base-8M` is a **static** model — model2vec produces one vector by **mean-pooling
  token embeddings**. There's no attention, no contextualization.
- `chunk_notes` (`rag.py:71-72`) keeps a note whole up to `chunk_max_chars`, **default
  4000** (`okf.config.example.yaml:58`).
- Mean-pooling 4000 characters of prose drags every vector toward the corpus centroid. The
  longer the chunk, the more averaging, the less any chunk distinguishes itself.

That is exactly the 0.016-wide score spread I measured. It's not bad luck on one query —
it's the arithmetic.

**The actionable insight: the two defaults are individually reasonable and pathological
together.** `chunk_max_chars: 4000` is sensible for a contextual model. `provider: local`
is a sensible zero-key default. Combined, they mean-pool 4000 chars into one vector and
call it retrieval. This book's vault hit it — 49 indexed notes became 85 chunks, so the
chapters *are* being split, into pieces right at the pathological size.

**Cheapest experiment before touching `fastembed`:** re-index this vault at
`chunk_max_chars: 800`–`1200` and re-run the §7 query. Smaller chunks mean less averaging;
if the spread widens and Chapter 10 climbs, the fix is a provider-conditional default
(local → ~1000, hosted → 4000) rather than a new dependency. That's a config change and one
`okf index` run — worth doing before the ONNX work in TODO.

**Minor, same area:** `_split_at_headings`'s docstring (`rag.py:103-107`) promises "no chunk
blows past embedding-model input limits", but the prefix is added *after* splitting
(`:75`), so a chunk's embedded text is up to `max_chars + len(prefix)`. The whole-note path
(`:71`) *does* account for the prefix. Small inconsistency; the docstring is the thing
that's wrong.

---

## 14. Test coverage — 25 tests, and the bugs live exactly where it stops [verified]

The suite is better than I expected: 25 tests, sensible fakes (`FakeEmbedder`), an
in-process MCP round-trip (`test_serve_mcp.py:272`), and a test asserting the index lands
next to the config rather than in the vault (`test_serve_rag.py:210`) — pinning the exact
invariant `roadmap.md` cares about. `test_engine.py` covers duplicate ids, link inference,
unresolved links, and canonicalization merges.

But **`markdown_folder` — the zero-code quickstart, the kit's headline feature — has exactly
one test** (`test_adapters.py:6-19`), against a flat directory with two uniquely-named files
and no edge cases. That single `notes.mkdir()` (`:8`) is the entire input topology under
test. Grep confirms: no test anywhere uses a nested notes folder, and no test builds a node
named `index`.

Every bug in this second pass is one test away:

```python
def test_markdown_folder_nested_duplicate_stems(tmp_path):   # §12
def test_source_note_named_index_survives_build(tmp_path):   # §11
def test_build_refuses_to_wipe_a_non_vault_directory(tmp_path):  # §10
```

`test_engine.py:32` (`test_duplicate_ids_rejected`) tests the *engine* raising on duplicate
ids — but nothing tests the built-in adapter *producing* them, which is the path a real user
actually walks. That gap is the whole story of §12.

`CONTRIBUTING.md:30` already says "Add a test for new engine behavior or a new built-in
adapter" — the convention is right; the built-in adapter just predates the habit.

---

## 15. 🔴 The hand-rolled YAML emitter writes invalid YAML for backslashes and newlines [verified]

`render.yaml_scalar` (`render.py:24-33`) hand-rolls YAML escaping. Two defects:

1. **The quote-trigger regex omits `\n`** (`render.py:29`), so a value containing a newline
   is emitted **unquoted** and structurally breaks the frontmatter block.
2. **The quoting path escapes `"` but not `\`** (`render.py:32`:
   `'"' + s.replace('"', '\\"') + '"'`), so `C:\path` becomes `"C:\path"` — and `\p` is not
   a valid YAML escape.

Verified by round-tripping `render.frontmatter()` back through `yaml.safe_load`:

| value | result |
|---|---|
| `Fair, reasonable, and clear.` | ✅ round-trips |
| `Jidoka: autonomation with a human touch.` | ✅ round-trips |
| `He said "stop the line" immediately.` | ✅ round-trips |
| `Kaizen — 改善 — continuous improvement.` | ✅ round-trips |
| `Use the C:\path\to\file convention.` | 🔴 **ScannerError** |
| `Escape it as \"quoted\" text.` | 🔴 **ParserError** |
| `First line.\nSecond line.` | 🔴 **ScannerError** |

```
---
type: Concept
description: "Use the C:\path\to\file convention."     <-- \p is not a valid YAML escape
---
```

**Why this is reachable, not theoretical.** `description` values are written by an LLM
(`okf enrich` → `enrichment.json` → `engine._apply_descriptions` → frontmatter). Nothing
constrains what the model returns. A description mentioning a Windows path, a regex, a
LaTeX command (`\alpha`), or an escape sequence produces an unparseable vault. Adapters can
also pass arbitrary frontmatter straight through (`model.py:35` — "may contain wikilinks",
and anything else).

**The failure chain is maximally unhelpful:**

1. `okf build` succeeds — it only *writes* the YAML, never parses it.
2. **`okf validate` passes** — it counts types with a regex (`engine.py:348`) and finds
   wikilinks textually. It never parses frontmatter. So the kit's own correctness check
   green-lights a broken vault.
3. `okf index` / `okf serve` → `load_vault` → `split_frontmatter` → `yaml.safe_load`
   (`render.py:105`) with **no try/except** → uncaught `ScannerError`.
4. The traceback **doesn't name the offending file**, because `load_vault` (`vault.py:46-53`)
   doesn't wrap per-file parsing. Under `okf serve` this kills the server at startup with a
   raw YAML traceback and no clue which note is at fault.

Same silent-failure signature as §10/§11: the thing that should catch it reports success.

**Fix — stop hand-rolling it.** The module docstring calls these helpers "deliberately
dependency-free" (`render.py:3`), but **PyYAML is a hard core dependency**
(`pyproject.toml:22-24`), and `split_frontmatter` already imports it (`render.py:103`). The
zero-dep constraint doesn't apply here; the emitter is a leftover from the "original one-off
generator" (`render.py:4`). Use `yaml.safe_dump(fields, sort_keys=False, allow_unicode=True)`
— it preserves insertion order, keeps `改善` readable, and is correct by construction.
Expect one-time formatting churn in rebuilt vaults; worth it.

**If you'd rather keep the emitter** (minimal, 2 lines):

```python
if re.search(r'[:#\[\]{}",&*?|<>=!%@`\\\n]', s) or s[0] in "-?:," or s.lower() in (...):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
```

Escape order matters — backslashes first, or you double-escape the escapes.

**Regardless of which fix:** wrap the per-file parse in `vault.load_vault` so a bad note
raises `SystemExit(f"{path}: invalid YAML frontmatter: {exc}")` instead of a bare traceback.
That's the difference between a five-minute fix and an afternoon.

`test_render.py:11` (`test_frontmatter_ordering_and_quoting`) tests quoting, but evidently
not backslashes or newlines — another one-test-away gap, same shape as §14.

---

## 16. Minor observations (recorded, not urgent)

Things noticed while reading that don't warrant their own section, captured so they aren't
lost:

- **`_strip_link_sections` silently drops hand-written link lists** (`rag.py:86-100`). Any
  `##` section whose content is *entirely* wikilink bullets is excluded from the index. For
  generated sections that's the intent; a user's hand-written "## Reading list" of pure
  links vanishes from search with no signal. Arguably correct, undocumented either way.
- **Canonicalization discards the non-first member's frontmatter** (`engine.py:277`:
  `canon.frontmatter = dict(members[0].frontmatter)`). Aliases, tags and links are merged
  across all members; frontmatter is taken from `members[0]` alone and the rest is dropped
  silently. Fine when members are near-duplicates, lossy when they aren't.
- **`validate_vault` counts types with a regex over the whole file** (`engine.py:348`:
  `re.search(r"^type:\s*(.+)$", ..., re.M)`), not just the frontmatter block. Harmless today
  — frontmatter is at the top so the first match wins — but it also re-reads each file it
  just read (`:341-349`), and a body line starting with `type:` is a latent miscount.
- **`engine.build()` mutates the `Node`s it's given** — `_infer_links` appends to `n.links`
  (`:242,245`) and `_apply_descriptions` writes `n.frontmatter` (`:256`). Only `list(nodes)`
  is copied (`:54`), not the nodes. Harmless via the CLI (fresh load each run) and roughly
  idempotent thanks to the `any(l.target == ...)` guards, but `engine.build` is public API
  documented in the README — a library caller reusing a node list gets surprises.
- **`_basename_stream`** (`engine.py:111-115`) yields the same mutable `taken` dict on every
  iteration so a dict-comprehension can thread state through `_unique_basename`. It works,
  but it's a confusing way to write a loop — and §11's fix touches exactly this code.

---

## Ready-to-paste TODO.md entries

Phrased in TODO.md's existing idiom and grouped under its current headings.

### Known issues / bugs
- [ ] 🔴 **`okf build` can `rm -rf` arbitrary user files and report success.**
  `engine.py:72-73` does an unguarded `shutil.rmtree(output)`. `output: .` resolves to the
  config's own directory (`config.py:20-23`) — verified to delete `okf.config.yaml` and an
  unrelated `thesis.docx`, then print a normal build summary. Guard with an `.okf-vault`
  marker file (refuse to wipe any non-empty dir without it) + explicit checks for
  `output` == `base_dir` / `adapter_options.path`. Also expose the existing `clean=False`
  kwarg (`engine.py:52`) as a config key. **Fix before the next release.**
- [ ] 🔴 **A source note named `index.md` is silently dropped from the vault.**
  `markdown_folder.py:29` gives it id `index`; `_write_type_indexes` (`engine.py:190`)
  overwrites the same path in step 5. Build reports the node in `counts`, `okf validate`
  passes (`engine.py:92` whitelists `index`), and the generated index links to itself with
  the destroyed note's title. Fix: seed `_unique_basename`'s `taken` map with the reserved
  index names before assigning basenames (`engine.py:62`), and warn on rename.
- [ ] 🔴 **The hand-rolled YAML emitter writes invalid YAML.** `render.yaml_scalar`
  (`render.py:24-33`) omits `\n` from its quote-trigger regex and never escapes `\`, so an
  LLM-written `description` containing a backslash, a newline, or a LaTeX command produces
  an unparseable vault. `okf build` succeeds, **`okf validate` passes** (it never parses
  frontmatter — `engine.py:348` uses a regex), then `okf index`/`serve` die in
  `yaml.safe_load` (`render.py:105`, no try/except) with a traceback that doesn't name the
  file. Fix: use `yaml.safe_dump(fields, sort_keys=False, allow_unicode=True)` — PyYAML is
  already a hard core dep (`pyproject.toml:22-24`), so the "dependency-free" note at
  `render.py:3` doesn't apply. Also wrap the per-file parse in `vault.load_vault` so bad
  notes are named. `test_render.py:11` tests quoting but not these cases.
- [ ] 🟠 **`markdown_folder` hard-crashes on nested folders with repeated filenames.**
  Globs `**/*.md` (`:25`) but ids from `f.stem` (`:29`) → `projects/notes.md` +
  `archive/notes.md` → `ValueError: Duplicate node id: 'notes'`. `README.md:26-27` promises
  "any folder of .md files". Disambiguate on collision, or derive ids from the relative
  path (tension: breaks the preserve-filenames-so-inline-links-resolve contract at
  `markdown_folder.py:5-6` — decide deliberately).
- [ ] **`okf serve` prints an unusable `claude mcp add` hint.** `cli.py:222,226` (and
  `README.md:94`) emit a bare `okf`, which isn't on PATH for the documented
  `pip install -e .` venv install — the command fails, and only surfaces as a broken
  server at client startup. Emit `{sys.executable} -m okfkit.cli serve …` instead.
- [ ] **`okf init` scaffolds a config with no `serve:` block.** `_CONFIG_TEMPLATE`
  (`cli.py:253-271`) predates Phases 7/8 and silently disagrees with
  `okf.config.example.yaml`; users scaffolded by `init` get no hint that `index`/`serve`
  exist. Render init from the example + add a key-parity test.
- [ ] **MCP servers don't inherit shell env → `okf_search` fails under hosted embedding
  providers.** Keys exported in a shell never reach a client-spawned `okf serve`; the
  resulting error surfaces via `mcp.py:183` as a "could not load index" message that
  points at the wrong cause. Verify with a voyage-configured server; add a
  key-specific message. (Masked today by `provider: local`.)
- [ ] **Relative `adapter:` paths resolve against CWD, not the config dir.** `output` and
  `adapter_options.path` resolve against `base_dir` (`config.py:20-23,48-49`); `adapter`
  is passed through unresolved and hits `os.path.abspath()` at `base.py:59`. Same config,
  different CWD, different adapter — and `writing-an-adapter.md:72` documents the relative
  form. Latent trap under `okf serve`, where the *client* picks the CWD. Resolve it in
  `config.load()`.

### Enhancements
- [ ] **`.env` support.** Load `.env` (cwd → config dir → upward) in `cli.main()`.
  Prerequisite for the MCP env-inheritance fix above. Keep the PyYAML-only core:
  hand-roll the ~10-line parser or make `python-dotenv` an optional dep. (It's already
  present transitively via `mcp` → `pydantic-settings`, but unreferenced.)
- [ ] **`okf doctor`.** One-shot preflight: resolved `okf` path, MCP registration status,
  config, vault + note count, enrichment/index freshness (`_newer_than()`), resolved
  providers, key *presence* (never values), local-model cache warm. Every bug in this
  report is a silent failure — this is the general antidote, and the highest-leverage
  item here. **Must report where each key came from** (exported-in-shell → MCP will still
  fail; loaded from `.env` → actually works): a `doctor` that just reads `os.environ`
  would green-light the very bug it exists to catch. Pairs with `.env` support; see §4(a)
  for the full check-list.
- [ ] **`okf serve --register` / `okf install-mcp`.** Run `claude mcp add` with the
  correct absolute interpreter path and echo what it ran. Removes the last hand-assembled
  step — the one that failed in the field.
- [ ] **Interactive key prompt, TTY-gated, offering to persist to `.env`.** MUST NOT
  prompt from `okf serve` (stdin/stdout are the MCP transport, `cli.py:215`,
  `mcp.py:323-331`) or any non-TTY context; keep the current `SystemExit` there.
- [ ] **Surface staleness in the CLI.** `_newer_than()` (`mcp.py:209-224`) already exists
  and is only used by `vault_info`. Warn on `build` (enrichment.json older than sources)
  and `index`/`search` (vault newer than index). Silent-stale is the current failure mode.
- [ ] **Pre-warm the local embedding model during `okf index`.** Avoids a ~30 MB
  cold-cache download inside a `serve` tool call; verify first whether HF/tqdm output
  reaches stdout (would corrupt the MCP stream — see §8 for the one-liner).

### Testing / CI
- [ ] **Test the built-in adapter past the happy path.** `markdown_folder` — the headline
  zero-code feature — has exactly one test (`test_adapters.py:6-19`): a flat dir, two
  uniquely-named files. No test anywhere uses a nested notes folder or a node named
  `index`, which is exactly where §10/§11/§12 live. Add: nested duplicate stems, a source
  note named `index.md` surviving a build, and a build refusing to wipe a non-vault
  directory. (`CONTRIBUTING.md:30` already asks for this; the built-in adapter predates
  the habit.)
- [ ] **Pin the register hint with a test.** Assert the executable in the printed
  `claude mcp add` command actually resolves — otherwise §1 regresses the moment someone
  tidies it back to a bare `okf`.

### Docs / packaging
- [ ] **Document the `enrich → build → index → serve` ordering.** It's load-bearing
  (`cli.py:84-88`, `157-158`) and produces stale-but-silent output when violated;
  currently only inferable by reading `cli.py`.
- [ ] **The docs promise `id` → filename, then demonstrate the feature that breaks it.**
  `README.md:80` and `writing-an-adapter.md:23` both state ids are preserved-or-slugged;
  canonicalization is an undocumented third outcome — and `writing-an-adapter.md:75`'s own
  worked example enables `canonicalize_type: Concept` 52 lines after stating the rule. Fix
  the `id` row in both, annotate the example, and consider printing an id-rewrite map from
  `okf enrich` (+ aliasing the *old id* so stale wikilinks resolve).
- [ ] **Note the `local` embeddings quality tradeoff** where the default is documented —
  zero-key, but soft ranking on topically homogeneous vaults (see §7). Suggest
  `provider: voyage` as the upgrade path.

---

## What worked well (worth not regressing)

- **`VaultService` is MCP-free** (`serve/mcp.py:45`). The entire server was verifiable in
  one `python -c` with no MCP client. This is why diagnosing the MCP path took minutes.
- **Error messages carry the fix.** `mcp.py:169-182` (`--no-rag` → what to run instead),
  `embeddings.py:99` (OpenRouter has no embeddings endpoint). The bad ones in this report
  are bad because they're *absent*, not because they're unclear.
- **`_missing()` returns `did_you_mean` suggestions** (`mcp.py:235-242`) — exactly right
  for an agent consumer that guessed an id.
- **Index sidecar in `.okf/` next to the config, never inside the vault** — correct, and
  the reasoning is written down in `docs/roadmap.md:26-27`. A rebuild wipes the vault; the
  index survives.
- **Read-only tool annotations** (`readOnlyHint=True`, `openWorldHint=False`, `mcp.py:278`)
  and body windowing with `next_offset` (`mcp.py:99-107`) — both show real thought about
  the agent consumer rather than just exposing functions.

---

## Scope and limits of this audit — read before trusting the silences

*Updated after the second pass. §§1–9 were written when most of the source was still
unread; that disclaimer is preserved below in case it explains any thinness up there.*

**Read in full:** `cli.py`, `config.py`, `model.py`, `render.py`, `engine.py`,
`adapters/base.py`, `adapters/markdown_folder.py`, `serve/mcp.py`, `serve/embeddings.py`,
`serve/rag.py`, `serve/vault.py`, `tests/test_engine.py`, `tests/test_adapters.py`,
`pyproject.toml`, `README.md`, `okf.config.example.yaml`, `CONTRIBUTING.md`, `TODO.md`,
`docs/roadmap.md`, `docs/writing-an-adapter.md`, plus the project's `okf.config.yaml` and
`book_adapter.py`.

**Executed, not just read:** the full `build → enrich → index → serve` pipeline on the book
vault; `VaultService` (`vault_info` / `search` / `neighbors`); `okf validate`; and four
purpose-built probes — CWD-relative adapter resolution (§9), the `markdown_folder`
quickstart edge cases (§11, §12), the unguarded `rmtree` (§10), and YAML round-tripping
(§15). The probes ran in temp dirs or in memory; **the book project was never mutated.**

**Still not read:**

- **`enrich.py` past line 75** — including the canonicalization batching and JSON parsing
  that is your current top TODO bug. No input on it. Note §6 (id rewrites) originates here
  and was diagnosed from *output plus `engine._apply_canonicalization`*, not from the
  prompt/batching side.
- **`tests/test_serve_mcp.py`, `tests/test_serve_rag.py`** (~530 lines) — I enumerated their
  test names and grepped them for specific coverage (nesting, `index`, `max_chars`) but did
  not read them line by line. §14's praise of them is based on names and structure, not a
  full read.
- **`examples/textbook/adapter.py`**, `.github/workflows/release.yml`, `markdown_folder`'s
  interaction with `link_inference` (untested combination).

**Known-unresolved:** §8's stdout question. I attempted the cold-cache download probe and
the command was declined, so **§8 remains explicitly unverified** — the one-liner is still
there for whoever picks it up.

**Single-sample caveats.** One real vault (54 notes, one domain, one custom adapter), one
machine, macOS only, Python 3.11. §7/§13 rest on one query — the *mechanism* is now
argued from source, but the measurement is still n=1. Nothing checked on Linux or Windows,
and PATH/env behavior — a large part of §§1–4 — is the most platform-sensitive thing in the
kit. The three second-pass bugs (§10–§12) are the exception: those are deterministic,
reproduced by execution, and platform-independent.

<details>
<summary>Original scope disclaimer, as written before the second pass</summary>

> **This report is not a code review.** It's a usability audit of the setup and serve path,
> biased by what a new session touches when asked "how do I use this?". Where it says
> nothing, that is usually because **I did not look**, not because I looked and found
> nothing. […] **`adapters/markdown_folder.py`** — ⚠️ the built-in zero-code adapter, i.e.
> the README's headline quickstart and the path most new users take. This project uses a
> custom adapter, so I never exercised it. **The most common new-user path is entirely
> unaudited in this report.**

That disclaimer turned out to be the most valuable paragraph in the first pass: every
finding in §§10–12 came from going back and auditing exactly what it named.

</details>

## Suggested sequencing

*Revised after the second pass — the data-loss bugs displace everything else.*

**Ship-blocking (do these before any release):**

1. **§10 unguarded `rmtree`** — `okf build` deleting an unrelated `thesis.docx` and printing
   success is the kind of bug that ends a tool's reputation. ~5 lines for the marker guard.
2. **§11 `index.md` silently dropped** — two lines (seed `taken` with reserved names), and it
   fires on one of the likeliest filenames a user will have.
3. **§15 invalid YAML from the emitter** — swap to `yaml.safe_dump`. Reachable through
   ordinary `okf enrich` output, and `okf validate` actively certifies the broken result.
4. **§12 nested-folder crash** — needs a design decision (see the tension noted in §12), but
   the status quo makes the headline quickstart false for most real note collections.
5. **Tests for all four**, per §14 — otherwise they come back.

**Then, the MCP/setup work (the original point of this report):**

6. **§1 register hint** — one line, and it's the thing that's actually broken in the field.
7. **§2 init template** — one commit, no design questions.
8. **§3 `.env` loading** → **§4(a) `okf doctor`** — in that order; `doctor` can't report key
   provenance honestly until `.env` exists.
9. **§5 staleness warnings** — `_newer_than()` already exists; just plumb it into the CLI.
10. **§6 + §9 docs and path resolution** — cheap, and §9 quietly de-risks `okf serve`.

**Needs measurement first, don't act on my numbers:**

11. **§13** — try `chunk_max_chars: 800`–`1200` with the local provider and re-run the §7
    query. Cheaper than the `fastembed` work already in TODO, and might obviate it.
12. **§8** — run the stdout one-liner. I never got to it; the command was declined.

§§1–2, §§10–11 and §15 are worth doing regardless of whether you accept any of the analysis:
they're demonstrable, reproduced bugs with fixes measured in lines.

**A note on §16.** Those are recorded for completeness, not because they need doing. If you
touch `_basename_stream` for §11, the last one becomes free.

## Reproduction context

- Kit: `okf-wiki-kit` 0.2.1, editable install, `okf-wiki-kit/.venv` (py3.11).
- Deps present: `mcp` 1.28.1, `numpy` 2.4.6, `model2vec` 0.8.2, `openai` 2.45.0, PyYAML 6.0.3.
- Project: `../wiki/` — `okf.config.yaml`, custom `book_adapter.py:BookAdapter`,
  `enrichment.json`, `vault/` (54 notes: 18 Chapter, 17 Concept, 9 Role Card, 5 Part,
  4 Index, 1 Home), `.okf/` (85 chunks, `local`/`potion-base-8M`, fresh).
- `okf validate`: all wikilinks resolve ✓.
- `claude mcp list`: **`okf-wiki` absent** — never registered (see §1).
- Env: `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `VOYAGE_API_KEY`
  all unset. Build/validate/index/search/serve still work (local embeddings, no key);
  `enrich`/`ask` cannot run.
