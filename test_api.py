#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试AI-ETF项目的API端点
"""

import requests
import time
import subprocess
import signal
import os
import sys

def test_api_endpoints():
    """测试API端点"""
    # 启动服务器
    server_process = subprocess.Popen([
        "poetry", "run", "uvicorn", 
        "server.app:app", "--host", "0.0.0.0", "--port", "8002", "--log-level", "error"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, 
    cwd=os.path.dirname(__file__))
    
    # 等待服务器启动
    time.sleep(5)
    
    base_url = "http://localhost:8002"
    
    # 测试不同的端点
    endpoints = [
        "/",
        "/docs",
        "/api/test"
    ]
    
    print("Testing API endpoints...")
    for endpoint in endpoints:
        try:
            response = requests.get(f"{base_url}{endpoint}", timeout=10)
            print(f"Endpoint {endpoint}: Status {response.status_code}")
            if endpoint == "/api/test":
                print(f"Response content: {response.text[:200]}...")  # 只打印前200个字符
        except Exception as e:
            print(f"Failed to access {endpoint}: {e}")
    
    # 测试ask端点（需要POST请求）
    try:
        response = requests.post(f"{base_url}/api/ask", json={"query": "你好"}, timeout=10)
        print(f"Endpoint /api/ask: Status {response.status_code}")
        print(f"Response content: {response.text[:200]}...")
    except Exception as e:
        print(f"Failed to access /api/ask: {e}")
    
    # 终止服务器
    server_process.send_signal(signal.SIGTERM)
    server_process.wait()
    
    print("API testing completed.")

if __name__ == "__main__":
    test_api_endpoints()