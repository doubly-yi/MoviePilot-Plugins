import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import federation from '@originjs/vite-plugin-federation'
export default defineConfig({
  plugins: [vue(), federation({
    name: 'BpPulseSignin', filename: 'remoteEntry.js',
    exposes: { './Page': './src/components/Page.vue', './Config': './src/components/Config.vue' },
    shared: { vue: { requiredVersion: false, generate: false } },
    format: 'esm',
  })],
  build: { target: 'esnext', cssCodeSplit: true, rollupOptions: { input: './src/entry.js' } },
  css: { postcss: { plugins: [{ postcssPlugin: 'bp-no-global-dependency-css', Root(root) {
    const path = root.source?.input?.file?.replaceAll('\\', '/') || ''
    if (path.includes('/node_modules/vuetify/') || path.includes('/node_modules/@mdi/')) root.removeAll()
  } }] } },
})
