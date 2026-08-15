# IntelligentApproval

招标文件智能合规审批系统，由 React 前端、FastAPI/Celery 后端和三阶段审批算法组成。

## 仓库入口

- `frontend/`：上传、任务进度、总览和文件规则详情页面。
- `backend/`：FastAPI 接口、PostgreSQL 数据模型、Celery 任务和算法适配层。
- `algorithm/`：目录提取、内容匹配、结构化/语义规则校验。
- `data/`：开发环境政策规则表和待审批样例。
- `scripts/`：前端、后端、算法和 vLLM 启动脚本。
- `docs/ALGORITHM_ARCHITECTURE.md`：算法内部设计。
- `docs/BACKEND_ARCHITECTURE.md`：后端架构、状态机、接口、部署和故障恢复。

## 开发环境快速启动

```bash
# 1. 安装依赖（Python 3.10+）
pip install -r requirements.txt

# 2. 配置
cp backend/.env.example backend/.env
# 编辑 backend/.env：至少确认 DATABASE_URL、REDIS_URL、STORAGE_ROOT、
# POLICY_RULES_PATH、ALGORITHM_ROOT 和本地模型相关变量。

# 3. 启动 PostgreSQL 和 Redis（仅开发环境提供的容器）
bash scripts/backend/run_infrastructure.sh

# 4. 启动 vLLM（服务器环境）
bash scripts/algorithm/serve_vllm_qwen3_8b.sh

# 5. 迁移并启动 API、worker、beat
bash scripts/backend/run_backend.sh

# 6. 另一个终端启动前端
cp frontend/.env.example frontend/.env
bash scripts/frontend/run.sh
```

API 默认位于 `http://127.0.0.1:8000`，OpenAPI 文档位于 `http://127.0.0.1:8000/docs`，前端默认位于 `http://127.0.0.1:5173`。

本地没有 vLLM 时可以在 `backend/.env` 暂时设置：

```dotenv
ALGORITHM_USE_EMBEDDING=false
ALGORITHM_USE_LLM_MATCHING=false
ALGORITHM_STRICT_LLM=false
ALGORITHM_ENABLE_LLM_CHECK=false
```

此配置只验证上传、队列、文档提取、字符召回、规则路由、持久化和页面展示；语义规则会正常标记为输入不足，不能用于评价正式审批质量。

完整部署和排障方法见 [后端架构文档](docs/BACKEND_ARCHITECTURE.md)。
