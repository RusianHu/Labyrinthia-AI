#!/usr/bin/env python3
"""
Labyrinthia AI - 代理连接测试
Proxy connection test for the Labyrinthia AI game
"""

import requests
import sys
import time
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from config import config


def test_direct_connection():
    """测试直接连接"""
    print("🔗 测试直接连接到Google API...")
    
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models"
        params = {"key": config.llm.api_key}
        
        start_time = time.time()
        response = requests.get(url, params=params, timeout=10)
        end_time = time.time()
        
        if response.status_code == 200:
            print(f"✅ 直接连接成功 (耗时: {end_time - start_time:.2f}秒)")
            return True
        else:
            print(f"❌ 直接连接失败: HTTP {response.status_code}")
            print(f"   响应: {response.text[:200]}")
            return False
            
    except requests.exceptions.Timeout:
        print("❌ 直接连接超时")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"❌ 直接连接错误: {e}")
        return False
    except Exception as e:
        print(f"❌ 直接连接异常: {e}")
        return False


def test_proxy_connection():
    """测试代理连接"""
    print(f"🔗 测试通过代理连接到Google API (代理: {config.llm.proxy_url})...")
    
    if not config.llm.use_proxy or not config.llm.proxy_url:
        print("⚠️  代理未启用或未配置")
        return False
    
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models"
        params = {"key": config.llm.api_key}
        proxies = {
            'http': config.llm.proxy_url,
            'https': config.llm.proxy_url
        }
        
        start_time = time.time()
        response = requests.get(url, params=params, proxies=proxies, timeout=15)
        end_time = time.time()
        
        if response.status_code == 200:
            print(f"✅ 代理连接成功 (耗时: {end_time - start_time:.2f}秒)")
            return True
        else:
            print(f"❌ 代理连接失败: HTTP {response.status_code}")
            print(f"   响应: {response.text[:200]}")
            return False
            
    except requests.exceptions.Timeout:
        print("❌ 代理连接超时")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"❌ 代理连接错误: {e}")
        return False
    except requests.exceptions.ProxyError as e:
        print(f"❌ 代理服务器错误: {e}")
        return False
    except Exception as e:
        print(f"❌ 代理连接异常: {e}")
        return False


def test_proxy_server():
    """测试代理服务器是否可用"""
    print(f"🔍 测试代理服务器可用性 ({config.llm.proxy_url})...")
    
    if not config.llm.proxy_url:
        print("⚠️  未配置代理URL")
        return False
    
    try:
        # 尝试通过代理访问一个简单的HTTP服务
        proxies = {
            'http': config.llm.proxy_url,
            'https': config.llm.proxy_url
        }
        
        # 测试访问httpbin.org
        response = requests.get(
            "http://httpbin.org/ip", 
            proxies=proxies, 
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ 代理服务器可用，出口IP: {data.get('origin', 'unknown')}")
            return True
        else:
            print(f"❌ 代理服务器响应异常: HTTP {response.status_code}")
            return False
            
    except requests.exceptions.ConnectionError as e:
        print(f"❌ 无法连接到代理服务器: {e}")
        return False
    except requests.exceptions.ProxyError as e:
        print(f"❌ 代理服务器错误: {e}")
        return False
    except Exception as e:
        print(f"❌ 代理测试异常: {e}")
        return False


def test_gemini_api_with_proxy():
    """使用代理测试Gemini API"""
    print("🤖 测试通过代理调用Gemini API...")
    
    try:
        from gemini_api import GeminiAPI
        
        # 准备代理配置
        proxies = {}
        if config.llm.use_proxy and config.llm.proxy_url:
            proxies = {
                'http': config.llm.proxy_url,
                'https': config.llm.proxy_url
            }
        
        # 创建API客户端
        client = GeminiAPI(
            api_key=config.llm.api_key,
            proxies=proxies
        )
        
        # 测试简单的文本生成
        response = client.single_turn(
            text="请回复'Hello from Labyrinthia AI!'",
            generation_config={"max_output_tokens": 50}
        )
        
        if response.get("candidates"):
            content = response["candidates"][0].get("content", {})
            parts = content.get("parts", [])
            if parts and parts[0].get("text"):
                text = parts[0]["text"]
                print(f"✅ Gemini API调用成功")
                print(f"   响应: {text[:100]}...")
                return True
        
        print("❌ Gemini API响应格式异常")
        return False
        
    except Exception as e:
        print(f"❌ Gemini API调用失败: {e}")
        return False


def show_config_info():
    """显示当前配置信息"""
    print("⚙️  当前配置信息:")
    print(f"   API密钥: {config.llm.api_key[:10]}...{config.llm.api_key[-4:] if len(config.llm.api_key) > 14 else '(太短)'}")
    print(f"   使用代理: {config.llm.use_proxy}")
    print(f"   代理地址: {config.llm.proxy_url}")
    print(f"   超时时间: {config.llm.timeout}秒")
    print()


def main():
    """主函数"""
    print("🏰 Labyrinthia AI - 代理连接测试")
    print("=" * 50)
    
    # 检查API密钥
    if not config.llm.api_key or config.llm.api_key == "your-api-key-here":
        print("❌ 请先在config.py中设置Gemini API密钥")
        sys.exit(1)
    
    # 显示配置信息
    show_config_info()
    
    # 运行测试
    tests = [
        ("代理服务器可用性", test_proxy_server),
        ("直接连接", test_direct_connection),
        ("代理连接", test_proxy_connection),
        ("Gemini API (代理)", test_gemini_api_with_proxy),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"📝 {test_name}测试:")
        try:
            if test_func():
                passed += 1
            print()
        except KeyboardInterrupt:
            print("\n🛑 测试被用户中断")
            sys.exit(1)
        except Exception as e:
            print(f"   测试异常: {e}")
            print()
    
    print("=" * 50)
    print(f"📊 测试结果: {passed}/{total} 通过")
    
    if passed == total:
        print("🎉 所有测试通过！代理配置正常")
    elif passed >= 2:
        print("⚠️  部分测试通过，建议检查网络配置")
    else:
        print("❌ 大部分测试失败，请检查代理设置和网络连接")
    
    # 给出建议
    print("\n💡 建议:")
    if config.llm.use_proxy:
        print("   - 确保代理服务器 (如V2Ray、Clash等) 正在运行")
        print("   - 检查代理地址和端口是否正确")
        print("   - 尝试在浏览器中测试代理是否能访问Google")
    else:
        print("   - 如果在中国大陆，建议启用代理: config.llm.use_proxy = True")
        print("   - 配置正确的代理地址: config.llm.proxy_url = 'http://127.0.0.1:10808'")


if __name__ == "__main__":
    main()
