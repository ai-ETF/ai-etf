# AI-ETF 项目

AI-ETF 是一个使用人工智能技术分析交易所交易基金(ETF)的项目。该项目旨在帮助投资者更好地理解和分析ETF市场趋势。

## 项目结构

```
ai-etf/
├── ai_etf/              # 主要的Python包
│   └── __init__.py      # 包初始化文件
├── tests/               # 测试文件目录
│   └── __init__.py      # 测试包初始化文件
├── pyproject.toml       # Poetry项目配置文件
├── poetry.lock          # Poetry依赖锁定文件
├── README.md            # 项目说明文档
└── .gitignore           # Git忽略文件配置
```

## 项目各部分说明

使用 python10最新版。

### 安装步骤

1. 克隆项目到本地：
   ```bash
   git clone <repository-url>
   cd ai-etf
   ```

2. 安装 Poetry（如果尚未安装）：
   ```bash
   curl -sSL https://install.python-poetry.org | python3 -
   ```

3. 安装项目依赖：
   ```bash
   poetry install
   ```

4. 激活虚拟环境：
   ```bash
   poetry shell
   ```

5. 运行测试（可选）：
   ```bash
   poetry run pytest
   ```

## 添加依赖

使用 Poetry 添加新依赖：

```bash
# 添加生产依赖
poetry add package-name

# 添加开发依赖
poetry add --group dev package-name
```
