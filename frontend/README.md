# 首信智能审批平台前端

## 运行

```bash
bash scripts/setup_runtime_config.sh  # 全项目只需首次执行一次
bash scripts/frontend/run.sh
```

浏览器默认访问 `http://localhost:5173/`。

`config/runtime.env` 中的 `VITE_REVIEW_API_URL` 必须包含后端 API 前缀，例如：

```dotenv
VITE_REVIEW_API_URL=http://127.0.0.1:8000/api
```

启动脚本会把该值自动传给 Vite。前端的数据适配状态以当前业务实现为准。

## 构建

```bash
cd frontend
npm run build
```

构建结果位于 `frontend/dist`，该目录不提交 Git。

接口类型位于 `src/types/review.ts`，HTTP 适配位于 `src/services/reviewService.ts`。完整后端契约见 `docs/BACKEND_ARCHITECTURE.md`。
