# 服务器首次启动与验证

本文档用于服务器第一次部署。日常运行不需要执行任何 `export`；所有进程都自动读取根目录
`config/runtime.env`。

## 1. 安装与统一配置

```bash
conda activate approval
pip install -r requirements.txt
bash scripts/setup_runtime_config.sh
```

只编辑 `config/runtime.env`，至少确认以下内容：

- `DATABASE_URL` 与 PostgreSQL 账号一致；开发容器同时确认 `POSTGRES_*`；
- `REDIS_URL`；
- `POLICY_RULES_PATH`；
- `LLM_MODEL_PATH`、`LOCAL_EMBED_MODEL`；
- `LLM_CUDA_VISIBLE_DEVICES`、`LLM_PORT`；
- `BACKEND_PORT`、`CORS_ORIGINS`。

路径含空格时使用双引号。数据库密码如果含有 `@`、`:`、`/` 等 URL 特殊字符，不要使用模板中的自动
拼接形式，应把 `DATABASE_URL` 改为完整连接地址，并对其中的密码部分进行 URL 编码。

编辑完成后先校验，脚本不会启动服务，也不会显示数据库密码：

```bash
bash scripts/check_runtime_config.sh
```

从旧版本升级时，`setup_runtime_config.sh` 不会覆盖已有配置。请手动确认以下检索参数已经同步为新版默认值：

```dotenv
ALGORITHM_CANDIDATE_COUNT=16
LOCAL_LLM_CANDIDATE_CHARS=1000
LOCAL_EMBED_CHUNK_CHARS=800
LOCAL_EMBED_CHUNK_OVERLAP=120
```

## 2. 不连接外部服务的代码测试

```bash
PYTHONPATH=backend python -m unittest discover -s backend/tests -v
PYTHONPATH=algorithm python -m unittest discover -s algorithm/tests -v
python -m compileall -q backend algorithm
```

这些测试验证代码契约，不代表 PostgreSQL、Redis、vLLM 或 GPU 已经可用。

## 3. 一键后台启动全部服务

单机联调只需在一个终端运行：

```bash
conda activate approval
cd /项目绝对路径/IntelligentApproval
bash scripts/open_service.sh
```

该脚本在后台静默按依赖顺序拉起并逐个等待就绪：PostgreSQL、Redis、vLLM、Alembic 迁移、FastAPI、一个
Celery worker 和唯一的 Celery beat。每个服务就绪会打印一行 `✓`，全部就绪后打印各服务地址并退出，把终端
还给你继续后续操作。各服务日志集中在 `runtime/services/*.log`。

- 使用企业已有的 PostgreSQL/Redis 实例时，只需在 `config/runtime.env` 写好连接地址；这台机器上仍会尝试
  启动本地容器化实例，如不需要可自行删去脚本中的基础设施段落。
- vLLM 首次加载模型较慢，脚本默认最多等待 6 分钟（`VLLM_READY_TRIES` 可覆盖）。
- conda 环境名、PostgreSQL 数据目录、端口沿用脚本内默认值，可用 `APP_CONDA_ENV`、`INFRA_CONDA_ENV`、
  `PG_DATA_DIR` 等环境变量覆盖。

停止全部服务（顺序与启动相反）：

```bash
bash scripts/close_service.sh
```

正式生产环境不使用这两个编排脚本，而应由 systemd、Supervisor 或 Kubernetes 分别监管
`scripts/algorithm/serve_vllm_qwen3_8b.sh`、`scripts/backend/run_api.sh`、`run_worker.sh`、`run_beat.sh`
等前台入口，并保证全系统只有一个 beat 实例。

## 4. 分层验证

先检查依赖：

```bash
bash scripts/backend/check_services.sh
```

然后上传一份真实文件完成全链路验证：

```bash
bash scripts/backend/smoke_review.sh "/待测试文件/招标文件1.pdf"
```

脚本会自动上传、轮询、打印最终 JSON，不需要手工复制任务 ID。任务产物位于
`STORAGE_ROOT/<review UUID>/`；任务、文档状态、算法原始结果和页面规范化结果位于 PostgreSQL。

不打开前端，直接批量提交一个目录中的文件：

```bash
bash scripts/backend/run_batch_review.sh "/待审文件目录"
```

它使用与前端相同的 `POST /api/reviews` 接口，等待整批完成后，将简要报告、汇总 JSON 和每份文件的
详细结果下载到 `BATCH_REVIEW_OUTPUT_ROOT/<review_id>/`。默认单批最多 10 份，由
`MAX_DOCUMENTS_PER_REVIEW` 控制；脚本不会把超限目录静默拆成多个独立审查任务。

最后可打开：

- OpenAPI：`http://服务器IP:8000/docs`
- 存活探针：`http://服务器IP:8000/api/health/live`
- 就绪探针：`http://服务器IP:8000/api/health/ready`

本轮配置改造不涉及前端业务数据连调；建议先完成上述后端全链路验证，再处理前端。
