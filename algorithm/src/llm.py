"""本地模型接入：OpenAI 兼容接口 → Qwen3-8B vLLM，不调用外部 API。"""

from __future__ import annotations

from functools import lru_cache

from config import settings


@lru_cache(maxsize=8)
def _client(base_url: str, api_key: str):
    """复用线程安全连接池，并确保本机 vLLM 请求不受系统 SOCKS/HTTP 代理影响。"""
    import httpx
    from openai import OpenAI

    transport = httpx.Client(trust_env=False, timeout=settings.llm_timeout, limits=httpx.Limits(max_connections=settings.llm_max_connections, max_keepalive_connections=settings.llm_max_connections))
    return OpenAI(base_url=base_url, api_key=api_key, http_client=transport)


def chat(
    prompt: str,
    system: str = "",
    temperature: float = 0.1,
    max_tokens: int = 4096,
    *,
    top_p: float | None = None,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> str:
    """调用本地 Qwen vLLM，返回文本。OpenAI/httpx 客户端按配置复用。"""
    client = _client(base_url or settings.llm_base_url, api_key or settings.llm_api_key)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    # 思考模式建议配非贪婪采样，top_p 仅在显式传入时下发，其余调用维持原行为。
    sampling = {"top_p": top_p} if top_p is not None else {}
    resp = client.chat.completions.create(
        model=model or settings.llm_model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        **sampling,
    )
    return resp.choices[0].message.content or ""


def healthcheck() -> dict:
    """探测本地服务是否可达（不生成长文本）。失败抛异常。"""
    client = _client(settings.llm_base_url, settings.llm_api_key)
    models = client.models.list()
    ids = [m.id for m in models.data]
    return {
        "base_url": settings.llm_base_url,
        "configured_model": settings.llm_model,
        "available_models": ids,
        "ok": settings.llm_model in ids or bool(ids),
    }


class Embedder:
    """BGE-M3 本地向量编码器；供步骤二批量语义召回。"""

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or settings.embed_model
        self._model = None

    def _lazy(self):
        if self._model is None:
            self._model = _embedding_model(self.model_name, settings.embed_device)
        return self._model

    def encode(self, texts: list[str]):
        """批量返回已归一化向量；调用方可直接用点积计算余弦相似度。"""
        return self._lazy().encode(texts, batch_size=settings.embed_batch_size, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)

    def similarity(self, a: str, b: str) -> float:
        ea, eb = self.encode([a, b])
        return float(ea @ eb)


@lru_cache(maxsize=4)
def _embedding_model(model_name: str, device: str):
    """同一进程的批量案件复用一份 embedding 权重，避免逐文件重新加载。"""
    from sentence_transformers import SentenceTransformer
    kwargs = {"device": device} if device else {}
    return SentenceTransformer(model_name, **kwargs)
