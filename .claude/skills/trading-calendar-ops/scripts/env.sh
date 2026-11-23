# 交易日历运维命令环境。
# Bash 工具的 shell 状态不跨调用保留，所以每次执行命令前都先 source 本文件：
#   source /home/sing/ai-etf/.claude/skills/trading-calendar-ops/scripts/env.sh
#
# 提供：
#   $SSH       连接生产服务器的 ssh 命令
#   $TOKEN     取出 ADMIN_API_TOKEN 的命令前缀，用法：$SSH "$TOKEN curl ..."
#   $SKILL_DIR 技能目录，用于引用 scripts/ 下的脚本

SKILL_DIR=/home/sing/ai-etf/.claude/skills/trading-calendar-ops
SSH_PASSFILE="$HOME/.ssh/47.113.220.182.pass"
SSH="sshpass -f $SSH_PASSFILE ssh -p 22 -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 root@47.113.220.182"
# token 只在远端 shell 内展开，不打印、不落盘。
TOKEN='TOKEN=$(systemctl show fastapi -p Environment --value | tr " " "\n" | sed -n "s/^ADMIN_API_TOKEN=//p"); '
