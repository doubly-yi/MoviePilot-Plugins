// 仅本地 UI 测试：不进入发布压缩包，不访问真实 bp 服务。
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import federation from '@originjs/vite-plugin-federation'
import { readFileSync } from 'node:fs'
import { resolve, sep } from 'node:path'
export default defineConfig({
  plugins: [{ name:'bp-preview-built-assets', configureServer(server) {
    // dist 默认不受 Vite watch 管理；原样提供构建产物，避免旧的转换缓存。
    server.middlewares.use('/dist', (req, res, next) => {
      const root = resolve('dist')
      const file = resolve(root, '.' + (req.url || '').split('?')[0])
      if (!file.startsWith(root + sep)) return next()
      try {
        const data = readFileSync(file)
        res.setHeader('Cache-Control', 'no-store')
        res.setHeader('Content-Type', file.endsWith('.css') ? 'text/css' : 'application/javascript')
        res.end(data)
      } catch { next() }
    })
  } }, vue(), federation({
    name:'BpPreviewHost', remotes:{bppulse:'http://127.0.0.1:5179/dist/assets/remoteEntry.js'},
    shared:['vue'],
  })],
  server:{port:5179, strictPort:true, proxy:{'/api':'http://127.0.0.1:8791'}},
})
