# Changelog

## v0.4.0 — 2026-07-19

Clears the remaining backlog after the v0.3.0 field-report fixes.

### Added
- `okf serve --transport http` (with `--host`/`--port`) — serves the MCP
  server over FastMCP streamable-http at `/mcp`. `stdio` remains the default
  and is byte-identical to before; `--register` always registers the stdio
  form (what MCP clients spawn).
- Opt-in integration tests (`tests/test_integration.py`) gated on
  `OKF_TEST_VAULT` (and `OKF_TEST_PROVIDER` for the embedding layer),
  exercising a real vault and real embeddings alongside the fake-based units.
- CI workflow (`.github/workflows/ci.yml`) running the full test matrix on
  every push and PR (Python 3.10–3.13), cancelling superseded runs.

### Fixed
- Enrichment canonicalization no longer loses whole batches to unparseable
  JSON: batch size dropped 100 → 30, a defensive `extract_json` (tolerates
  code fences, leading prose, and trailing commas), a self-repair retry that
  feeds the model back its own broken output plus the parse error, and a loud
  stderr warning when a batch still fails (instead of a silent fallback).
- `okf_search` under MCP now reports missing embedding keys correctly: the
  error names the key and the "MCP servers don't inherit your shell env" rule
  and points at `.env` / `okf doctor`, instead of the misleading
  "Could not load the semantic index" (field report §3, now verified).

### Changed
- Default Anthropic enrichment/ask model bumped `claude-sonnet-4-6` →
  `claude-opus-4-8` (still overridable via `--model`).
- Evaluated `fastembed` (ONNX) as a local embedding backend and **rejected**
  it: at 1000-char chunks, `potion-base-8M` beats `bge-small-en-v1.5` on
  within-topic top-1 accuracy (4/4 vs 2/4), embeds ~420× faster, and avoids
  ~96 MB of dependencies. `local` stays the default.
- Release process documented in CONTRIBUTING.md, including the `pypi`
  environment approval gate.
- Test suite: 119 → 144 (plus 9 opt-in integration tests).

## v0.3.0 — 2026-07-16

Fixes every finding from the first real-world field audit
([docs/FIELD-REPORT-v0.2.1.md](docs/FIELD-REPORT-v0.2.1.md)).

### Fixed (data loss / crashes)
- `okf build` refuses to wipe any non-empty directory that is not a marked okf
  vault (`.okf-vault` marker guard, plus explicit config-dir/source-dir checks);
  previously `output: .` silently deleted unrelated files and reported success.
- A source note named `index.md` survives builds as `index-2.md` (with a warning)
  instead of being silently overwritten by the generated type index.
- Frontmatter is emitted via `yaml.safe_dump` — values with backslashes, newlines,
  or LaTeX no longer produce unparseable vaults, and `load_vault` names the
  offending file on bad YAML instead of dying with a bare traceback.
- The `markdown_folder` adapter disambiguates repeated filenames in nested folders
  (`archive/notes.md` → `archive-notes`, warned) instead of crashing.
- The printed MCP register command uses the absolute interpreter path
  (`{python} -m okfkit.cli serve …`) — the bare `okf` form failed silently on
  non-activated-venv installs.
- Relative `adapter:` paths resolve against the config's directory, not the CWD.

### Added
- `okf doctor` — preflight for the kit's silent failure modes: executable
  resolution, MCP registration, config, API-key presence **and provenance**
  (shell-only export vs `.env`-loaded), vault validity, enrichment/index
  freshness, and local-model cache state.
- `okf serve --register` — runs `claude mcp add` with the correct absolute path
  and prints exactly what it ran.
- `.env` loading (stdlib-only) with real-environment-wins precedence, and a
  TTY-gated key prompt that offers to persist to `.env` (never under `serve`).
- Staleness warnings: `build` warns when `enrichment.json` is older than the
  sources; `search`/`ask` warn (on stderr) when the vault is newer than the index.
- `clean:` config key to disable the output wipe on rebuild.
- `okf enrich` prints an id-rewrite map when canonicalization changes ids.

### Changed
- `chunk_max_chars` now defaults per embedding provider — 1000 for `local`
  (static model; long mean-pooled chunks blur ranking), 4000 for hosted.
- `okf init`'s template is at key-parity with `okf.config.example.yaml`
  (including the `serve:` block).
- Docs: id/canonicalization contract corrected, `enrich → build → index → serve`
  ordering documented, MCP env-inheritance callout, local-embeddings tradeoff.
- Test suite: 25 → 119 tests.

## v0.2.1 — 2026-07-15
- Added the `[openrouter]` extra as an alias of `[openai]`.
- GitHub Actions release workflow (test-gated, PyPI Trusted Publishing).

## v0.2.0 — 2026-07-15
- Phase 7: semantic RAG — `okf index` / `okf search` / `okf ask`.
- Phase 8: read-only MCP server — `okf serve` with five tools.

## v0.1.0 — 2026-07-15
- Initial public release: adapter-based vault generation (`okf build`), LLM
  enrichment (`okf enrich`), validation (`okf validate`), `okf init`.
