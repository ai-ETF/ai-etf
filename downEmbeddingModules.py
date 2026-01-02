# downEmbeddingModels.py - 增强版
import os
import sys
from huggingface_hub import snapshot_download

# 1. 优先使用镜像站
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')

# 2. 配置参数
model_id = "shibing624/text2vec-base-chinese"
local_dir = "./local_models/text2vec-base-chinese"

print("=" * 60)
print(f"开始下载模型: {model_id}")
print(f"使用镜像站: {os.environ.get('HF_ENDPOINT', '默认 (hf.co)')}")
print(f"目标目录: {local_dir}")
print("=" * 60)

try:
    # 3. 添加更多参数优化下载
    snapshot_download(
        repo_id=model_id,
        local_dir=local_dir,
        local_dir_use_symlinks=False,  # 不使用符号链接
        resume_download=True,          # 支持断点续传
        max_workers=4,                 # 并行下载线程数
    )
    
    print(f"✅ 模型已成功下载到: {local_dir}")
    
except Exception as e:
    print(f"❌ 下载失败: {e}")
    print("\n备选方案:")
    print("1. 检查网络连接: ping hf-mirror.com")
    print("2. 尝试手动设置代理:")
    print("   export HTTP_PROXY=http://your-proxy:port")
    print("   export HTTPS_PROXY=http://your-proxy:port")
    print("3. 或手动下载: https://hf-mirror.com/shibing624/text2vec-base-chinese")
    sys.exit(1)

# 4. 验证下载结果
print("\n下载内容概览:")
if os.path.exists(local_dir):
    import glob
    files = glob.glob(os.path.join(local_dir, "**"), recursive=True)
    print(f"找到 {len(files)} 个文件/目录")
    
    # 列出关键文件
    key_files = [f for f in files if os.path.isfile(f)]
    for f in key_files[:10]:  # 显示前10个文件
        size = os.path.getsize(f) / (1024*1024)  # MB
        print(f"  - {os.path.basename(f):<30} {size:.2f} MB")
    
    if len(key_files) > 10:
        print(f"  ... 还有 {len(key_files)-10} 个文件")
else:
    print("警告: 目标目录不存在，下载可能未完成")_dir=local_dir)
print(f"模型已下载到: {local_dir}")