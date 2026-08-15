# Backend

后端固定使用以下技术栈：

- FastAPI：HTTP API 和 OpenAPI 契约
- PostgreSQL：任务、文档状态、算法原始结果和前端规范化结果
- Redis + Celery：长时间算法任务的可靠投递、恢复和并发控制
- 共享 POSIX 文件目录：原文件、政策规则快照、中间产物、日志和 Markdown 报告

## 进程入口

```bash
bash scripts/backend/migrate.sh      # Alembic 数据库迁移
bash scripts/backend/run_api.sh      # FastAPI
bash scripts/backend/run_worker.sh   # Celery worker
bash scripts/backend/run_beat.sh     # 唯一的 Celery beat 调度器
```

单服务器开发可用 `bash scripts/backend/run_backend.sh` 一次启动以上进程。生产环境应由 systemd、Supervisor 或 Kubernetes 分别监管三个入口，并确保集群中只运行一个 beat 实例。

唯一配置模板为 `config/runtime.env.example`。首次运行 `bash scripts/setup_runtime_config.sh` 创建本机配置，所有入口脚本会自动加载，不需要在终端执行 `export`。完整说明见 `docs/BACKEND_ARCHITECTURE.md`。

## 无外部服务的快速测试

```bash
PYTHONPATH=backend python -m unittest discover -s backend/tests -v
python -m compileall -q backend
```

这些测试不连接 PostgreSQL、Redis 或 vLLM。完整联调必须在服务器启动依赖后进行。
