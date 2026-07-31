# CodeGraph 安装与配置指南

> 项目地址：https://github.com/colbymchenry/codegraph

CodeGraph 是一个代码索引工具，通过 MCP 协议与 AI 编程助手（Claude Code、Cursor 等）集成，提供代码结构搜索、调用链分析、影响范围评估等能力。

---

## 1. 安装 CLI

- 请先安装 nodeJS

```bash
codegraph --version #检验指令,有时检验不到也不知为什么
which codegraph #有路径就说明可以
npm i -g @colbymchenry/codegraph
```

CodeGraph 自带运行时，无需编译原生模块，跨平台一致。安装后 `codegraph` 命令会加入 PATH，但**当前终端不会立即生效**，需要重开一个终端。

升级命令：

```bash
codegraph upgrade          # 自动检测安装方式并升级
codegraph upgrade --check  # 仅检查是否有新版本
codegraph upgrade <version> # 锁定指定版本
```

## 2. 连接 AI 代理

```bash
codegraph install
```

> **⚠️ 注意**：该命令会弹出交互式选择界面，**需要选中** "Claude Code"，然后回车确认。

该命令会自动检测并配置以下 AI 代理的 MCP 服务器：

> **注意**：这一步只连接代理，不索引代码。索引是下一步 `codegraph init` 的事。

快捷方式（一步完成下载 + 安装）：

```bash
npx @colbymchenry/codegraph
```

## 3. 初始化项目

进入项目目录，构建代码索引：

```bash
cd your-project
codegraph init
```

这会在项目根目录生成 `.codegraph/` 目录，包含代码结构的索引数据。

## 4. 手动配置（推荐——如自动安装失败）

如果 `codegraph install` 未成功，或想确保配置正确，可以用以下方式手动注册 MCP 服务器：

### 4.1 注册 MCP 服务器

```bash
claude mcp add codegraph -s user -- codegraph serve --mcp --path /absolute/path/to/your/project
```

### 4.2 验证 MCP 连接

```bash
# 检查 MCP 服务器是否连接成功（必须看到 ✔ Connected）
claude mcp list

# 查看详情
claude mcp get codegraph
```

### 4.3 重启 Claude Code 会话

**MCP 服务器只在会话启动时加载。** 配置之后必须退出并重启 Claude Code，才能生效。

重启后可用 `/mcp` 命令确认 codegraph 已加载。

## 自动同步

CodeGraph 默认开启自动同步（auto-sync）。它会监听项目文件变化，在 AI 代理编辑代码或你手动增删改文件时自动更新索引，**无需手动重新构建**。

## 卸载

```bash
codegraph uninstall
```

该命令会：
- 移除所有已配置代理中的 MCP 服务器配置、指令和权限
- **不会删除**项目的 `.codegraph/` 索引目录

如需删除索引：

```bash
codegraph uninit            # 在项目目录下执行
```

可选参数：
- `--target` — 仅从指定代理移除
- `--yes` — 非交互模式，直接执行
