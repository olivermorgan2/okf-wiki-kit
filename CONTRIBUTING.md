# Contributing to okf-wiki-kit

Thanks for your interest! This project aims to stay small, dependency-light, and easy to extend.

## Development setup

```bash
git clone https://github.com/olivermorgan2/okf-wiki-kit
cd okf-wiki-kit
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,openai,anthropic]"
pytest
```

## Project layout

- `okfkit/model.py` — the `Node` / `Link` data model (the contract between adapters and the engine).
- `okfkit/render.py` — pure helpers: slugs, YAML frontmatter, wikilinks, file writing.
- `okfkit/engine.py` — the generic build: render, indexes, link inference, validation.
- `okfkit/enrich.py` — optional LLM pass (canonicalize a node type + write descriptions).
- `okfkit/adapters/` — `base.py` (the `SourceAdapter` ABC) and built-in adapters.
- `okfkit/cli.py`, `okfkit/config.py` — the `okf` command and config loading.
- `examples/` — worked example adapters.
- `tests/` — pytest unit tests.

## Guidelines

- **Keep the core generic.** Domain knowledge belongs in *adapters*, never in the engine.
- **Minimize dependencies.** The core depends only on PyYAML; LLM SDKs are optional extras.
- **Add a test** for new engine behavior or a new built-in adapter.
- **New adapters** are welcome under `okfkit/adapters/` (broadly useful) or `examples/` (domain-specific).

## Adding an LLM enrichment backend

`okfkit/enrich.py` uses a small `Backend` abstraction. To support another provider, add a branch
that returns the model's text for a `(system, user)` prompt; keep the JSON parsing/retry shared.

## Releasing

Releases publish to PyPI via `.github/workflows/release.yml` (Trusted Publishing / OIDC — no API token). The flow, for `vX.Y.Z`:

1. Bump the version in **both** `pyproject.toml` and `okfkit/__init__.py`. The workflow verifies the built wheel's version against the tag and fails the publish if they disagree.
2. Add a `CHANGELOG.md` entry.
3. Commit and push `main`.
4. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.
5. Create the GitHub Release: `gh release create vX.Y.Z --title "vX.Y.Z" --notes "..."`. *Publishing the release* is what triggers the workflow — the tag alone does nothing.

The workflow then runs the full test matrix; only if it's green does the `publish` job build and upload to PyPI. Note: the publish job uses the `pypi` GitHub environment, which requires a reviewer to **approve the deployment** in the Actions UI before the upload runs — the release will sit at "Waiting" until someone approves it.

## Reporting issues

Please include your `okf.config.yaml`, the adapter you used, and the command output.
