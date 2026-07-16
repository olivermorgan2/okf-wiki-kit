# okf-wiki-kit — TODO

Running list of known fixes and planned updates. Check items off as they land;
add new ones under the right heading. Keep entries specific enough to act on.

## Enhancements
- [ ] **`okf search` vs `okf ask --no-llm`.** Decide whether to keep `search` as its own
  subcommand or fold it in (open design question from `docs/phase-7-8-plan.md`).
- [ ] **Local contextual embeddings — revisit with a retrieval-tuned model.** fastembed's
  bge-v1.5 (ONNX) was evaluated 2026-07-16 and **rejected**: at 1000-char chunks,
  potion-base-8M beats bge-small on within-topic top-1 (4/4 vs 2/4), embeds ~420× faster,
  and avoids ~96 MB of deps (onnxruntime etc.). If revisited, benchmark a retrieval-tuned
  model on within-vault queries — generic bge via ONNX isn't it.

## Recorded, not urgent (field report §16)
- `_strip_link_sections` silently drops hand-written all-wikilink sections from the
  semantic index (`rag.py`) — intended for generated sections, undocumented either way.
- Canonicalization keeps only `members[0]`'s frontmatter (`engine._apply_canonicalization`);
  aliases/tags/links are merged but other frontmatter from later members is dropped silently.
- `validate_vault` counts types with a regex over the whole file, not just the frontmatter
  block, and re-reads each file it just wrote — latent miscount if a body line starts
  with `type:`.
- `engine.build()` mutates the `Node`s it's given (`_infer_links`, `_apply_descriptions`);
  only the list is copied. Harmless via the CLI; a surprise for library callers.

## Done
- [x] **Enrich canonicalization hardened** — batch size 100 → 30 (`CANON_BATCH_SIZE`),
  `extract_json` (fences / leading prose / trailing commas, error with snippet), self-repair
  retry feeding the model its own broken output + parse error, loud stderr fallback warning.
  _(2026-07-16)_
- [x] **Voyage/openai MCP failure message verified + fixed** — the missing-key SystemExit was
  surfacing as "Could not load the semantic index"; `_load_failure_message` in `serve/mcp.py`
  now names the key, the env-inheritance rule, the `.env` remedy, and the still-working graph
  tools. _(2026-07-16)_
- [x] **MCP HTTP transport** — `okf serve --transport http --host --port` via FastMCP
  streamable-http (serves at `/mcp`); stdio default byte-identical; `--register` always
  registers stdio. _(2026-07-16)_
- [x] **`okf ask`/enrich default model bumped** — `claude-sonnet-4-6` → `claude-opus-4-8`
  (`enrich.DEFAULT_MODELS`; overridable via `--model`). _(2026-07-16)_
- [x] **fastembed evaluated → rejected** — see the revisit item above for the numbers.
  _(2026-07-16)_
- [x] **Integration tests against a real vault** — `tests/test_integration.py`, opt-in via
  `OKF_TEST_VAULT` (+ `OKF_TEST_PROVIDER` for the embedding layer); 9 tests, verified green
  against a real vault with real model2vec embeddings. _(2026-07-16)_
- [x] **CI on push/PR** — `.github/workflows/ci.yml`, mirrors the release test job + 3.13,
  cancels superseded runs. _(2026-07-16)_
- [x] **Release process documented** — CONTRIBUTING "Releasing" section incl. the `pypi`
  environment approval gate. _(2026-07-16)_
- [x] **CHANGELOG.md** — started with v0.1.0 → v0.3.0. _(2026-07-16)_
- [x] **Field report v0.2.1 fixes — data-loss and crash bugs** _(2026-07-16)_:
  `okf build` refuses to wipe non-vault directories (`.okf-vault` marker guard in
  `engine.py` + explicit config-dir/source-dir checks in `cli._build`, `clean:` config
  key exposed); a source note named `index.md` survives as `index-2.md` with a warning
  (reserved basename); frontmatter is emitted via `yaml.safe_dump` (backslashes, newlines,
  LaTeX all round-trip; `load_vault` names the offending file on bad YAML); the
  markdown_folder adapter disambiguates nested duplicate stems (`projects-notes`) instead
  of crashing. All covered by tests.
- [x] **Field report v0.2.1 fixes — setup/DX** _(2026-07-16)_: MCP register hint now uses
  `{sys.executable} -m okfkit.cli` (test-pinned); `okf serve --register` runs
  `claude mcp add` with the correct absolute path; `okf doctor` preflights executable,
  MCP registration, config, key presence **and provenance** (shell-only vs `.env`-loaded),
  vault, enrichment/index freshness, and local-model cache; `.env` loading
  (`okfkit/envfile.py`, stdlib-only) with real-env-wins precedence; TTY-gated key prompt
  offering to persist to `.env` (never under `serve`); staleness warnings on
  `build`/`search`/`ask` via `okfkit/freshness.py`; `okf init` template at parity with the
  example config (test-pinned); relative `adapter:` paths resolve against the config dir;
  `okf enrich` prints an id-rewrite map when canonicalization changes ids.
- [x] **Field report v0.2.1 fixes — docs** _(2026-07-16)_: id/canonicalization contract
  corrected in README + writing-an-adapter; `enrich → build → index → serve` ordering
  documented; MCP env-inheritance callout; local-embeddings quality tradeoff; nested-folder
  and `index.md` caveats.
- [x] **Fix Node.js 20 deprecation in `release.yml`** — bumped `actions/checkout@v5` and
  `actions/setup-python@v6` (Node 24). _(2026-07-15)_
- [x] **Add `[openrouter]` extra** as an alias of `[openai]` (v0.2.1). _(2026-07-15)_
- [x] **Token-less releases** — `release.yml` (test-gated) + PyPI Trusted Publishing. _(2026-07-15)_
- [x] **Phase 7 (semantic RAG)** — `okf index` / `search` / `ask` (v0.2.0). _(2026-07-15)_
- [x] **Phase 8 (MCP server)** — `okf serve` + five read-only tools (v0.2.0). _(2026-07-15)_
