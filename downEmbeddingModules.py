# downEmbeddingModules_fixed.py
import os
import sys
from huggingface_hub import snapshot_download

os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
model_id = "shibing624/text2vec-base-chinese"
local_dir = "./local_models/text2vec-base-chinese"

print(f"正在尝试通过镜像站下载: {model_id}")
try:
    snapshot_download(
        repo_id=model_id,
        local_dir=local_dir,
        local_dir_use_symlinks=False,
        resume_download=True,
        max_workers=2  # 网络不稳时可减少并发
    )
    print(f"✅ 模型成功下载至: {local_dir}")
except Exception as e:
    print(f"❌ 下载失败: {e}")
    print("\n网络不稳定，建议采用下方【手动下载方案】。")