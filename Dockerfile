# 使用官方Python运行时作为基础镜像
FROM python:3.10-slim

# Python
ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100

# Poetry
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_CACHE_DIR='/var/cache/pypoetry' \
    POETRY_HOME='/usr/local' \
    POETRY_VERSION=2.2.1

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
RUN curl -sSL https://install.python-poetry.org | python3 -

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 复制pyproject.toml和poetry.lock（如果存在）
COPY pyproject.toml poetry.lock ./

# 安装依赖（仅生产环境依赖）
# RUN poetry install --no-ansi --only=main --no-root = 不安装当前项目本身，只装依赖
RUN poetry install --no-ansi --only=main --no-root


# 复制项目文件
COPY . .

# 暴露端口
EXPOSE 8000

# 运行应用
CMD ["poetry", "run", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]