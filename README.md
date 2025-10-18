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

### 1. 主要包 (ai_etf/)
这是项目的核心代码所在，开发者应在此目录下创建所有主要功能模块：

- **数据分析模块**: 实现ETF数据的获取、清洗和分析功能
- **机器学习模型**: 构建预测ETF趋势的AI模型
- **可视化组件**: 创建图表和报告展示分析结果
- **API接口**: 提供外部系统调用的接口

### 2. 测试目录 (tests/)
所有单元测试和集成测试应放在此目录中：

- **单元测试**: 针对单个函数或类的测试
- **集成测试**: 测试多个模块协同工作的功能
- **性能测试**: 测试系统的性能和响应时间

### 3. 配置文件
- **pyproject.toml**: 定义项目元数据和依赖关系
- **poetry.lock**: 锁定依赖的确切版本，确保构建一致性

## 开发环境搭建

### 前置要求
- Python 3.8 或更高版本
- Poetry 包管理工具

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

## 部署教程

### 本地运行

1. 确保已安装所有依赖：
   ```bash
   poetry install
   ```

2. 激活虚拟环境：
   ```bash
   poetry shell
   ```

3. 运行应用程序：
   ```bash
   python -m ai_etf
   ```

### 生产环境部署

1. 构建项目分发包：
   ```bash
   poetry build
   ```

2. 发布到PyPI（可选）：
   ```bash
   poetry publish
   ```

3. 在生产服务器上安装：
   ```bash
   pip install ai-etf
   ```

## 贡献指南

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情