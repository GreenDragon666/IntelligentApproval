# 首信智能审批平台前端

## 运行

进入 `web` 目录后执行：

```bash
npm install
npm run dev -- --host 0.0.0.0
```

浏览器访问：

```text
http://localhost:5173/
```

## 打包

```bash
npm run build
```

打包结果在 `dist` 目录。

## 后端接口

未配置后端时，页面使用内置示例数据。

连接后端时设置环境变量：

```bash
VITE_REVIEW_API_URL=http://你的接口地址
```
