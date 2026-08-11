"""集中配置：所有 LLM 调用统一连接服务器本地 Qwen3-8B vLLM。"""

from __future__ import annotations

import os
from dataclasses import dataclass

# 本地权重根目录（路径含空格，脚本里务必加引号）
_DEFAULT_MODEL_DIR = "/home/zyl/public/LLM Library/Qwen3-8B"


@dataclass
class Settings:
    # —— 本地代码模型（OpenAI 兼容，通常由 vLLM 提供）——
    llm_base_url: str = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:8001/v1")
    # vLLM 的 --served-model-name；客户端请求用这个名字
    llm_model: str = os.getenv("LOCAL_LLM_MODEL", "Qwen3-8B")
    # 本地权重目录（起服务时用）；客户端一般不直接读这个路径
    llm_model_path: str = os.getenv("LOCAL_LLM_MODEL_PATH", _DEFAULT_MODEL_DIR)
    llm_api_key: str = os.getenv("LOCAL_LLM_API_KEY", "EMPTY")
    llm_candidate_chars: int = int(os.getenv("LOCAL_LLM_CANDIDATE_CHARS", "1200"))
    llm_timeout: float = float(os.getenv("LOCAL_LLM_TIMEOUT", "180"))
    llm_max_connections: int = int(os.getenv("LOCAL_LLM_MAX_CONNECTIONS", "16"))

    # —— 步骤三：短输出语义判定与并发 ——
    semantic_workers: int = int(os.getenv("SEMANTIC_WORKERS", "4"))
    matching_workers: int = int(os.getenv("MATCHING_WORKERS", "4"))
    semantic_max_tokens: int = int(os.getenv("SEMANTIC_MAX_TOKENS", "768"))
    semantic_max_retries: int = int(os.getenv("SEMANTIC_MAX_RETRIES", "1"))
    semantic_max_evidence_chars: int = int(os.getenv("SEMANTIC_MAX_EVIDENCE_CHARS", "16000"))
    semantic_max_chars_per_evidence: int = int(os.getenv("SEMANTIC_MAX_CHARS_PER_EVIDENCE", "8000"))

    # —— 语义相似度 embedding（步骤三可选；当前确定性 checker 不强制）——
    embed_model: str = os.getenv("LOCAL_EMBED_MODEL", "BAAI/bge-m3")

    # —— 可选二次复核 ——
    review_max_evidence_chars: int = int(os.getenv("REVIEW_MAX_EVIDENCE_CHARS", "20000"))


settings = Settings()
