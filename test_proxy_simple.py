#!/usr/bin/env python3
"""
Labyrinthia AI - 简化代理测试
Simple proxy test for the Labyrinthia AI game
"""

import requests
import sys
import time
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from config import config


def test_proxy_gemini():
    """测试通过代理连接Gemini API"""
    print(f"🤖 测试通过代理连接Gemini API...")
    print(f"   代理: {config.llm.proxy_url}")
    print(f"   API密钥: {config.llm.api_key[:10]}...{config.llm.api_key[-4:]}")
    
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models"
        params = {"key": config.llm.api_key}
        proxies = {
            'http': config.llm.proxy_url,
            'https': config.llm.proxy_url
        }
        
        print("   正在连接...")
        start_time = time.time()
        response = requests.get(url, params=params, proxies=proxies, timeout=15)
        end_time = time.time()
        
        if response.status_code == 200:
            data = response.json()
            models = data.get('models', [])
            print(f"✅ 连接成功！(耗时: {end_time - start_time:.2f}秒)")
            print(f"   可用模型数量: {len(models)}")
            if models:
                print(f"   示例模型: {models[0].get('name', 'unknown')}")
            return True
        else:
            print(f"❌ 连接失败: HTTP {response.status_code}")
            print(f"   响应: {response.text[:200]}")
            return False
            
    except requests.exceptions.Timeout:
        print("❌ 连接超时")
        return False
    except requests.exceptions.ProxyError as e:
        print(f"❌ 代理错误: {e}")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"❌ 连接错误: {e}")
        return False
    except Exception as e:
        print(f"❌ 其他错误: {e}")
        return False


def test_gemini_generate():
    """测试Gemini文本生成"""
    print("🎯 测试Gemini文本生成...")
    
    try:
        from gemini_api import GeminiAPI
        
        # 准备代理配置
        proxies = {
            'http': config.llm.proxy_url,
            'https': config.llm.proxy_url
        }
        
        # 创建API客户端
        client = GeminiAPI(
            api_key=config.llm.api_key,
            proxies=proxies
        )
        
        print("   正在生成文本...")
        start_time = time.time()
        response = client.single_turn(
            text="请简短回复：你好，我是Labyrinthia AI游戏！",
            generation_config={"max_output_tokens": 100}
        )
        end_time = time.time()
        
        if response.get("candidates"):
            candidate = response["candidates"][0]
            content = candidate.get("content", {})
            parts = content.get("parts", [])

            if parts and parts[0].get("text"):
                text = parts[0]["text"].strip()
                print(f"✅ 文本生成成功！(耗时: {end_time - start_time:.2f}秒)")
                print(f"   AI回复: {text}")
                return True
            else:
                # 检查是否因为MAX_TOKENS而被截断
                finish_reason = candidate.get("finishReason", "")
                if finish_reason == "MAX_TOKENS":
                    print("⚠️  文本生成被截断（达到最大token限制），但连接正常")
                    print(f"   完成原因: {finish_reason}")
                    print("✅ 代理和API连接正常工作！")
                    return True
                else:
                    print("❌ 文本生成失败：响应格式异常")
                    print(f"   完成原因: {finish_reason}")
                    print(f"   原始响应: {response}")
                    return False

        print("❌ 文本生成失败：无候选响应")
        print(f"   原始响应: {response}")
        return False
        
    except Exception as e:
        print(f"❌ 文本生成错误: {e}")
        return False


def main():
    """主函数"""
    print("🏰 Labyrinthia AI - 简化代理测试")
    print("=" * 50)
    
    # 检查配置
    if not config.llm.api_key or config.llm.api_key == "your-api-key-here":
        print("❌ 请先设置Gemini API密钥")
        sys.exit(1)
    
    if not config.llm.use_proxy or not config.llm.proxy_url:
        print("❌ 请启用并配置代理")
        sys.exit(1)
    
    # 运行测试
    tests = [
        test_proxy_gemini,
        test_gemini_generate
    ]
    
    passed = 0
    for test_func in tests:
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
    if passed == len(tests):
        print("🎉 所有测试通过！代理配置正常，可以开始游戏了！")
    else:
        print("⚠️  部分测试失败，请检查代理配置")


if __name__ == "__main__":
    main()
