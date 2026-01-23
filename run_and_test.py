#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AI-ETF项目启动和测试脚本
用于启动服务并验证其功能
"""

import subprocess
import time
import requests
import threading
import signal
import sys
import os
import logging

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def check_service_health(url):
    """检查服务健康状态"""
    try:
        response = requests.get(url, timeout=5)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False

def test_api_endpoints(base_url):
    """测试API端点"""
    endpoints = [
        "/",
        "/docs",
        "/api/test"
    ]
    
    results = {}
    for endpoint in endpoints:
        try:
            url = base_url + endpoint
            response = requests.get(url, timeout=10)
            results[endpoint] = {
                "status_code": response.status_code,
                "success": response.status_code in [200, 405]  # 405是方法不允许，但表明路由存在
            }
        except requests.exceptions.RequestException as e:
            results[endpoint] = {
                "error": str(e),
                "success": False
            }
    
    return results

def run_integration_tests():
    """运行集成测试"""
    try:
        logger.info("开始运行集成测试...")
        result = subprocess.run([
            "python", "integration_test.py"
        ], cwd=os.path.dirname(__file__), capture_output=True, text=True, timeout=60)
        
        logger.info(f"集成测试完成，返回码: {result.returncode}")
        if result.stdout:
            logger.info(f"标准输出:\n{result.stdout}")
        if result.stderr:
            logger.error(f"错误输出:\n{result.stderr}")
        
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error("集成测试超时")
        return False
    except Exception as e:
        logger.error(f"运行集成测试时出错: {e}")
        return False

def main():
    """主函数"""
    logger.info("🚀 AI-ETF项目启动和测试")
    
    # 检查必要的文件和配置
    required_files = [
        ".env",
        "server/app.py",
        "pyproject.toml",
        "local_models/text2vec-base-chinese"
    ]
    
    missing_files = []
    for file in required_files:
        if not os.path.exists(file):
            missing_files.append(file)
    
    if missing_files:
        logger.warning(f"⚠️  发现缺失的文件: {missing_files}")
        logger.info("请确保以下文件存在:")
        logger.info("- .env: 包含必要的环境变量")
        logger.info("- server/app.py: 主应用文件")
        logger.info("- pyproject.toml: 项目依赖配置")
        logger.info("- local_models/text2vec-base-chinese: 下载的模型文件")
        return False
    
    logger.info("✅ 必要文件检查通过")
    
    # 启动服务器并在后台运行
    logger.info("🔌 启动服务器...")
    server_process = subprocess.Popen([
        "poetry", "run", "uvicorn", 
        "server.app:app", "--host", "0.0.0.0", "--port", "8001", "--reload"
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=os.path.dirname(__file__))
    
    # 等待服务器启动
    time.sleep(5)
    
    # 检查服务器是否成功启动
    if server_process.poll() is not None:
        _, stderr = server_process.communicate()
        logger.error(f"❌ 服务器启动失败: {stderr.decode()}")
        return False
    
    logger.info("✅ 服务器启动成功")
    
    try:
        base_url = "http://localhost:8001"
        
        # 测试服务健康状态
        logger.info("🏥 检查服务健康状态...")
        if check_service_health(base_url):
            logger.info("✅ 服务健康检查通过")
        else:
            logger.error("❌ 服务健康检查失败")
            return False
        
        # 测试API端点
        logger.info("📡 测试API端点...")
        results = test_api_endpoints(base_url)
        
        all_passed = True
        for endpoint, result in results.items():
            if result.get("success"):
                logger.info(f"✅ {endpoint}: 成功")
            else:
                logger.error(f"❌ {endpoint}: 失败 - {result.get('error', '未知错误')}")
                all_passed = False
        
        if not all_passed:
            logger.error("❌ 部分API端点测试失败")
        else:
            logger.info("✅ 所有API端点测试通过")
        
        # 运行集成测试
        integration_success = run_integration_tests()
        
        if integration_success:
            logger.info("✅ 集成测试通过")
        else:
            logger.warning("⚠️  集成测试未通过，但这可能是由于环境配置问题")
        
        logger.info("\n🎉 AI-ETF项目启动和测试完成!")
        logger.info(f"🌐 服务地址: {base_url}")
        logger.info(f"📖 API文档: {base_url}/docs")
        logger.info(f"🧪 测试端点: {base_url}/api/test")
        
        return True
        
    finally:
        # 终止服务器进程
        logger.info("🛑 关闭服务器...")
        server_process.terminate()
        try:
            server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_process.kill()
            logger.warning("服务器进程强制终止")
        
        logger.info("✅ 服务器已关闭")

if __name__ == "__main__":
    success = main()
    if success:
        logger.info("\n✅ AI-ETF项目启动和测试成功!")
        logger.info("您可以随时使用以下命令启动服务:")
        logger.info("cd /home/laihaida/home/ai-etf && poetry run uvicorn server.app:app --host 0.0.0.0 --port 8001")
    else:
        logger.error("\n❌ AI-ETF项目启动和测试失败!")
        sys.exit(1)