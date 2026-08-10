"""本地模型接入：OpenAI 兼容接口 → Qwen3-8B vLLM，不调用外部 API。"""

from __future__ import annotations

from config import settings


def chat(
    prompt: str,
    system: str = "",
    temperature: float = 0.1,
    max_tokens: int = 4096,
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> str:
    """调用本地代码生成模型，返回文本。openai 包懒加载。"""
    from openai import OpenAI

    client = OpenAI(
        base_url=base_url or settings.llm_base_url,
        api_key=api_key or settings.llm_api_key,
    )
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = client.chat.completions.create(
        model=model or settings.llm_model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""


def healthcheck() -> dict:
    """探测本地服务是否可达（不生成长文本）。失败抛异常。"""
    from openai import OpenAI

    client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
    models = client.models.list()
    ids = [m.id for m in models.data]
    return {
        "base_url": settings.llm_base_url,
        "configured_model": settings.llm_model,
        "available_models": ids,
        "ok": settings.llm_model in ids or bool(ids),
    }


class Embedder:
    """BGE-M3 语义相似度。本地加载，懒加载；步骤三可选。"""

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or settings.embed_model
        self._model = None

    def _lazy(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def similarity(self, a: str, b: str) -> float:
        from sentence_transformers import util
        m = self._lazy()
        ea, eb = m.encode([a, b], normalize_embeddings=True)
        return float(util.cos_sim(ea, eb)[0][0])
