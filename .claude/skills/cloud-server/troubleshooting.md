# 第 4 步：故障排查

仅在连接或操作报错时读取本文件。

| 现象 | 原因 | 处理 |
|------|------|------|
| 端口 22 被拒/超时，但 443 正常 | fail2ban 类防护对快速密码连接间歇封禁 | 等待 15-20s 再试；合并操作为少量连接；不要连续重连 |
| `Permission denied (publickey,password)` | 本机公钥未装到服务器（决策已定不走密钥） | 预期行为：用 `sshpass` 密码连接，忽略此报错 |
| 密码文件权限错误 | 权限非 600 | `chmod 600 ~/.ssh/47.113.220.182.pass` |
| 服务健康检查返回 000 | 应用启动预热慢（加载 1594 只 ETF，约 30s） | 等待后重试 `curl`，不要立刻判定失败 |
| 远程命令无输出/挂起 | 命令等待交互输入 | 检查命令是否缺非交互参数（如 `-y`） |
| `!` 前缀命令报 `No such file or directory` | 多行粘贴/特殊字符被转义截断 | 改用单行命令；避免 `>`、`&&` 等字符 |
| `'list' object has no attribute 'users'` | supabase-py 版本返回结构不同 | 兼容处理：`page.users if hasattr(page,'users') else page` |
