import fs from 'node:fs'
import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// 可选：让前端 dev server 也走 HTTPS —— 与后端 config.json 的 tls 开关配套。
// 页面是 http 而后端是 https 时，浏览器会按「混合内容」拦掉接口请求，故两端协议需一致。
// 用法（证书可用 backend/tools/gen_self_signed_cert.py 生成）：
//   VITE_HTTPS=1 VITE_CERT=../backend/certs/server.crt VITE_KEY=../backend/certs/server.key npm run dev
// 不设这些变量时行为完全不变（仍是 http://host:5173）。
const certPath = process.env.VITE_CERT
const keyPath = process.env.VITE_KEY
const useHttps = process.env.VITE_HTTPS === '1' && certPath && keyPath &&
  fs.existsSync(certPath) && fs.existsSync(keyPath)

export default defineConfig({
  plugins: [svelte()],
  server: {
    port: 5173,
    host: '0.0.0.0',
    ...(useHttps ? { https: { cert: fs.readFileSync(certPath), key: fs.readFileSync(keyPath) } } : {})
  }
})
