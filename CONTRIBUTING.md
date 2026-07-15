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

## Reporting issues

Please include your `okf.config.yaml`, the adapter you used, and the command output.
