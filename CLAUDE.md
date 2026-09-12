# CLAUDE.md

## 项目目标与当前结构

本仓库是招标文件智能合规审批系统：

- `frontend/`：React + TypeScript + Vite 页面；
- `backend/`：FastAPI + PostgreSQL + Redis/Celery 后端；
- `algorithm/`：目录提取、内容匹配、规则校验三阶段核心算法；
- `config/runtime.env`：数据库、Redis、后端、算法、模型和前端地址的唯一运行配置；
- `scripts/`：各服务启动入口；
- `docs/ALGORITHM_ARCHITECTURE.md` 和 `docs/BACKEND_ARCHITECTURE.md`：详细设计与运维说明。

新任务通过前端上传到 `POST /api/reviews`。API 保存文件和 PostgreSQL 记录后只投递 UUID；Celery worker 通过 `backend/app/services/algorithm_adapter.py` 直接调用 `prepare_case()` 与 `run_case()`。禁止让 Web 任务调用 `algorithm/main.py`，因为 CLI 会管理并覆盖全局 `reports/`。

## 后端硬约束

- 不新增零散 `.env`、INI 或脚本内运行默认值；新增运行参数统一进入 `config/runtime.env.example`，所有 shell 入口先加载 `scripts/lib/load_runtime_config.sh`。
- 数据库固定为 PostgreSQL；不要加入 SQLite/MySQL 兼容分支。
- Redis 只作 Celery broker/backend；PostgreSQL 是任务状态和结果的唯一真相来源。
- 原文件和算法产物保存在 `STORAGE_ROOT`；数据库保存相对路径和 JSONB。
- API 请求线程不得运行算法；所有核心处理必须进入 Celery。
- 前端不得直接消费算法原始 JSON。所有映射集中在 `backend/app/services/result_mapper.py`。
- 数据库结构变化必须新增 Alembic migration，不使用运行时 `create_all()`。
- API 与 worker 可以多实例；Celery beat 在集群中只能有一个实例。
- 每个任务创建时快照政策规则表并保存 SHA-256；worker 运行前必须校验快照哈希。
- 每份文档必须使用独立 `work/decision_cache`，不得共享案件缓存。
- 上传文件路径必须经过 `safe_filename()` 和 `ensure_within()`。
- 不在 API 中返回模型原始响应、缓存键、堆栈或服务器绝对路径。

## 算法硬约束

- 不调用外部模型 API；所有模型调用连接服务器本地 Qwen3-8B vLLM。
- 不自动启动模型服务，由运维单独运行 `scripts/algorithm/serve_vllm_qwen3_8b.sh`。
- 步骤一、二不得写死义齿、医疗器械或特定产品领域词汇。
- 不在运行时生成案件专用 Python checker；确定性逻辑位于全局执行器。
- `rule_raw` 决定审查主题；`rule_text` 中的法规依据可参考，生成公式/开发说明不得直接参与判定。
- 检查方式包含“结构化数据检查”时走确定性执行器；其他方法走语义判定。
- 结构化数值必须由正则提取；LLM 只做字段语义映射、兜底判断和解释。
- 结构化计算成功时 LLM 不覆盖状态；`requires_review` 时可语义兜底，但保留结构化初判。
- Qwen JSON 解析必须兼容 `<think>`、Markdown 代码围栏和前后说明文字。
- 步骤二默认字符 TF-IDF + 本地 BGE-M3 混合召回，最终 evidence 不超过 3 条。
- Office 优先使用 LibreOffice 转 PDF，不覆盖用户原文件；DOCX 可 XML 降级。
- `argparse.add_argument` 保持一行，不主动拆行。

## 数据契约

政策规则输入契约：由本项目之外的程序统一转成 JSON（`data/policy_rules.json`，路径见 `POLICY_RULES_PATH`），`algorithm/src/cont_match/rules.py` 只读 JSON、不再解析 Excel/PDF。顶层为 `{version, rules:[...]}` 或直接规则数组。每条规则字段：`rule_id`（整数）、`rule_raw`（重点排查情形，必填）、`rule_text`（触发逻辑公式，对象，含 `description`/`legal_basis`/`formula`/`dev_note` 四个可选子字段，载入时按 `【描述】/【法规依据】/【公式】/【开发说明】` 顺序重组为块字符串供 `rule_parts` 解析）、`check_method`（检查方式，缺省“大模型分析”）、`structured_fields`、`match_hints`（仅用于步骤二召回，不进最终输出）。`rule_text` 也兼容纯字符串。

算法正式匹配契约位于 `algorithm/src/rule_schema.py`：

- `source` 只包含 `file`；
- `rule_id` 为整数；
- `rule_raw` 对应“重点排查情形”；
- `rule_text` 对应“触发逻辑公式”（此处为重组后的块字符串）；
- `check_method` 对应“检查方式”；
- `structured_fields` 对应“结构化数据展示字段”；
- `evidence` 包含原文、章节和 PDF/文件内双页码。

前端公开契约位于 `backend/app/schemas.py` 和 `frontend/src/types/review.ts`。算法状态映射仅在 `result_mapper.py`：`pass -> passed`、`insufficient_input/error -> insufficient`，其中 `error` 额外累计 `executionFailed`。

## 常用命令

```bash
# 首次配置；日常启动不需要再执行 export
bash scripts/setup_runtime_config.sh

# 开发基础设施
bash scripts/backend/run_infrastructure.sh

# vLLM
bash scripts/algorithm/serve_vllm_qwen3_8b.sh

# 后端单进程入口
bash scripts/backend/migrate.sh
bash scripts/backend/run_api.sh
bash scripts/backend/run_worker.sh
bash scripts/backend/run_beat.sh

# 单服务器联合入口
bash scripts/backend/run_backend.sh

# 前端
bash scripts/frontend/run.sh

# 后端纯逻辑测试
PYTHONPATH=backend python -m unittest discover -s backend/tests -v
python -m compileall -q backend

# 算法测试（需要算法依赖）
PYTHONPATH=algorithm python -m unittest discover -s algorithm/tests -v

# 前端生产构建
cd frontend && npm run build

# 算法 CLI 单文件流程（脚本会加载统一配置）
bash scripts/algorithm/run_one_report.sh
```

后端启动、API、状态机、目录协议、故障恢复和生产注意事项以 `docs/BACKEND_ARCHITECTURE.md` 为准。
