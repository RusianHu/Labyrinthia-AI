"""
Gemini API 连通性测试脚本
"""

import sys
import os
from pprint import pprint

# 将项目根目录添加到Python路径中，以便导入其他模块
# Add the project root to the Python path to allow importing other modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import config
from gemini_api import GeminiAPI

def test_gemini_connection():
    """
    测试与Gemini API的连接。
    """
    print("--- 开始 Gemini API 连通性测试 ---")

    # 1. 从配置加载LLM设置
    llm_config = config.llm
    api_key = llm_config.api_key
    
    if not api_key or "AIzaSy" not in api_key:
        print("\n错误：Gemini API 密钥未在 config.py 中配置或无效。")
        print("请在 config.py 文件中设置 config.llm.api_key。")
        return

    print(f"使用的模型: {llm_config.model_name}")
    print(f"使用的端点: {llm_config.gemini_endpoint}")
    
    # 2. 配置代理
    proxies = {}
    if llm_config.use_proxy and llm_config.proxy_url:
        proxies = {
            "http": llm_config.proxy_url,
            "https": llm_config.proxy_url,
        }
        print(f"使用代理: {llm_config.proxy_url}")
    else:
        print("不使用代理。")

    try:
        # 3. 初始化 GeminiAPI 客户端
        print("\n正在初始化 GeminiAPI 客户端...")
        client = GeminiAPI(
            api_key=api_key,
            endpoint=llm_config.gemini_endpoint,
            api_version=llm_config.gemini_api_version,
            default_timeout=llm_config.timeout,
            proxies=proxies,
        )

        # 4. 发送一个简单的测试请求
        test_prompt = "Hello, Gemini. Please respond with 'OK' if you can hear me."
        print(f"发送测试提示: '{test_prompt}'")
        
        response = client.single_turn(
            model=llm_config.model_name,
            text=test_prompt,
            generation_config={
                "temperature": 0.1, # 使用低温以获得可预测的响应
            }
        )

        # 5. 打印和验证响应
        print("\n--- API 响应 ---")
        pprint(response)
        print("--------------------")

        # 验证响应是否成功
        if response and response.get("candidates"):
            candidate = response["candidates"][0]
            if candidate.get("content", {}).get("parts", [{}])[0].get("text"):
                text_response = candidate["content"]["parts"][0]["text"]
                print(f"\n成功! 从 Gemini 收到的消息: '{text_response.strip()}'")
                print("\n结论: Gemini API 网络畅通，配置正确！")
            else:
                finish_reason = candidate.get("finishReason", "未知")
                print(f"\n警告: API 调用已完成，但未收到文本内容。结束原因: {finish_reason}")
        else:
            print("\n错误: API 响应格式无效或为空。")

    except Exception as e:
        print(f"\n--- 测试失败 ---")
        print(f"在与 Gemini API 通信时发生错误: {e}")
        print("\n请检查以下几点：")
        print("1. 您的网络连接是否正常。")
        print(f"2. 如果使用代理，请确保代理服务器 ({llm_config.proxy_url}) 正在运行且可访问。")
        print("3. 您的 Gemini API 密钥是否正确且已启用。")
        print("4. Google Cloud 项目的计费是否已启用。")
        print(f"5. 目标端点 ({llm_config.gemini_endpoint}) 是否正确。")

    finally:
        print("\n--- 测试结束 ---")

if __name__ == "__main__":
    test_gemini_connection()