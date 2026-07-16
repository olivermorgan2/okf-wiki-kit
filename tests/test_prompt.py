"""Tests for the TTY-gated key rescue in `make_embedder`/`make_backend` and the
pure `resolve_provider_model` resolvers (no SDK import, no key check).

Non-interactive behavior (CI/MCP/pipes) must be byte-identical to before: the
original SystemExit messages. When `envfile.prompt_for_key` yields a key, the
factories must sail past the key check (SDK construction is stubbed out)."""

import pytest

from okfkit import enrich, envfile
from okfkit.serve import embeddings

KEYS = ("VOYAGE_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY")


@pytest.fixture
def no_keys(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OKF_NONINTERACTIVE", "1")
    return monkeypatch


class _Stub:
    """Stands in for EmbeddingBackend/Backend: records ctor args, imports nothing."""
    def __init__(self, provider, model, api_key=None, base_url=None):
        self.provider, self.model, self.api_key, self.base_url = \
            provider, model, api_key, base_url


# ---------------------------------------------------------------------------
# make_embedder
# ---------------------------------------------------------------------------
def test_make_embedder_no_key_noninteractive_keeps_original_error(no_keys):
    with pytest.raises(SystemExit,
                       match=r"^Set VOYAGE_API_KEY for the voyage embedding provider\.$"):
        embeddings.make_embedder(provider="voyage")


def test_make_embedder_prompt_rescue_passes_key_check(no_keys):
    no_keys.setattr(envfile, "prompt_for_key", lambda var, hint="": "fake-key")
    no_keys.setattr(embeddings, "EmbeddingBackend", _Stub)
    backend = embeddings.make_embedder(provider="voyage")   # no SystemExit about the key
    assert isinstance(backend, _Stub)
    assert backend.api_key == "fake-key"
    assert backend.model == embeddings.DEFAULT_EMBED_MODELS["voyage"]


# ---------------------------------------------------------------------------
# make_backend
# ---------------------------------------------------------------------------
def test_make_backend_no_key_noninteractive_keeps_original_error(no_keys):
    with pytest.raises(SystemExit,
                       match=r"^Set OPENROUTER_API_KEY \(or OPENAI_API_KEY\) "
                             r"for the openai provider\.$"):
        enrich.make_backend(provider="openai")


def test_make_backend_prompt_rescue_passes_key_check(no_keys):
    no_keys.setattr(envfile, "prompt_for_key", lambda var, hint="": "fake-key")
    no_keys.setattr(enrich, "Backend", _Stub)
    backend = enrich.make_backend(provider="openai")        # no SystemExit about the key
    assert isinstance(backend, _Stub)
    assert backend.api_key == "fake-key"
    assert backend.model == enrich.DEFAULT_MODELS["openai"]


# ---------------------------------------------------------------------------
# resolvers: pure — sane defaults per provider, no keys, no SDKs
# ---------------------------------------------------------------------------
def test_enrich_resolver_defaults(no_keys):
    assert enrich.resolve_provider_model() == ("anthropic", "claude-opus-4-8")
    assert enrich.resolve_provider_model("openai") == \
        ("openai", enrich.DEFAULT_MODELS["openai"])
    assert enrich.resolve_provider_model("openai", "custom/model") == \
        ("openai", "custom/model")


def test_embeddings_resolver_defaults(no_keys):
    assert embeddings.resolve_provider_model() == ("local", "minishlab/potion-base-8M")
    assert embeddings.resolve_provider_model("voyage") == ("voyage", "voyage-3.5-lite")
    assert embeddings.resolve_provider_model("openai") == ("openai", "text-embedding-3-small")
    assert embeddings.resolve_provider_model("local", "my/model") == ("local", "my/model")


def test_resolvers_follow_autodetect(no_keys):
    no_keys.setenv("VOYAGE_API_KEY", "x")
    assert embeddings.resolve_provider_model()[0] == "voyage"
    no_keys.setenv("OPENAI_API_KEY", "x")
    assert enrich.resolve_provider_model()[0] == "openai"
    no_keys.setenv("ANTHROPIC_API_KEY", "x")
    assert enrich.resolve_provider_model()[0] == "anthropic"
