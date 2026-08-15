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

## 2. 不连接外部服务的代码测试

```bash
PYTHONPATH=backend python -m unittest discover -s backend/tests -v
PYTHONPATH=algorithm python -m unittest discover -s algorithm/tests -v
python -m compileall -q backend algorithm
```

这些测试验证代码契约，不代表 PostgreSQL、Redis、vLLM 或 GPU 已经可用。

## 3. 启动 PostgreSQL 与 Redis

测试服务器使用仓库内的容器：

```bash
bash scripts/backend/run_infrastructure.sh
docker compose -f backend/docker-compose.infrastructure.yml ps
```

如果使用企业已有实例，不运行第一条命令，只需在统一配置中写好连接地址。

## 4. 启动 vLLM

在终端 A 运行：

```bash
conda activate approval
cd /项目绝对路径/IntelligentApproval
bash scripts/algorithm/serve_vllm_qwen3_8b.sh
```

该进程会持续占用终端。另一个终端运行：

```bash
bash scripts/algorithm/check_vllm.sh
```

能返回 `/v1/models` JSON 才继续。

## 5. 启动后端

首次单机联调在终端 B 运行：

```bash
conda activate approval
cd /项目绝对路径/IntelligentApproval
bash scripts/backend/run_backend.sh
```

该入口先执行 Alembic 迁移，再同时启动 FastAPI、一个 Celery worker 和唯一的 Celery beat。正式生产环境应由
systemd、Supervisor 或 Kubernetes 分别监管 `run_api.sh`、`run_worker.sh`、`run_beat.sh`，并保证全系统只有
一个 beat 实例。

## 6. 分层验证

终端 C 先检查依赖：

```bash
bash scripts/backend/check_services.sh
```

然后上传一份真实文件完成全链路验证：

```bash
bash scripts/backend/smoke_review.sh "/待测试文件/招标文件1.pdf"
```

脚本会自动上传、轮询、打印最终 JSON，不需要手工复制任务 ID。任务产物位于
`STORAGE_ROOT/<review UUID>/`；任务、文档状态、算法原始结果和页面规范化结果位于 PostgreSQL。

最后可打开：

- OpenAPI：`http://服务器IP:8000/docs`
- 存活探针：`http://服务器IP:8000/api/health/live`
- 就绪探针：`http://服务器IP:8000/api/health/ready`

本轮配置改造不涉及前端业务数据连调；建议先完成上述后端全链路验证，再处理前端。
