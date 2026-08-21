"""
Pluggable LLM/embedding provider interface.

Reference: FRD section "LLM Orchestration Layer" - the platform must never
hardcode a single vendor. `LLMProvider` is the seam: everything upstream
(app/services/rag.py) talks to this ABC only, never to a vendor SDK
directly. Provider selection is entirely config-driven via
`settings.LLM_PROVIDER` (env var `LLM_PROVIDER=mock|litellm`).

Two concrete implementations ship here:

  * MockProvider     - fully deterministic, offline, zero-cost. This is the
                        default so the whole vertical slice (ingest -> embed
                        -> retrieve -> answer -> cite -> review -> cost log)
                        works out of the box with no API keys and no network
                        access, which is what makes it possible to run
                        pytest in a sandboxed/offline CI runner.

  * LiteLLMProvider  - thin adapter over the `litellm` package, which itself
                        gives unified access to OpenAI/Anthropic/Azure/etc.
                        with routing + fallback + cost capture. Not exercised
                        by default; swap in via LLM_PROVIDER=litellm plus the
                        relevant vendor API key env vars (see .env.example).

To add a real provider without touching call sites: implement `LLMProvider`,
register it in `get_llm_provider()`, and flip the env var.
"""
from __future__ import annotations

import hashlib
import math
import re
import time
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass

from app.core.config import get_settings

settings = get_settings()


@dataclass
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    provider: str
    prompt_tokens: int
    cost_usd: float
    latency_ms: float


@dataclass
class CompletionResult:
    text: str
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    latency_ms: float


class LLMProvider(ABC):
    """Abstract interface every provider (mock, litellm, future vendors)
    must implement. Keep this surface minimal and stable.
    """

    name: str = "base"

    @abstractmethod
    def embed(self, texts: list[str]) -> EmbeddingResult:
        ...

    @abstractmethod
    def complete(self, prompt: str, *, max_tokens: int = 512) -> CompletionResult:
        ...


# --------------------------------------------------------------------------
# Mock provider - deterministic, offline, default.
# --------------------------------------------------------------------------

_EMBEDDING_DIM = 256
_TOKEN_RE = re.compile(r"[A-Za-z0-9_']+")

# The mock classifier's "I have no basis for a label" answer. `unknown` is
# deliberately outside any taxonomy, so classification.py parses it as
# UNKNOWN_LABEL at confidence 0.0 and routes the document to human review
# rather than picking a category at random.
_UNCLASSIFIABLE_RESPONSE = "LABEL: unknown\nCONFIDENCE: 0.0"


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _hashing_embed(text: str, dim: int = _EMBEDDING_DIM) -> list[float]:
    """Deterministic bag-of-words hashing embedding.

    Each token is hashed into a bucket in a fixed-size vector (the classic
    "hashing trick"), giving a stable, dependency-free embedding that still
    captures lexical overlap well enough for cosine-similarity retrieval
    over small demo corpora. This is intentionally simple - it is NOT meant
    to compete with a real sentence-embedding model, only to make the full
    pipeline exercisable offline and deterministically in tests.
    """
    vec = [0.0] * dim
    tokens = _tokenize(text)
    if not tokens:
        return vec
    for tok in tokens:
        h = int(hashlib.sha256(tok.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h // dim) % 2 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


class MockProvider(LLMProvider):
    """Deterministic local provider used by default (LLM_PROVIDER=mock).

    - Embeddings: hashing bag-of-words vectors (see `_hashing_embed`).
    - Completions: dispatched on prompt shape, because the platform issues
      two structurally different kinds of completion:
        * grounded RAG prompts (CONTEXT/QUESTION, built by rag.py) get a
          template-based extractive "answer" that quotes the highest-signal
          sentences from the supplied context and cites them. It never
          invents facts outside that context, which makes the refusal /
          grounding behaviour in rag.py trivially testable.
        * constrained-label classification prompts (CANDIDATE LABELS/
          DOCUMENT, built by classification.py) get a `LABEL:`/`CONFIDENCE:`
          response chosen by lexical evidence, so FRD 7 classification is
          exercisable offline on the same terms as RAG.
    """

    name = "mock"

    def embed(self, texts: list[str]) -> EmbeddingResult:
        start = time.perf_counter()
        vectors = [_hashing_embed(t) for t in texts]
        latency_ms = (time.perf_counter() - start) * 1000
        prompt_tokens = sum(len(_tokenize(t)) for t in texts)
        return EmbeddingResult(
            vectors=vectors,
            model="mock-hashing-embedding-v1",
            provider=self.name,
            prompt_tokens=prompt_tokens,
            cost_usd=0.0,
            latency_ms=latency_ms,
        )

    def complete(self, prompt: str, *, max_tokens: int = 512) -> CompletionResult:
        start = time.perf_counter()
        text = self._respond(prompt)
        latency_ms = (time.perf_counter() - start) * 1000
        prompt_tokens = len(_tokenize(prompt))
        completion_tokens = len(_tokenize(text))
        return CompletionResult(
            text=text,
            model="mock-template-llm-v1",
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_usd=0.0,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _respond(prompt: str) -> str:
        """Route to the template matching the prompt's shape.

        Sniffing the prompt (rather than adding a `task` argument to
        `LLMProvider.complete`) keeps the provider ABC minimal and stable,
        which is the whole point of that seam - a real provider needs no
        knowledge that classification exists.
        """
        if "CANDIDATE LABELS:" in prompt:
            return MockProvider._template_classification(prompt)
        return MockProvider._template_answer(prompt)

    @staticmethod
    def _template_classification(prompt: str) -> str:
        """Deterministic stand-in for a real classifier (FRD 7).

        Scores every candidate label by how much of its description shows up
        in the document, weighting each description token by 1/df across the
        label set so boilerplate shared by several descriptions ("document",
        "date") carries almost no signal while distinctive terms
        ("remittance", "indemnification") carry a full point.

        Confidence blends two transparent quantities: `share` (how much of
        the total evidence the winner holds) and `margin` (how far clear of
        the runner-up it is). A document matching one category cleanly
        scores high; a document matching two equally well scores low and
        lands in the review queue, which is the behaviour worth testing.
        Zero evidence yields `unknown`/0.0 rather than a coin flip.
        """
        labels_match = re.search(r"CANDIDATE LABELS:\n(.*?)\n\nDOCUMENT:", prompt, re.DOTALL)
        doc_match = re.search(r"\nDOCUMENT:\n(.*?)\n\nINSTRUCTIONS:", prompt, re.DOTALL)
        if not labels_match or not doc_match:
            return _UNCLASSIFIABLE_RESPONSE

        entries: list[tuple[str, set[str]]] = []
        for line in labels_match.group(1).splitlines():
            entry_match = re.match(r"\[([^\]]+)\]\s*(.+)", line.strip())
            if not entry_match:
                continue
            description_tokens = {t for t in _tokenize(entry_match.group(2)) if len(t) > 3}
            entries.append((entry_match.group(1), description_tokens))
        if not entries:
            return _UNCLASSIFIABLE_RESPONSE

        document_frequency: Counter[str] = Counter()
        for _, tokens in entries:
            document_frequency.update(tokens)

        doc_tokens = set(_tokenize(doc_match.group(1)))
        scored = sorted(
            (
                (sum(1.0 / document_frequency[t] for t in tokens & doc_tokens), label)
                for label, tokens in entries
            ),
            key=lambda pair: (-pair[0], pair[1]),
        )

        top_score, top_label = scored[0]
        total = sum(score for score, _ in scored)
        if top_score <= 0 or total <= 0:
            return _UNCLASSIFIABLE_RESPONSE

        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        share = top_score / total
        margin = (top_score - runner_up) / top_score
        confidence = round(min(1.0, 0.5 * share + 0.5 * margin), 4)
        return f"LABEL: {top_label}\nCONFIDENCE: {confidence}"

    @staticmethod
    def _template_answer(prompt: str) -> str:
        """Extract the CONTEXT and QUESTION sections from the grounded
        prompt built by rag.py and produce a template answer grounded only
        in that context, echoing citation markers already embedded by the
        caller (e.g. "[1]", "[2]").
        """
        context_match = re.search(r"CONTEXT:\n(.*?)\nQUESTION:", prompt, re.DOTALL)
        question_match = re.search(r"QUESTION:\n(.*?)(\nINSTRUCTIONS:|$)", prompt, re.DOTALL)
        context = context_match.group(1).strip() if context_match else ""
        question = question_match.group(1).strip() if question_match else prompt.strip()

        if not context:
            return (
                "I don't have enough grounded context to answer that "
                "confidently. Please rephrase or ingest a relevant document."
            )

        # Rank sentences in the context by lexical overlap with the question,
        # then stitch the best 1-3 together as an "answer", preserving the
        # inline [n] citation markers that rag.py already inserted per source.
        question_tokens = set(_tokenize(question))
        segments = [seg.strip() for seg in re.split(r"(?=\[\d+\])", context) if seg.strip()]

        scored = []
        for seg in segments:
            seg_tokens = set(_tokenize(seg))
            overlap = len(seg_tokens & question_tokens)
            scored.append((overlap, seg))
        scored.sort(key=lambda x: x[0], reverse=True)

        top = [seg for score, seg in scored[:2] if score > 0] or [scored[0][1]]
        answer = " ".join(top)
        return f"Based on the retrieved context: {answer}"


# --------------------------------------------------------------------------
# LiteLLM-backed provider - real multi-provider routing, ready to enable.
# --------------------------------------------------------------------------


class LiteLLMProvider(LLMProvider):
    """Adapter over the `litellm` package.

    LiteLLM gives a single `completion()`/`embedding()` call signature across
    OpenAI, Anthropic, Azure OpenAI, Bedrock, etc, plus built-in fallback
    routing (`LITELLM_FALLBACK_MODELS`) and per-call cost capture via
    `response._hidden_params["response_cost"]` (falls back to
    `litellm.completion_cost(...)` when unavailable).

    Enable with:
        LLM_PROVIDER=litellm
        LITELLM_MODEL=gpt-4o-mini            # or any litellm-supported model id
        OPENAI_API_KEY=...                   # or ANTHROPIC_API_KEY, etc.

    Not exercised in the default test suite because it requires network
    access and a paid API key - see backend/tests/test_rag.py for how the
    ABC seam is used to swap providers in tests via dependency override.
    """

    name = "litellm"

    def __init__(self) -> None:
        try:
            import litellm  # noqa: F401
        except ImportError as exc:  # pragma: no cover - exercised only when enabled
            raise RuntimeError(
                "LLM_PROVIDER=litellm requires the 'litellm' package. "
                "Install it (see backend/requirements.txt) or switch back to "
                "LLM_PROVIDER=mock."
            ) from exc
        self._litellm = litellm
        self._fallbacks = [m for m in settings.LITELLM_FALLBACK_MODELS.split(",") if m]

    def embed(self, texts: list[str]) -> EmbeddingResult:
        start = time.perf_counter()
        response = self._litellm.embedding(model=settings.LITELLM_EMBEDDING_MODEL, input=texts)
        latency_ms = (time.perf_counter() - start) * 1000
        vectors = [item["embedding"] for item in response["data"]]
        usage = response.get("usage", {}) or {}
        cost = self._extract_cost(response)
        return EmbeddingResult(
            vectors=vectors,
            model=settings.LITELLM_EMBEDDING_MODEL,
            provider=self.name,
            prompt_tokens=usage.get("prompt_tokens", 0),
            cost_usd=cost,
            latency_ms=latency_ms,
        )

    def complete(self, prompt: str, *, max_tokens: int = 512) -> CompletionResult:
        start = time.perf_counter()
        response = self._litellm.completion(
            model=settings.LITELLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            fallbacks=self._fallbacks or None,
        )
        latency_ms = (time.perf_counter() - start) * 1000
        text = response["choices"][0]["message"]["content"]
        usage = response.get("usage", {}) or {}
        cost = self._extract_cost(response)
        return CompletionResult(
            text=text,
            model=settings.LITELLM_MODEL,
            provider=self.name,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            cost_usd=cost,
            latency_ms=latency_ms,
        )

    def _extract_cost(self, response) -> float:
        try:
            hidden = getattr(response, "_hidden_params", {}) or {}
            if "response_cost" in hidden and hidden["response_cost"] is not None:
                return float(hidden["response_cost"])
            return float(self._litellm.completion_cost(completion_response=response))
        except Exception:
            return 0.0


_provider_instance: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    """Factory selecting the active provider from settings.LLM_PROVIDER.

    Cached process-wide; call `reset_llm_provider()` in tests if you need to
    force re-selection after monkeypatching settings.
    """
    global _provider_instance
    if _provider_instance is not None:
        return _provider_instance
    if settings.LLM_PROVIDER == "litellm":
        _provider_instance = LiteLLMProvider()
    else:
        _provider_instance = MockProvider()
    return _provider_instance


def reset_llm_provider() -> None:
    global _provider_instance
    _provider_instance = None
