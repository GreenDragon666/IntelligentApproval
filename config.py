"""集中配置。全部指向本地模型服务，不调用外部 API。

模型权重默认路径（本机已下载）：
  /home/zyl/public/LLM Library/Qwen2.5-Coder-3B-Instruct
  /home/zyl/public/LLM Library/Qwen2.5-Coder-14B-Instruct

先用 3B 把编写期链路跑通；资源够再切 14B。
"""

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

    # —— 语义相似度 embedding（步骤三可选；当前确定性 checker 不强制）——
    embed_model: str = os.getenv("LOCAL_EMBED_MODEL", "BAAI/bge-m3")

    # —— 代码生成流水线（编写期）——
    codegen_max_retries: int = int(os.getenv("CODEGEN_MAX_RETRIES", "3"))
    generated_dir: str = os.getenv("GENERATED_DIR", "generated_checkers")
    checker_timeout: int = int(os.getenv("CHECKER_TIMEOUT", "30"))
    review_max_retries: int = int(os.getenv("REVIEW_MAX_RETRIES", "1"))
    review_max_evidence_chars: int = int(os.getenv("REVIEW_MAX_EVIDENCE_CHARS", "20000"))


settings = Settings()
