#!/bin/bash
# ============================================================
# e2e-testing skill 同步脚本
#
# 背景：这个 skill 在 ai-etf 与 application 两个仓库各存一份，内容必须
# 逐字节一致——前端同学和后端同学读的必须是同一份规范，否则"两边都说
# 按规范做了"却对不上。手工 rsync 容易漏，而且漏了没人发现，所以固定
# 成脚本：同步 + 校验一步做完。
#
# ai-etf 那份是**唯一真源**：docs/e2e/00-06 在 ai-etf，skill 由它派生。
# 所以永远是 ai-etf → application 单向同步，不要反向拉。
#
# 用法：
#   ./sync_e2e_skill.sh            # 同步 ai-etf → application
#   ./sync_e2e_skill.sh --check    # 只校验是否一致，不写入（提交前 / CI 用）
#   ./sync_e2e_skill.sh --dry-run  # 预览会改哪些文件，不写入
#
# 目标仓库不在隔壁时用环境变量指定：
#   E2E_SKILL_DEST=/path/to/application/.claude/skills/e2e-testing ./sync_e2e_skill.sh
#
# 退出码：0 = 一致 / 同步成功；1 = 不一致（--check）或出错
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AI_ETF_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

SOURCE="$AI_ETF_ROOT/.claude/skills/e2e-testing"
DEST="${E2E_SKILL_DEST:-$AI_ETF_ROOT/../application/.claude/skills/e2e-testing}"

MODE="sync"
for arg in "$@"; do
    case "$arg" in
        --check)   MODE="check" ;;
        --dry-run) MODE="dryrun" ;;
        -h|--help) sed -n '2,26p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) echo "❌ 未知参数：$arg（可用：--check / --dry-run / --help）"; exit 1 ;;
    esac
done

# ==================== 前置校验 ====================
command -v rsync >/dev/null 2>&1 || { echo "❌ 找不到 rsync，请先安装"; exit 1; }

[ -f "$SOURCE/SKILL.md" ] || {
    echo "❌ 源不完整：找不到 $SOURCE/SKILL.md"
    exit 1
}

# ⚠️ 安全闸门：下面会用到 rsync --delete（破坏性），所以只允许作用在
# 名字确认为 e2e-testing 的目录上。这样即使 E2E_SKILL_DEST 被写错成
# 一个已有的目录，也会在这里被拦下来，而不是把里面的东西删掉。
case "$DEST" in
    */e2e-testing) ;;
    *) echo "❌ 目标路径必须以 /e2e-testing 结尾（防止 --delete 误删别的目录）："
       echo "   $DEST"
       exit 1 ;;
esac

if [ ! -d "$(dirname "$DEST")" ]; then
    echo "❌ 目标仓库不存在：$(dirname "$DEST")"
    echo "   若 application 不在 ai-etf 的隔壁，用 E2E_SKILL_DEST=... 指定"
    exit 1
fi

SRC_COUNT=$(find "$SOURCE" -type f | wc -l | tr -d ' ')

# 规范化路径，避免输出里出现 ai-etf/../application 这种难读的写法
if [ -d "$DEST" ]; then
    DEST="$(cd "$DEST" && pwd)"
else
    DEST="$(cd "$(dirname "$DEST")" && pwd)/$(basename "$DEST")"
fi

echo "============================================================"
echo "  e2e-testing skill 同步"
echo "------------------------------------------------------------"
echo "  源    : $SOURCE"
echo "  目标  : $DEST"
echo "  文件数: $SRC_COUNT（源）"
echo "  模式  : $MODE"
echo "============================================================"

# ==================== --dry-run：只预览 ====================
if [ "$MODE" = "dryrun" ]; then
    [ -d "$DEST" ] || { echo "⚠️  目标目录不存在，首次运行会整体创建"; }
    echo ""
    echo "--- 将发生的变更（rsync 预览，未写入）---"
    if [ -d "$DEST" ]; then
        rsync -an --delete --itemize-changes "$SOURCE/" "$DEST/"
    else
        echo "  [新建] $DEST（$SRC_COUNT 个文件）"
    fi
    echo "--- 预览结束，未改动任何文件 ---"
    exit 0
fi

# ==================== --check：只校验 ====================
if [ "$MODE" = "check" ]; then
    if [ ! -d "$DEST" ]; then
        echo "❌ 目标目录不存在：$DEST"
        exit 1
    fi
    echo ""
    if DIFF_OUT=$(diff -rq "$SOURCE" "$DEST" 2>&1); then
        echo "✅ 两份 skill 逐字节一致（$SRC_COUNT 个文件）"
        exit 0
    else
        echo "❌ 两份 skill 不一致，请运行 ./sync_e2e_skill.sh 同步："
        echo ""
        echo "$DIFF_OUT" | sed 's/^/    /'
        exit 1
    fi
fi

# ==================== 同步 ====================
rsync -a --delete "$SOURCE/" "$DEST/"

# 校验：同步完立刻验一遍，避免"以为同步了"（rsync 成功 ≠ 内容一定一致，
# 比如目标目录恰好在另一个挂载点 / 被并发改动）
echo ""
if DIFF_OUT=$(diff -rq "$SOURCE" "$DEST" 2>&1); then
    DEST_COUNT=$(find "$DEST" -type f | wc -l | tr -d ' ')
    echo "✅ 同步完成并校验通过：$SRC_COUNT 个文件，两侧一致"
    echo "   目标：$DEST"
    echo ""
    echo "   别忘了：这份 skill 属于两个仓库，提交时要**分别**在"
    echo "   ai-etf 和 application 提交，否则两边又会不一致。"
else
    echo "❌ 同步后校验仍不一致，请手工检查："
    echo ""
    echo "$DIFF_OUT" | sed 's/^/    /'
    exit 1
fi
