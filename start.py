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
        'pydantic',
        'loguru'
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

        # 检查当前 Provider 的 API Key
        provider_name = config.llm.provider.value

        if not config.llm.api_key:
            print(f"⚠️  警告: 未设置 {provider_name.upper()} API 密钥")
            print(f"请在 .env 文件中设置对应的 API Key:")

            # 根据不同的 Provider 给出具体提示
            if provider_name == "gemini":
                print("   GEMINI_API_KEY=your_key_here")
            elif provider_name == "openrouter":
                print("   OPENROUTER_API_KEY=your_key_here")
            elif provider_name == "openai":
                print("   OPENAI_API_KEY=your_key_here")
            elif provider_name == "lmstudio":
                print("   LMSTUDIO_BASE_URL=http://localhost:1234/v1")

            print("或者在 config.py 中直接修改默认配置")
            return False

        print("✅ 配置检查通过")
        print(f"   LLM Provider: {provider_name}")
        print(f"   Model: {config.llm.model_name}")
        return True

    except Exception as e:
        print(f"❌ 配置检查失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def start_server():
    """启动服务器"""
    print("🚀 启动 Labyrinthia AI 服务器...")

    try:
        # 启动服务器 - 不重定向输出，让调试信息正常显示
        # 使用 None 作为 stdout 和 stderr，这样输出会直接显示在控制台
        process = subprocess.Popen([
            sys.executable, "main.py"
        ], stdout=None, stderr=None)

        # 等待服务器启动
        print("⏳ 等待服务器启动...")
        time.sleep(3)

        # 检查服务器是否启动成功
        if process.poll() is None:
            print("✅ 服务器启动成功!")
            print("🌐 游戏地址: http://127.0.0.1:8001")

            # 自动打开浏览器
            try:
                webbrowser.open("http://127.0.0.1:8001")
                print("🎮 浏览器已自动打开游戏页面")
            except Exception:
                print("⚠️  无法自动打开浏览器，请手动访问 http://127.0.0.1:8001")

            print("\n按 Ctrl+C 停止服务器")
            print("=" * 50)
            print()  # 空行，让服务器日志更清晰

            # 等待进程结束
            try:
                process.wait()
            except KeyboardInterrupt:
                print("\n" + "=" * 50)
                print("🛑 正在停止服务器...")
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    print("⚠️  服务器未响应，强制终止...")
                    process.kill()
                    process.wait()
                print("✅ 服务器已停止")
        else:
            # 服务器启动失败
            print("❌ 服务器启动失败")
            print("请检查端口 8001 是否被占用，或查看上方的错误信息")

    except Exception as e:
        print(f"❌ 启动服务器时发生错误: {e}")
        import traceback
        traceback.print_exc()


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
