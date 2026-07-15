"""Embedding backends for semantic search over a built vault.

Provider-flexible, mirroring `enrich.Backend`: Voyage AI (Anthropic's recommended
embeddings partner), any OpenAI-compatible embeddings endpoint, or a fully local
model2vec model (no API key, numpy-only, ~30 MB). All SDKs are lazy-imported so
none of them is a hard dependency of the kit.

NOTE: unlike `enrich`, the openai provider here defaults to the real OpenAI API
(`https://api.openai.com/v1`) — OpenRouter has no embeddings endpoint.
"""

from __future__ import annotations

import os

DEFAULT_EMBED_MODELS = {
    "voyage": "voyage-3.5-lite",
    "openai": "text-embedding-3-small",
    "local": "minishlab/potion-base-8M",
}
# Deliberately NOT enrich.DEFAULT_OPENAI_BASE_URL (OpenRouter): no embeddings there.
DEFAULT_OPENAI_EMBED_BASE_URL = "https://api.openai.com/v1"

_INSTALL_HINTS = {
    "voyage": "voyageai numpy",
    "openai": "openai numpy",
    "local": "model2vec numpy",
}


def require_numpy():
    """Import numpy lazily; RAG features need it but the core kit does not."""
    try:
        import numpy
    except ImportError:
        raise SystemExit("The 'numpy' package is required for RAG features: pip install numpy")
    return numpy


# ---------------------------------------------------------------------------
# Embedding backend — Voyage AI, OpenAI-compatible, or local (model2vec)
# ---------------------------------------------------------------------------
class EmbeddingBackend:
    def __init__(self, provider, model, api_key=None, base_url=None):
        self.provider = provider
        self.model = model
        if provider == "voyage":
            import voyageai
            self.client = voyageai.Client(api_key=api_key) if api_key else voyageai.Client()
        elif provider == "openai":
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key,
                                 base_url=base_url or DEFAULT_OPENAI_EMBED_BASE_URL)
        elif provider == "local":
            from model2vec import StaticModel
            self.client = StaticModel.from_pretrained(model)
        else:
            raise ValueError(f"unknown embedding provider: {provider}")

    def embed(self, texts, input_type=None, batch_size=128):
        """Embed *texts* → numpy float32 array of shape (len(texts), dim).

        *input_type* is "document" | "query" | None; only Voyage uses it
        (retrieval-tuned embeddings), other providers ignore it.
        """
        np = require_numpy()
        texts = list(texts)
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        rows = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            if self.provider == "voyage":
                rows += self.client.embed(batch, model=self.model,
                                          input_type=input_type).embeddings
            elif self.provider == "openai":
                resp = self.client.embeddings.create(model=self.model, input=batch)
                rows += [d.embedding for d in resp.data]
            else:  # local
                rows += list(self.client.encode(batch))
        return np.asarray(rows, dtype=np.float32)


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------
def make_embedder(provider=None, model=None, base_url=None) -> EmbeddingBackend:
    provider = provider or _autodetect_provider()
    model = model or DEFAULT_EMBED_MODELS[provider]
    api_key = None
    if provider == "voyage":
        api_key = (os.environ.get("VOYAGE_API_KEY") or "").strip()
        if not api_key:
            raise SystemExit("Set VOYAGE_API_KEY for the voyage embedding provider.")
    elif provider == "openai":
        api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
        if not api_key:
            raise SystemExit("Set OPENAI_API_KEY for the openai embedding provider "
                             "(note: OpenRouter has no embeddings endpoint).")
    try:
        return EmbeddingBackend(provider, model, api_key=api_key, base_url=base_url)
    except ImportError:
        raise SystemExit(f"Missing package(s) for the {provider!r} embedding provider: "
                         f"pip install {_INSTALL_HINTS[provider]}")


def _autodetect_provider() -> str:
    if os.environ.get("VOYAGE_API_KEY"):
        return "voyage"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "local"
