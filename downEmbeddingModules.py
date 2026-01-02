import os
import sys
import requests
from huggingface_hub import snapshot_download

# 1. 强制使用镜像站
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'

# 2. 按需设置代理（如果您的服务器需要通过特定代理访问外网）
# os.environ['HTTP_PROXY'] = 'http://你的代理IP:端口'
# os.environ['HTTPS_PROXY'] = 'http://你的代理IP:端口'

model_id = "shibing624/text2vec-base-chinese"
local_dir = "./local_models/text2vec-base-chinese"

print(f"正在通过镜像站下载: {model_id}")

try:
    # 3. 配置更灵活的重试和超时逻辑
    snapshot_download(
        repo_id=model_id,
        local_dir=local_dir,
        local_dir_use_symlinks=False,
        resume_download=True,
        max_workers=2,  # 如果网络不稳定，先减少并发数
        timeout=(30, 120)  # 分别设置连接超时和读取超时（秒）
    )
    print(f"✅ 模型成功下载至: {local_dir}")
    
except Exception as e:
    print(f"❌ 下载失败，错误详情: {e}")
    print("\n进入「手动下载」阶段...")
    
    # 4. 提供手动下载链接
    manual_url = f"https://hf-mirror.com/{model_id}/tree/main"
    print(f"请尝试通过浏览器或wget手动访问: {manual_url}")
    print("例如，尝试下载关键文件:")
    print(f"  wget {manual_url}/config.json")
    print(f"  wget {manual_url}/pytorch_model.bin")
    print(f"  wget {manual_url}/vocab.txt")
    print("下载后请将文件放入上述 local_dir 目录中。")
    sys.exit(1)