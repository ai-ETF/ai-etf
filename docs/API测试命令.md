# API 测试命令（已迁移）

> ⚠️ 本文档内容已整合进 **`docs/api/`**，此处仅保留入口。请勿继续在此维护。

所有接口测试指令已按模块收编到：

- 入口与接口总览：[`docs/api/README.md`](api/README.md)
- 基础 & 认证：[`docs/api/01-基础与认证.md`](api/01-基础与认证.md)
- 对话 & 会话：[`docs/api/02-对话与会话.md`](api/02-对话与会话.md)
- 行情：[`docs/api/03-行情.md`](api/03-行情.md)
- 自选股：[`docs/api/04-自选股.md`](api/04-自选股.md)
- 组合交易：[`docs/api/05-组合交易.md`](api/05-组合交易.md)
- 风险测评：[`docs/api/06-风险测评.md`](api/06-风险测评.md)
- 文档上传：[`docs/api/07-文档上传.md`](api/07-文档上传.md)

新增 / 修改接口后，运行校验：

```bash
python docs/api/scripts/gen_index.py --url https://ai-etf.xyz
```
