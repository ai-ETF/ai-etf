# 使用官方Python运行时作为基础镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libsqlite3-dev\
    && rm -rf /var/lib/apt/lists/*

# 安装Poetry
RUN pip install poetry

# 复制pyproject.toml和poetry.lock（如果存在）
COPY pyproject.toml poetry.lock ./

# 配置Poetry不使用虚拟环境
RUN poetry config virtualenvs.create false

# 安装依赖（仅生产环境依赖）
RUN poetry install --only main --no-interaction

# 复制项目文件
COPY . .

# 暴露端口
EXPOSE 8000

# 运行应用
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]