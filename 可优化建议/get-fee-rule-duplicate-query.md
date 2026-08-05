# get_fee_rule 重复远程查询效率问题

## 问题描述

`get_fee_rule()` 每次调用都是一次完整的 Supabase REST API 请求（`SELECT * FROM fund_fee_rules WHERE fund_code = ?`），同一只基金、同一次请求、同一时刻的费率规则不可能变化，但代码中存在重复调用。

## 逐流程调用链分析

### 1. 申购流程 `apply_purchase()` — ✅ 已优化为 1 次查询

```
apply_purchase()
├─ L216: rule = fee_svc.get_fee_rule(fund_code)          ← 唯一1次远程查询
├─ L262: _calc_purchase_fee(fund_code, amount, rule=rule) ✅ rule传入，跳过查询
└─ L269: _get_fund_name(fund_code, rule=rule)             ✅ rule传入，直接取fund_name
```

### 2. 赎回流程 `apply_redeem()` — ✅ 已优化为 1 次查询

```
apply_redeem()
├─ L349: rule = fee_svc.get_fee_rule(fund_code)          ← 唯一1次远程查询
└─ L420: _get_fund_name(fund_code, rule=rule)             ✅ rule传入，直接取fund_name
```

### 3. 确认流程 `_confirm_one_order()` — ⚠️ 批量场景有重复

单笔确认已优化为 1 次查询（rule 透传生效），但 `confirm_pending_orders()` 批量循环中每笔订单独立调用 `get_fee_rule`，无跨订单去重：

```
confirm_pending_orders()
├─ 查询所有 pending 订单（N 笔，涉及 M 只不同基金）
└─ for order in orders:
    └─ _confirm_one_order(order, today)
        ├─ fee_svc = FundFeeService()                    ← 每次循环新建实例
        └─ rule = fee_svc.get_fee_rule(fund_code)        ← 每笔订单1次远程查询
```

## 效率量化

| 场景 | pending 订单数 | 涉及不同基金数 | 实际远程查询 | 理论最少查询 | 浪费 |
|------|-------------|-------------|-----------|----------|------|
| 单笔申购 | 0 | 1 | 1 | 1 | 0 |
| 单笔赎回 | 0 | 1 | 1 | 1 | 0 |
| 确认 5 笔（3 只基金） | 5 | 3 | 5 | 3 | 2 次 |
| 确认 20 笔（5 只基金） | 20 | 5 | 20 | 5 | **15 次** |
| 确认 50 笔（8 只基金） | 50 | 8 | 50 | 8 | **42 次** |

按 Supabase 单次 25~100ms 延迟估算：

| 场景 | 浪费查询 | 浪费延迟（下限） | 浪费延迟（上限） |
|------|---------|-------------|-------------|
| 5 笔/3 只基金 | 2 次 | 50ms | 200ms |
| 20 笔/5 只基金 | 15 次 | 375ms | **1.5s** |
| 50 笔/8 只基金 | 42 次 | 1.05s | **4.2s** |

## 额外开销：FundFeeService 反复实例化

每次循环还做了：
- `FundFeeService()` 构造 → `self._client = None`
- `svc.client` property → `get_supabase()` → 获取/创建 Supabase 客户端

虽然 `get_supabase()` 内部可能有单例/连接池，但每次都走一遍 property 查找和 import 路径，属于不必要的重复。

## 根因总结

| 层级 | 问题 | 严重度 |
|------|------|--------|
| **`confirm_pending_orders` 批量循环** | 每笔订单独立调用 `get_fee_rule`，无跨订单去重 | 🔴 高 — 延迟随订单数线性增长 |
| **`FundFeeService` 无实例级缓存** | 同一实例内对同一 `fund_code` 连续调用 `get_fee_rule` 也走远程 | 🟡 中 — 单请求内无缓存 |
| **`PortfolioService` 每次新建 `FundFeeService`** | `_calc_purchase_fee`/`_calc_redemption_fee`/`_get_fund_name` 各自实例化 | 🟢 低 — 仅多一次实例化开销，rule 透传已避免查询 |

## 优化方案

| 方案 | 改动量 | 效果 | 适用场景 |
|------|--------|------|---------|
| **A. 批量确认时按基金分组** | 小 | 50 笔→8 次查询 | 最直接，解决最大瓶颈 |
| **B. `FundFeeService` 加实例级 LRU 缓存** | 中 | 任意场景自动去重 | 通用，但需管理缓存失效 |
| **C. `confirm_pending_orders` 预加载** | 小 | 批量场景 1 次 `SELECT` 全部 | 最优，但需改 SQL |
| **D. `PortfolioService` 持有 `FundFeeService` 实例** | 小 | 消除重复实例化 | 辅助优化 |

**推荐 A+C 组合**：在 `confirm_pending_orders` 入口处，先收集所有 pending 订单涉及的 `fund_code`，一次 `SELECT * FROM fund_fee_rules WHERE fund_code IN (...)` 预加载到 dict，然后逐单确认时从 dict 取 rule 而非远程查询。N 笔 M 只基金的场景从 N 次远程查询降为 **1 次**。

## 相关文件

- `server/services/fund_fee_service.py` — `get_fee_rule()` 定义（L44）
- `server/services/portfolio_service.py` — `apply_purchase()`(L201)、`apply_redeem()`(L334)、`confirm_pending_orders()`(L583)、`_confirm_one_order()`(L652)
- `sql/fund_fee_rules_seed.sql` — 费率种子数据
