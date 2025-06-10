#!/usr/bin/env python3
"""
Labyrinthia AI - 启动脚本
Simple startup script for the Labyrinthia AI game
"""

import os
import sys
import subprocess
import webbrowser
import time
from pathlib import Path


def check_dependencies():
    """检查依赖是否安装"""
    required_packages = [
        'fastapi',
        'uvicorn',
        'jinja2',
        'requests',
        'pydantic'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print("❌ 缺少以下依赖包:")
        for package in missing_packages:
            print(f"   - {package}")
        print("\n请运行以下命令安装依赖:")
        print("pip install -r requirements.txt")
        return False
    
    print("✅ 所有依赖已安装")
    return True


def check_config():
    """检查配置"""
    try:
        from config import config
        
        if not config.llm.api_key or config.llm.api_key == "your-api-key-here":
            print("⚠️  警告: 未设置Gemini API密钥")
            print("请在config.py中设置你的API密钥")
            print("或者设置环境变量 GEMINI_API_KEY")
            return False
        
        print("✅ 配置检查通过")
        return True
        
    except Exception as e:
        print(f"❌ 配置检查失败: {e}")
        return False


def start_server():
    """启动服务器"""
    print("🚀 启动 Labyrinthia AI 服务器...")
    
    try:
        # 启动服务器
        process = subprocess.Popen([
            sys.executable, "main.py"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        # 等待服务器启动
        print("⏳ 等待服务器启动...")
        time.sleep(3)
        
        # 检查服务器是否启动成功
        if process.poll() is None:
            print("✅ 服务器启动成功!")
            print("🌐 游戏地址: http://127.0.0.1:8000")
            
            # 自动打开浏览器
            try:
                webbrowser.open("http://127.0.0.1:8000")
                print("🎮 浏览器已自动打开游戏页面")
            except Exception:
                print("⚠️  无法自动打开浏览器，请手动访问 http://127.0.0.1:8000")
            
            print("\n按 Ctrl+C 停止服务器")
            
            # 等待进程结束
            try:
                process.wait()
            except KeyboardInterrupt:
                print("\n🛑 正在停止服务器...")
                process.terminate()
                process.wait()
                print("✅ 服务器已停止")
        else:
            # 服务器启动失败
            stdout, stderr = process.communicate()
            print("❌ 服务器启动失败:")
            if stderr:
                print(stderr)
            if stdout:
                print(stdout)
            
    except Exception as e:
        print(f"❌ 启动服务器时发生错误: {e}")


def main():
    """主函数"""
    print("🏰 Labyrinthia AI - DnD风格地牢冒险游戏")
    print("=" * 50)
    
    # 检查当前目录
    if not Path("main.py").exists():
        print("❌ 请在项目根目录下运行此脚本")
        sys.exit(1)
    
    # 检查依赖
    if not check_dependencies():
        sys.exit(1)
    
    # 检查配置
    if not check_config():
        response = input("\n是否继续启动? (y/N): ")
        if response.lower() not in ['y', 'yes']:
            sys.exit(1)
    
    # 启动服务器
    start_server()


if __name__ == "__main__":
    main()
