# Python 基础知识（给 C++ 开发者）

## 1. Python 从上到下逐行执行

C++ 是编译型语言，函数定义位置无关紧要，只要有前置声明即可。Python 是解释型语言，**文件本身就是入口，从第1行执行到最后一行**。

可以理解为：Python 文件本身就是 C++ `main()` 的函数体，语句顺序很重要。

```
# Python：app 在第76行创建，uvicorn.run(app) 必须在它之后
app = FastAPI(...)           # 第76行：先创建
uvicorn.run(app, ...)        # 第97行：后使用，顺序不能反
```

## 2. `if __name__ == "__main__"` 是什么

`__name__` 是 Python 内置变量，值取决于文件如何被运行：

| 场景 | `__name__` 的值 | 进不进 if 块 |
|---|---|---|
| 直接运行 `python server/app.py` | `"__main__"` | 进 |
| 被别人 import `from server.app import app` | `"server.app"` | 不进 |

等价于 C++ 的 `int main()`：**只有直接运行时才执行的入口代码**。

实际项目中的两种启动方式：

```bash
# 方式1：直接运行（触发 if 块，本地调试用）
python server/app.py

# 方式2：通过 uvicorn 命令（不触发 if 块，部署用）
uvicorn server.app:app --host 0.0.0.0 --port 8000
```

## 3. `@asynccontextmanager` 装饰器

来自 `contextlib` 标准库，把一个生成器函数变成异步上下文管理器。

核心机制是 `yield` 关键字：

```
yield 之前的代码 → 进入时执行（启动阶段）
yield            → 暂停，把控制权交给调用方（应用运行中）
yield 之后的代码 → 退出时执行（关闭阶段）
```

项目中的例子（`server/app.py`）：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # yield 之前：启动阶段
    supabase = get_supabase()      # 验证数据库连接
    if not supabase:
        raise RuntimeError("连接失败")

    yield                           # 应用在这里运行，处理请求

    # yield 之后：关闭阶段
    logger.info("应用关闭")
```

## 4. 项目入口文件结构

```
python server/app.py
  → 加载 .env 环境变量
  → 初始化日志
  → 导入 api_router（来自 server/api/__init__.py）
  → 定义 lifespan 函数
  → app = FastAPI(lifespan=lifespan)
  → app.include_router(api_router, prefix="/api")
  → if __name__ == "__main__": uvicorn.run(app)
```

### server/app.py — 应用入口

创建 FastAPI 实例、配置中间件、注册路由。

### server/api/\_\_init\_\_.py — 路由聚合器

把 chat、upload、test、ask 四个子模块的 router 聚合成一个统一的 router。app.py 只需一行 `app.include_router(api_router, prefix="/api")` 即可挂载所有接口。

### server/\_\_init\_\_.py — 包导出

把 `app` 暴露出去，供外部（如 uvicorn）直接 `from server import app` 使用。

### 请求流向

```
用户请求 → FastAPI (app.py)
  → /api/chat        → chat.py    → QA 服务 → LLM 回答
  → /api/ask         → ask.py     → （已废弃）
  → /api/upload      → upload.py  → 文档上传处理
  → /api/test/hello  → test.py    → 测试接口
```
