# 第 3 步：常用操作

确认连通后使用。统一变量，不要散落硬编码：

```bash
SSH_HOST="47.113.220.182"
SSH_PORT=22
SSH_USER="root"
SSH_PASSFILE="$HOME/.ssh/47.113.220.182.pass"
SSH_OPTS="-p ${SSH_PORT} -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
```

## 3.1 执行单条远程命令

```bash
sshpass -f "$SSH_PASSFILE" ssh $SSH_OPTS "${SSH_USER}@${SSH_HOST}" "<远程命令>"
```

示例：

```bash
# 查看负载与磁盘
sshpass -f "$SSH_PASSFILE" ssh $SSH_OPTS root@47.113.220.182 "uptime && df -h"
# 查看服务状态（systemd）
sshpass -f "$SSH_PASSFILE" ssh $SSH_OPTS root@47.113.220.182 "systemctl status fastapi --no-pager"
# 查看 Docker 容器
sshpass -f "$SSH_PASSFILE" ssh $SSH_OPTS root@47.113.220.182 "docker ps"
```

## 3.2 进入交互式 Shell（用户自己登录）

让用户在本会话输入（`!` 前缀当场执行并把输出带回会话）。**务必保持单行**——`!` 下多行粘贴只会执行第一行：

```
! sshpass -f ~/.ssh/47.113.220.182.pass ssh -p 22 -o StrictHostKeyChecking=accept-new root@47.113.220.182
```

## 3.3 传输文件（scp）

```bash
# 上传
sshpass -f "$SSH_PASSFILE" scp $SSH_OPTS ./本地文件 root@47.113.220.182:/目标/路径/
# 下载
sshpass -f "$SSH_PASSFILE" scp $SSH_OPTS root@47.113.220.182:/远端/文件 ./本地目录/
```

操作中报错 → 见[第 4 步：故障排查](./troubleshooting.md)
