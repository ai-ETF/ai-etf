import os
os.environ['USE_MODELSCOPE'] = 'True'

try:
    from modelscope import snapshot_download
except ImportError:
    print("正在自动为你安装 modelscope...")
    os.system("pip install modelscope -i https://mirrors.aliyun.com/pypi/simple/")
    from modelscope import snapshot_download

print("开始从国内魔搭源 (ModelScope) 下载 MinerU 所需的视觉版面分析模型...")
print("文件较大（包含表格识别、公式识别等多个 AI 模型），请保持网络畅通，耐心等待。")

# PDF-Extract-Kit 包含了 MinerU 所有的核心 CV 权重模型
model_dir = snapshot_download('opendatalab/PDF-Extract-Kit')

print("=========================================")
print(f"✅ 模型已经全部成功下载！")
print(f"模型保存在这里: {model_dir}")
print("=========================================")