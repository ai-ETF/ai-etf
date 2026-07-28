"""
可视化 LangGraph 图

用法：
    python -m server.scripts.visualize_graph                        # 输出 Mermaid 文本（默认莱拉图）
    python -m server.scripts.visualize_graph --png                  # 输出 PNG 图片
    python -m server.scripts.visualize_graph --graph qa             # 指定其他图
    python -m server.scripts.visualize_graph --graph qa --png       # 指定图 + 输出 PNG

支持的图名称：lyra, qa, document（可在 GRAPHS 中扩展）
"""
import argparse
import sys
import os

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Python < 3.12 兼容性修复：pydantic 要求使用 typing_extensions.TypedDict
import typing
import typing_extensions
typing.TypedDict = typing_extensions.TypedDict

from dotenv import load_dotenv
load_dotenv()

import importlib


# 注册所有可用的图，新增图时在这里加一行即可
GRAPHS = {
    "lyra":     "server.graphs.lyra.graph:build_lyra_graph",
    "qa":       "server.graphs.qa.graph:build_qa_graph",
    "document": "server.graphs.document.graph:build_document_graph",
}


def load_graph_builder(name: str):
    """
    根据 'module.path:function_name' 格式动态导入图的构建函数。
    """
    if name not in GRAPHS:
        print(f"未知图: {name}")
        print(f"可用图: {', '.join(GRAPHS.keys())}")
        sys.exit(1)

    module_path, func_name = GRAPHS[name].rsplit(":", 1)
    module = importlib.import_module(module_path)
    return getattr(module, func_name)


def print_mermaid(builder):
    """打印 Mermaid 格式的图结构"""
    graph = builder().compile()
    print(graph.get_graph().draw_mermaid())


def save_png(builder, path):
    """通过 Mermaid 官方 API 保存为 PNG 图片"""
    graph = builder().compile()
    graph.get_graph().draw_mermaid_png(output_file_path=path)
    print(f"PNG 已保存到: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="可视化 LangGraph 图")
    parser.add_argument("--graph", default="lyra", choices=GRAPHS.keys(),
                        help="要可视化的图名称（默认: lyra）")
    parser.add_argument("--png", action="store_true", help="导出为 PNG 图片")
    parser.add_argument("--output", default=None, help="PNG 输出路径（默认: <图名>_graph.png）")
    args = parser.parse_args()

    builder = load_graph_builder(args.graph)
    output = args.output or f"{args.graph}_graph.png"

    if args.png:
        save_png(builder, output)
    else:
        print_mermaid(builder)
