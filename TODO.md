# okf-wiki-kit — TODO

Running list of known fixes and planned updates. Check items off as they land;
add new ones under the right heading. Keep entries specific enough to act on.

## Known issues / bugs
- [ ] **`enrich.py` concept canonicalization fails to parse on large batches.** With
  `claude-sonnet-4-6`, 100-concept batches have returned unparseable JSON on every batch,
  leaving concepts unmerged (non-fatal — falls back to keeping them separate). Harden:
  smaller batch size, more robust JSON extraction / repair, and/or a retry that asks the
  model to fix its own JSON.
- [ ] **Verify the voyage-configured MCP failure message.** Field report §3 (unverified):
  a missing key in a client-spawned `okf serve` likely surfaces via `mcp.py` as a
  "could not load the semantic index" error that points at the wrong cause. Largely
  mitigated now by `.env` loading + `okf doctor`, but worth confirming with a real
  voyage-configured server and adding a key-specific message if confirmed.

## Enhancements
- [ ] **`okf ask` default model.** Currently defaults to `claude-sonnet-4-6` (overridable via
  `--model`). Revisit whether to bump the default.
- [ ] **MCP: optional HTTP transport.** Server is stdio-only today; FastMCP supports
  `streamable-http` with no architecture change — expose a `--transport http` flag.
- [ ] **Embeddings: evaluate `fastembed` (ONNX).** As an alternative/higher-quality local
  backend vs `model2vec`, still dependency-light (no torch). Measured 2026-07-16 (field
  report §13 follow-up, 18-chapter rebuilt vault): 1000-char chunks with the local model
  sharpened top-1 margins on 3 of 4 queries and never hurt top-1 — so the default is now
  provider-conditional (`local` → 1000, hosted → 4000; `cli._chunk_max_chars`). That is
  mitigation, not the fix; a contextual model is still the real upgrade. §8 was also
  measured: the cold-cache HF download writes only to stderr — no MCP-stream risk.
- [ ] **`okf search` vs `okf ask --no-llm`.** Decide whether to keep `search` as its own
  subcommand or fold it in (open design question from `docs/phase-7-8-plan.md`).

## Testing / CI
- [ ] **Integration tests against a real vault.** Opt-in (`OKF_TEST_VAULT` + `skipif`) tests
  exercising real embedding providers and a full-size vault, complementing the fake-based
  unit tests.
- [ ] **CI on push/PR.** A test workflow that runs on every push/PR (not only on release),
  so regressions are caught before tagging.

## Docs / packaging
- [ ] **Document the release process.** Note the tag → GitHub Release → Trusted-Publishing
  flow in CONTRIBUTING.

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
