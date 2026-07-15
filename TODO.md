# okf-wiki-kit — TODO

Running list of known fixes and planned updates. Check items off as they land;
add new ones under the right heading. Keep entries specific enough to act on.

## Known issues / bugs
- [ ] **`enrich.py` concept canonicalization fails to parse on large batches.** With
  `claude-sonnet-4-6`, 100-concept batches have returned unparseable JSON on every batch,
  leaving concepts unmerged (non-fatal — falls back to keeping them separate). Harden:
  smaller batch size, more robust JSON extraction / repair, and/or a retry that asks the
  model to fix its own JSON.

## Enhancements
- [ ] **`okf ask` default model.** Currently defaults to `claude-sonnet-4-6` (overridable via
  `--model`). Revisit whether to bump the default.
- [ ] **MCP: optional HTTP transport.** Server is stdio-only today; FastMCP supports
  `streamable-http` with no architecture change — expose a `--transport http` flag.
- [ ] **Embeddings: evaluate `fastembed` (ONNX).** As an alternative/higher-quality local
  backend vs `model2vec`, still dependency-light (no torch).
- [ ] **`okf search` vs `okf ask --no-llm`.** Decide whether to keep `search` as its own
  subcommand or fold it in (open design question from `docs/phase-7-8-plan.md`).

## Testing / CI
- [ ] **Integration tests against a real vault.** Opt-in (`OKF_TEST_VAULT` + `skipif`) tests
  exercising real embedding providers and a full-size vault, complementing the fake-based
  unit tests.
- [ ] **CI on push/PR.** A test workflow that runs on every push/PR (not only on release),
  so regressions are caught before tagging.

## Docs / packaging
- [ ] **CHANGELOG.md.** Start a changelog (v0.1.0 → 0.2.0 RAG+MCP → 0.2.1 `[openrouter]`).
- [ ] **Document the release process.** Note the tag → GitHub Release → Trusted-Publishing
  flow in CONTRIBUTING.

## Done
- [x] **Fix Node.js 20 deprecation in `release.yml`** — bumped `actions/checkout@v5` and
  `actions/setup-python@v6` (Node 24). _(2026-07-15)_
- [x] **Add `[openrouter]` extra** as an alias of `[openai]` (v0.2.1). _(2026-07-15)_
- [x] **Token-less releases** — `release.yml` (test-gated) + PyPI Trusted Publishing. _(2026-07-15)_
- [x] **Phase 7 (semantic RAG)** — `okf index` / `search` / `ask` (v0.2.0). _(2026-07-15)_
- [x] **Phase 8 (MCP server)** — `okf serve` + five read-only tools (v0.2.0). _(2026-07-15)_
