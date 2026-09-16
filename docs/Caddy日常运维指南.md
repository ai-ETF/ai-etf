# Caddy 日常运维指南（云服务器）

> 适用范围：本指南基于本项目在阿里云 ECS（Linux / Ubuntu 24.04）上部署的 Caddy 编写，
> 涵盖日常巡检、配置修改、HTTPS 证书、日志、备份、升级与故障排查。
> 本文中的命令默认使用 `root` 或具有 `sudo` 权限的用户执行。

---

## 1. 概述

### 1.1 本项目 Caddy 部署情况

| 项目 | 值 |
|---|---|
| 版本 | Caddy 2.6.2（Ubuntu 官方源安装） |
| 配置路径 | `/etc/caddy/Caddyfile` |
| 监听端口 | 80（HTTP）、443（HTTPS） |
| 上游应用 | FastAPI（`127.0.0.1:8000`） |
| 证书 | Let's Encrypt 自动签发 + 自动续期 |
| 服务管理 | systemd（`caddy.service`） |

### 1.2 当前 Caddyfile

```caddyfile
# /etc/caddy/Caddyfile
ai-etf.xyz {
	reverse_proxy 127.0.0.1:8000
}

# www 重定向到主域名
www.ai-etf.xyz {
	redir https://ai-etf.xyz{uri} permanent
}
```

行为说明：
- `https://ai-etf.xyz` 反代到本地 FastAPI；
- `http://` 访问自动 308 跳转到 HTTPS（Caddy 默认行为）；
- `https://www.ai-etf.xyz` 301 永久跳转到主域名。

---

## 2. 常用运维命令

### 2.1 状态查看

```bash
# 服务运行状态（active/running、主进程 PID、最近日志）
systemctl status caddy

# 仅看是否存活
systemctl is-active caddy
```

### 2.2 修改配置并生效

```bash
# 1) 先校验配置语法（推荐，避免把服务改挂）
caddy validate --config /etc/caddy/Caddyfile

# 2) 热重载（不中断连接，推荐日常使用）
systemctl reload caddy

# 3) 确认已生效
systemctl status caddy
```

> **为什么用 reload 而不是 restart？**
> `reload` 是零停机热更新，正在进行的请求不会中断；
> `restart` 会短暂断开全部连接，仅在 reload 无法生效时才使用。

### 2.3 停止 / 启动 / 重启

```bash
systemctl stop caddy      # 停止
systemctl start caddy     # 启动
systemctl restart caddy   # 重启（会短暂断连）
systemctl enable caddy    # 开机自启（安装时通常已配置好）
```

### 2.4 服务开机自启确认

```bash
systemctl is-enabled caddy   # 输出 enabled 即为开机自启
```

---

## 3. 配置文件管理

### 3.1 配置规范

- 主配置固定为 `/etc/caddy/Caddyfile`，不要改路径；
- 修改前**先备份**，再编辑，再校验，最后 reload（顺序不可颠倒）；
- Caddy 配置对**缩进**敏感（默认使用 Tab），复制粘贴时注意不要被转成空格。

### 3.2 安全修改流程（示例）

```bash
# 备份
cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak.$(date +%Y%m%d)

# 编辑
vim /etc/caddy/Caddyfile

# 校验
caddy validate --config /etc/caddy/Caddyfile

# 生效
systemctl reload caddy
```

### 3.3 配置文件位置速查

| 用途 | 路径 |
|---|---|
| 主配置 | `/etc/caddy/Caddyfile` |
| 证书与账号数据 | `/var/lib/caddy/.local/share/caddy/` |
| 运行时数据 | `/var/lib/caddy/.config/caddy/` |
| 系统日志 | journald（见第 5 节） |

---

## 4. HTTPS / 证书管理

### 4.1 证书自动签发与续期

Caddy 使用 ACME（Let's Encrypt）自动申请证书，并在到期前**自动续期**（通常在到期前 30 天左右触发），**无需人工干预**。续期成功后会自动 reload，全程零停机。

### 4.2 查看当前证书

```bash
caddy list-modules | grep tls   # 确认 ACME 模块存在

# 直接查看 443 端口当前证书的过期时间（从本机测）
echo | openssl s_client -connect 127.0.0.1:443 -servername ai-etf.xyz 2>/dev/null \
  | openssl x509 -noout -dates -subject -ext subjectAltName
```

### 4.3 证书存储

- 证书与私钥保存在 `/var/lib/caddy/.local/share/caddy/certificates/`；
- **不要手工删除**该目录，删除会导致证书重新申请；
- 备份时建议一并打包该目录。

### 4.4 强制续期（仅在证书异常时使用）

```bash
# 删除本地证书缓存后 reload，Caddy 会重新向 Let's Encrypt 申请
rm -rf /var/lib/caddy/.local/share/caddy/certificates/*
systemctl restart caddy
```

> ⚠️ 注意：短时间内频繁重新申请可能触发 Let's Encrypt 限流（每域每周 5 次）。
> 只在证书损坏或确实异常时使用。

### 4.5 证书申请失败排查

- **80/443 端口未放行**：云服务器需在安全组放行 80、443；本机防火墙（ufw/firewalld）也需放行；
- **域名未解析到本机 IP**：确保 DNS 的 A 记录指向当前 ECS 公网 IP；
- **域名未备案（大陆节点）**：阿里云会对未备案域名做 ICP 拦截，HTTPS 申请与访问都会被云层阻断，需先在阿里云控制台完成备案。

---

## 5. 日志查看

Caddy 通过 journald 记录日志：

```bash
# 最近 50 行
journalctl -u caddy -n 50

# 实时跟踪
journalctl -u caddy -f

# 查看某一天的日志
journalctl -u caddy --since "2026-08-29" --until "2026-08-30"

# 只看错误级别
journalctl -u caddy -p err -n 50
```

常见日志含义：
- `"error": "acme: error ..."`：证书申请失败，按 4.5 排查；
- `certificate obtained successfully`：证书签发成功，正常信息；
- `server is listening only on the HTTPS port`：正常，Caddy 已开始服务。

---

## 6. 备份与恢复

### 6.1 备份内容

建议备份三部分：

```bash
# 1) 配置文件
cp /etc/caddy/Caddyfile /backup/caddy/Caddyfile.$(date +%Y%m%d)

# 2) 证书数据（含 Let's Encrypt 账号，恢复后不会重新申请）
tar -czf /backup/caddy/caddy-data-$(date +%Y%m%d).tar.gz \
  -C /var/lib/caddy .local/share/caddy .config/caddy
```

### 6.2 恢复

```bash
# 恢复配置文件
cp /backup/caddy/Caddyfile.20260822 /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy

# 恢复证书数据
tar -xzf /backup/caddy/caddy-data-20260822.tar.gz -C /var/lib/caddy
systemctl restart caddy
```

### 6.3 本项目历史备份

- 服务器：`/root/backup/ai-etf-pre-caddy-20260822.tar.gz`（迁移前完整备份）
- 本地：`/home/sing/server-backup-aietf/ai-etf-pre-caddy-20260822.tar.gz`
- 校验和：`ac66e5fa776af0574089d18868ef1267`

---

## 7. 升级 Caddy

### 7.1 为什么建议升级

当前服务器安装的是 Ubuntu 源里的 **2.6.2（2022 年）**，版本较旧。建议升级到
Caddy 官方最新版，以获得安全更新与功能修复。

### 7.2 升级方式

```bash
# 添加 Caddy 官方源并升级
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list

sudo apt update
sudo apt install caddy   # 或 sudo apt upgrade caddy
```

> 升级后校验配置是否仍合法：
> ```bash
> caddy version
> caddy validate --config /etc/caddy/Caddyfile
> systemctl restart caddy
> ```

> ⚠️ 升级前建议先备份证书数据（见第 6 节），避免意外。

---

## 8. 常见故障排查

### 8.1 外网无法访问

按顺序检查：

```bash
# 1) Caddy 是否存活
systemctl status caddy

# 2) 端口是否在监听
ss -tlnp | grep -E ':(80|443)'

# 3) 从本机回环验证是否可达（区分"服务问题"和"外网问题"）
curl -sS -I http://ai-etf.xyz        # 期望 308 → https
curl -sS -I https://ai-etf.xyz       # 期望 200 / 上游响应头
curl -sS http://127.0.0.1:8000       # 直接测上游 FastAPI 是否存活

# 4) 域名解析是否正确
dig +short ai-etf.xyz

# 5) 安全组 / 防火墙是否放行 80、443（云控制台 + 本机）
ufw status
```

### 8.2 HTTP 返回 403 / 页面被"Non-compliance ICP Filing"拦截

- 特征：响应头 `Server: Beaver`，页面标题为 `Non-compliance ICP Filing`；
- 原因：**阿里云对未备案域名的 ICP 拦截**，属于云层限制，与 Caddy 无关；
- 解决：在[阿里云备案控制台](https://beian.aliyun.com/)完成备案，通过后自动放行，Caddy 侧无需改动。

### 8.3 HTTPS 连接被重置

- 多为 8.2 的备案拦截，或安全组未放行 443；
- 先确认 `ss -tlnp` 显示 443 有 Caddy 监听，再按 4.5 排查。

### 8.4 修改配置后 reload 报错

```bash
# 回退到最近备份并重载
cp /etc/caddy/Caddyfile.bak.20260829 /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy
```

### 8.5 端口被占用

```bash
# 找出占用 80/443 的进程（如旧 nginx）
ss -tlnp | grep -E ':(80|443)'
# 若为 nginx 残留，停用并禁用
systemctl stop nginx && systemctl disable nginx
```

---

## 9. 安全建议

1. **及时升级**：保持 Caddy 为最新稳定版（见第 7 节）；
2. **SSH 登录加固**：建议改用密钥登录并禁用密码登录，避免弱口令风险；
3. **最小权限**：Caddy 本身以独立低权限用户 `caddy` 运行，无需改动；
4. **定期备份**：配置 + 证书数据至少每月备份一次，异地留存一份；
5. **监听收窄**：`reverse_proxy` 保持指向 `127.0.0.1` 的回环地址，不要让上游
   FastAPI 暴露到公网。

---

## 10. 日常巡检清单（建议）

| 频率 | 检查项 | 命令 |
|---|---|---|
| 每周 | 服务存活 | `systemctl is-active caddy` |
| 每周 | 证书剩余有效期 | 见 4.2 的 openssl 命令 |
| 每周 | 日志有无报错 | `journalctl -u caddy -p err -n 20` |
| 每月 | 备份配置与证书 | 见第 6 节 |
| 每月 | 版本检查 | `caddy version` |
| 变更时 | 配置合法性 | `caddy validate --config /etc/caddy/Caddyfile` |

---

*文档基于本项目实际部署环境编写（阿里云 ECS + Ubuntu 24.04 + Caddy 2.6.2 + FastAPI:8000）。*
