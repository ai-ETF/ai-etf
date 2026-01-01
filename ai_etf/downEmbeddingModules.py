from huggingface_hub import snapshot_download

# 模型仓库ID
model_id = "shibing624/text2vec-base-chinese"
# 指定下载到本地的目录，这里以项目根目录下的 'local_models' 文件夹为例
local_dir = "./local_models/text2vec-base-chinese"

snapshot_download(repo_id=model_id, local_dir=local_dir)
print(f"模型已下载到: {local_dir}")