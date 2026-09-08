# bp PULSE 插件开发与验证

以下内容面向插件维护者。使用说明见 [插件 README](../plugins.v2/bppulsesignin/README.md)。

## 安装与发布

当前面向本地核对的 MP V2 接口，索引限制为 `>=2.15.6,<3`；尚未在完整 MP 运行环境中加载实测，不声明 V3 兼容。

本地开发可通过 MP 的 `PLUGIN_LOCAL_REPO_PATHS` 配置本仓库，安装此插件并开启 `PLUGIN_AUTO_RELOAD`。`DEV=true` 会暂停宿主定时任务，验证 Cron 时需注意该设置。

Vue 联邦组件已构建在 `dist/assets/`。插件市场使用 GitHub Release 分发，先发布 `BpPulseSignin_v1.0.0`，附带 `bppulsesignin_v1.0.0.zip`，再通过第三方插件仓库安装。没有对应 Release 时，市场安装不可用。

仓库已提供 `.github/workflows/bppulse-release.yml`：推送 `package.v2.json` 至 `main` 或手动运行时执行测试、构建和打包；已有 Release 不覆盖。更新版本时同时修改 Python `plugin_version`、`package.v2.json`、插件前端 `package.json` / 锁文件及更新日志。本次开发仅生成本地安装包，未推送或发布。

手动打包（从仓库根目录）：

```bash
npm ci --prefix plugins.v2/bppulsesignin
npm run typecheck --prefix plugins.v2/bppulsesignin
npm run build --prefix plugins.v2/bppulsesignin
python3 tools/package_bppulse.py
```

安装包输出到 `.release/`，压缩包根目录直接是插件文件，不含测试、node_modules 或预览宿主。

## 验证

后端测试覆盖真实插件业务与 FastAPI 路由，宿主数据库、通知、调度器和 bp 请求使用替身。测试导入名与生产一致，为 `app.plugins.bppulsesignin`。

```bash
# 使用独立测试环境，勿将这些固定版本安装进运行中的 MP 环境
python3 -m venv /tmp/bp-plugin-tests
/tmp/bp-plugin-tests/bin/pip install -r tests/v2/bppulsesignin/requirements.txt
/tmp/bp-plugin-tests/bin/python -m pytest tests/v2/bppulsesignin -q
```

浏览器交互测试（两个终端，从仓库根目录运行）：

```bash
/tmp/bp-plugin-tests/bin/python tests/v2/bppulsesignin/ui_server.py
npm run preview-ui --prefix plugins.v2/bppulsesignin
```

访问 `http://127.0.0.1:5179`。预览加载编译后的联邦组件，通过真实插件 API 操作内存中的模拟账号；验证码为 `123456`，不连接真实 bp 服务。预览服务关闭后模拟数据消失。

发布前还需在真实 MP V2 中验证安装发现、页面加载、定时服务及通知渠道，并使用自己的账号完成短信登录和签到。
