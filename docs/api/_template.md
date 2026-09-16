# NN-模块名（新增接口模板）

> 新增接口文档时复制本文件。改文件名为 `NN-模块名.md`（如 `08-定投.md`）。
> 完成后：① 在 `README.md` 接口总览表加一行；② 运行 `python docs/api/scripts/gen_index.py` 校验。
> 约定：所有 curl 统一用 `$API` / `$TOKEN` / `$AUTH` 变量（定义见 `README.md`），一个接口只在文档里出现一次。

## 前置条件

```bash
# 需 JWT 的接口：先按 README.md 获取 $TOKEN 与 $AUTH
# 无需 JWT 的接口可跳过本步
```

## 接口速查

| 方法 | 路径 | 认证 |
|------|------|:---:|
| GET | `/api/example/{id}` | 🔒 |

## 接口 1：获取 XXX

**方法 / 路径：** `GET /api/example/{id}`（🔒 需 JWT）

**说明：** 一句话说明该接口的作用。

**curl 示例：**

```bash
curl -s "$API/api/example/123" \
  -H "$AUTH" | python3 -m json.tool
```

**参数：**

| 参数 | 位置 | 类型 | 必需 | 说明 |
|------|------|------|:---:|------|
| id | path | string | ✅ | 资源 ID |

**响应要点：** 返回字段及含义（如无特殊响应结构可省略）。

---

## 接口 2：创建 XXX

**方法 / 路径：** `POST /api/example`

**curl 示例：**

```bash
curl -s -X POST "$API/api/example" \
  -H "Content-Type: application/json" \
  -H "$AUTH" \
  -d '{"name": "xxx", "amount": 100}' | python3 -m json.tool
```

**请求体：**

| 字段 | 类型 | 必需 | 说明 |
|------|------|:---:|------|
| name | string | ✅ | 名称 |
| amount | number | ❌ | 金额（元） |

**错误场景：** 常见错误码 / 提示信息（可选）。
