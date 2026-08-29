#!/usr/bin/env bash
#
# 公开接口一键冒烟测试（无需 JWT / 账号）
#
# 用法：
#   bash docs/api/scripts/smoke_test.sh                      # 默认远程 https://ai-etf.xyz
#   bash docs/api/scripts/smoke_test.sh --url http://localhost:8000
#
set -u

API="https://ai-etf.xyz"
[ $# -ge 2 ] && [ "$1" = "--url" ] && API="$2"

PASS=0
FAIL=0

check() {
  local name="$1" cmd="$2" expect="$3"
  local body
  body=$(eval "$cmd" 2>/dev/null)
  if echo "$body" | grep -q "$expect"; then
    echo "✅ $name"
    PASS=$((PASS + 1))
  else
    echo "❌ $name  (响应: ${body:0:120})"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== 冒烟测试: $API ==="
echo ""

check "根路径健康检查"     "curl -s '$API/'"                                '"Hello"'
check "test 端点"          "curl -s '$API/api/test/hello'"                   '"message"'
check "上传模块健康"       "curl -s '$API/api/upload/health'"                '"healthy"'
check "组合模块健康"       "curl -s '$API/api/portfolio/health'"             '"ok"'
check "自选股模块健康"     "curl -s '$API/api/watchlist/health'"             '"ok"'
check "行情模块健康"       "curl -s '$API/api/market/health'"                '"ok"'
check "风险模块健康"       "curl -s '$API/api/risk/health'"                  '"ok"'
check "实时行情"           "curl -s '$API/api/market/spot/512890'"           '"code"'
check "涨幅榜"             "curl -s '$API/api/market/ranking?top_n=5'"       '"items"'
check "搜索"               "curl -s --get '$API/api/market/search' --data-urlencode 'keyword=红利' --data-urlencode 'top_n=5'" '"items"'
check "高级筛选"           "curl -s -X POST '$API/api/market/filter' -H 'Content-Type: application/json' -d '{\"keyword\":\"ETF\",\"top_n\":5}'" '"items"'

echo ""
echo "=== 结果: $PASS 通过, $FAIL 失败 ==="
[ "$FAIL" -eq 0 ]
