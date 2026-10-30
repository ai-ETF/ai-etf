---
name: deploy
disable-model-invocation: true
description: 把指定分支的代码部署到云服务器 47.113.220.182 的 /root/ai-etf 并重启 fastapi 服务。
---

# 部署到云服务器

把指定分支的代码同步到生产服务器。**首次拉取用「复制远程分支」建分支，不要用 merge**——两边 base 不同时 merge 会引入冲突和多余提交。

**前置条件**：要部署的分支必须**已推送到 GitHub**——本 skill 是从 `origin` 拉取，不是从本地推。

## 部署目标（实测确认，勿凭记忆改）

| 项 | 值 |
|---|---|
| 服务器 | `47.113.220.182`（连接与凭据见 [`cloud-server`](../cloud-server/SKILL.md)） |
| **部署目录** | **`/root/ai-etf`** ← 以此为准，也是 systemd 的 `WorkingDirectory` |
| 服务 | `fastapi.service`（`User=root`） |
| 启动命令 | `/root/ai-etf/.venv/bin/uvicorn server.app:app --host 0.0.0.0 --port 8000` |
| 外部地址 | `https://ai-etf.xyz` |

```bash
# 统一变量，后续命令复用
BRANCH="<要部署的分支名>"          # 由 和远程分支同名
APP_DIR=/root/ai-etf
SVC=fastapi
SSH_PASSFILE="$HOME/.ssh/47.113.220.182.pass"
SSH="sshpass -f $SSH_PASSFILE ssh -p 22 -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 root@47.113.220.182"
```

> 原则：把每个步骤**合并进一次 ssh 连接**（服务器有 fail2ban 类防护，频繁连接会被临时封禁）。

## 第 1 步：判定属于哪种情况

```bash
$SSH "cd $APP_DIR && if git rev-parse --verify --quiet '$BRANCH' >/dev/null; then echo 情况二已有该分支; else echo 情况一首次拉取; fi"
```

- 输出「情况一」→ 走 A 节
- 输出「情况二」→ 走 B 节

## A. 首次拉取该分支

```bash
$SSH "cd $APP_DIR && set -e
BEFORE=\$(git rev-parse HEAD)
git fetch origin
git checkout -b '$BRANCH' 'origin/$BRANCH'
AFTER=\$(git rev-parse HEAD)
echo '--- 分支 ---'; git branch --show-current
echo '--- HEAD ---'; echo \"\$BEFORE -> \$AFTER\"
echo '--- 本次新增提交 ---'; git log --oneline \"\$BEFORE..\$AFTER\" | head -20"
```

`git checkout -b <分支> origin/<分支>` 会把本地分支直接指到远程分支的位置，等价于「复制」；它同时会把上游设为 `origin/<分支>`。

## B. 之前拉过

```bash
$SSH "cd $APP_DIR && set -e
git switch '$BRANCH'
BEFORE=\$(git rev-parse HEAD)
git fetch origin
git pull origin '$BRANCH'
AFTER=\$(git rev-parse HEAD)
echo '--- 分支 ---'; git branch --show-current
echo '--- HEAD ---'; echo \"\$BEFORE -> \$AFTER\"
echo '--- 本次新增提交 ---'; git log --oneline \"\$BEFORE..\$AFTER\" | head -20"
```

## 第 2 步：汇报，等待确认

把上一步的输出（分支名、HEAD 变化、新增提交列表）**完整展示给用户**，然后**停下等待确认**。

⚠️ 不要跳过这一步直接重启。重启会造成短暂停机，且涉及生产环境。

## 第 3 步：确认后重启并验证

```bash
$SSH "systemctl restart $SVC && sleep 2 && systemctl is-active $SVC && systemctl show $SVC -p ActiveEnterTimestamp --value"
```

**验证生效**（这一步不能省）：

```bash
# 进程启动时间应为刚刚（对比部署时间）
$SSH "systemctl show $SVC -p ActiveEnterTimestamp --value"

# 外部可达
curl -s -o /dev/null -w '%{http_code}\n' https://ai-etf.xyz/
```

- 启动时间**没有变化** → 没重启成功，代码不会生效，回上一步排查。
- 健康检查首次可能返回 `000`：应用预热要加载全量 ETF（约 30s），等待后重试，**不要立刻判定失败**。

## 红线

- ❌ **只在 `/root/ai-etf` 里操作 git**。绝不在 `/root/ai-etf/ai-etf` 执行任何 git 命令——那是历史遗留的内层 clone（remote 指向 `https://`、停在旧提交），**不是部署目录**。拉错目录是这套环境最容易犯的错。
- ❌ 部署分支**不用 merge**（不用 `git merge` / `git rebase`），一律用 A 节的复制方式。
- ❌ **不擅自重启**：第 1 步做完必须停下汇报，等用户确认。
- ❌ 不在服务器上 `git push`、不改远端分支（部署是只读拉取）。
- ❌ 不把密码写入任何文件、日志或输出（凭据规则见 cloud-server）。

## 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `checkout` 报 `local changes would be overwritten` | 部署目录有未提交改动挡住了切换 | 先 `git -C $APP_DIR status` 给用户看；**确认无用后**才 `git -C $APP_DIR checkout -- .` 再重试 |
| `checkout -b` 报 `already exists` | 其实本地已有该分支 | 回第 1 步，改走 B 节 |
| A 节 `git fetch` 超时/卡住 | 服务器到 GitHub 的 deploy key 或网络问题 | `$SSH "timeout 25 git -C $APP_DIR fetch --dry-run origin"` 复测；仍失败见 cloud-server 的 troubleshooting |
| 重启后接口行为没变 | **代码同步 ≠ 生效** | 对比 `ActiveEnterTimestamp` 与部署时间；没变说明进程没真正重启 |
| 健康检查 `000` / 超时 | 应用预热慢（约 30s） | 等一会儿再 `curl`，不要立刻判定失败 |
| `systemctl is-active` 非 `active` | 启动失败 | `$SSH "journalctl -u $SVC -n 50 --no-pager"` 看日志 |
