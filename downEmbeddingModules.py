# downEmbeddingModules.py

import os
import shutil
import socket
import subprocess
import traceback

from huggingface_hub import (
    snapshot_download,
    HfApi,
)
from huggingface_hub import constants


# =====================================================
# 配置区
# =====================================================

MODEL_ID = "shibing624/text2vec-base-chinese"

LOCAL_DIR = "./local_models/text2vec-base-chinese"

HF_MIRROR = "https://hf-mirror.com"

# =====================================================
# 工具函数
# =====================================================


def print_line():
    print("-" * 70)


def run_cmd(cmd, timeout=20):
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        return (
            result.returncode == 0,
            result.stdout.strip(),
            result.stderr.strip()
        )

    except Exception as e:
        return False, "", str(e)


# =====================================================
# 网络诊断
# =====================================================

def check_network():

    print("\n================ 网络诊断 ================\n")

    checks = [
        ("curl -I https://hf-mirror.com",
         "curl -I https://hf-mirror.com"),

        ("curl -I https://huggingface.co",
         "curl -I https://huggingface.co"),
    ]

    for title, cmd in checks:

        print(f"[检查] {title}")

        ok, out, err = run_cmd(cmd)

        if ok:
            print("✅ 成功")
            print(out[:500])

        else:
            print("❌ 失败")
            print(err)

        print_line()


# =====================================================
# DNS检查
# =====================================================

def check_dns():

    print("\n================ DNS诊断 ================\n")

    try:

        result = socket.getaddrinfo(
            "hf-mirror.com",
            443
        )

        print("✅ hf-mirror.com DNS解析正常")

        for item in result[:3]:
            print(item[4])

    except Exception as e:

        print("❌ DNS异常")
        print(e)

    print_line()


# =====================================================
# HuggingFace检查
# =====================================================

def check_hf():

    print("\n================ HF诊断 ================\n")

    print("huggingface_hub实际ENDPOINT:")

    try:
        print(constants.ENDPOINT)
    except Exception as e:
        print(e)

    print_line()

    print("测试 model_info()")

    try:

        api = HfApi(
            endpoint=HF_MIRROR
        )

        info = api.model_info(MODEL_ID)

        print("✅ 模型存在")

        print("modelId:", info.id)

    except Exception as e:

        print("❌ model_info失败")

        print(e)

        raise

    print_line()


# =====================================================
# 磁盘检查
# =====================================================

def check_disk():

    print("\n================ 磁盘检查 ================\n")

    total, used, free = shutil.disk_usage("/")

    print(f"总空间 : {total // (1024**3)} GB")
    print(f"已使用 : {used // (1024**3)} GB")
    print(f"剩余空间 : {free // (1024**3)} GB")

    if free < 2 * 1024**3:
        print("⚠️ 剩余空间不足2GB")

    print_line()


# =====================================================
# 下载
# =====================================================

def download_model():

    print("\n================ 开始下载 ================\n")

    print("模型:")
    print(MODEL_ID)

    print("\n保存路径:")
    print(LOCAL_DIR)

    print("\n使用镜像:")
    print(HF_MIRROR)

    print_line()

    try:

        snapshot_download(
            repo_id=MODEL_ID,

            local_dir=LOCAL_DIR,

            endpoint=HF_MIRROR,

            local_dir_use_symlinks=False,

            resume_download=True,

            max_workers=2,
        )

        print("\n✅ 下载成功")

        print(LOCAL_DIR)

    except Exception as e:

        print("\n❌ 下载失败")

        print(e)

        print("\n详细异常:")

        traceback.print_exc()

        print("\n建议：")

        print("1. 再次验证镜像站")
        print("2. 检查磁盘空间")
        print("3. 检查代理")
        print("4. 浏览器打开：")
        print(
            f"{HF_MIRROR}/{MODEL_ID}"
        )


# =====================================================
# 主程序
# =====================================================

if __name__ == "__main__":

    print("\n")
    print("=" * 70)
    print(" HuggingFace模型下载器 ")
    print("=" * 70)

    check_network()

    check_dns()

    check_disk()

    check_hf()

    download_model()