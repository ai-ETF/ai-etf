# 第 2 步：连接测试

每次会话开始先验证连通性；连接异常时也回到这里处理。

## 轻量连通测试

```bash
sshpass -f "$HOME/.ssh/47.113.220.182.pass" ssh -p 22 -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 root@47.113.220.182 "uptime"
```

✅ 有正常回显（uptime 输出）→ 进入[第 3 步：常用操作](./operations.md)

## 连接失败 → 可能是 fail2ban 类间歇封禁

现象：端口 22 连接被拒/超时，但服务器 443（HTTPS）正常；密码正确却连不上；报 `Connection timed out` / `Permission denied`。

处置：

1. **不要连续重连**。等待 15-20 秒再试一次。
2. 尽量把后续操作**合并进更少的连接**（一次 ssh 内用 `;` 分隔多条命令）。
3. 仍失败 → 见[第 4 步：故障排查](./troubleshooting.md)
