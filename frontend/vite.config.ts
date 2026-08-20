import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 后端地址来自统一配置 runtime.env（run.sh 已 source 并 set -a 导出）。
const backendPort = process.env.BACKEND_PORT ?? '8000';
const apiPrefix = process.env.API_PREFIX ?? '/api';

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    // 同源代理到本机后端：浏览器只连 5173，免 CORS；后端端口变化不影响前端。
    proxy: {
      [apiPrefix]: { target: `http://127.0.0.1:${backendPort}`, changeOrigin: true },
    },
    // 源码在 CIFS 网络盘时 inotify 失效，设 VITE_USE_POLLING=1 改用轮询以恢复热更新。
    watch: process.env.VITE_USE_POLLING ? { usePolling: true, interval: 300 } : undefined,
  },
});
