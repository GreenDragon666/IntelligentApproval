# 首信智能审批平台前端

## 运行

```bash
cp frontend/.env.example frontend/.env
bash scripts/frontend/run.sh
```

浏览器默认访问 `http://localhost:5173/`。

`VITE_REVIEW_API_URL` 必须包含后端 API 前缀，例如：

```dotenv
VITE_REVIEW_API_URL=http://127.0.0.1:8000/api
```

配置后，上传页会向后端提交文件，Processing 页面轮询真实任务进度。未配置时继续使用 `public/data` 中的示例报告。

## 构建

```bash
cd frontend
npm run build
```

构建结果位于 `frontend/dist`，该目录不提交 Git。

接口类型位于 `src/types/review.ts`，HTTP 适配位于 `src/services/reviewService.ts`。完整后端契约见 `docs/BACKEND_ARCHITECTURE.md`。
