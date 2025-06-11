"""
LLMService 连通性测试脚本
"""

import asyncio
import sys
import os
from pprint import pprint

# 将项目根目录添加到Python路径中
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from llm_service import llm_service
from config import config

async def test_llm_service_connection():
    """
    测试 LLMService 的连通性。
    """
    print("--- 开始 LLMService 连通性测试 ---")

    # 检查 API 密钥是否已配置
    if not config.llm.api_key or "AIzaSy" not in config.llm.api_key:
        print("\n错误：Gemini API 密钥未在 config.py 中配置或无效。")
        print("请在 config.py 文件中设置 config.llm.api_key。")
        return

    print(f"使用的服务提供商: {config.llm.provider.value}")
    print(f"使用的模型: {config.llm.model_name}")
    if config.llm.use_proxy:
        print(f"使用代理: {config.llm.proxy_url}")
    else:
        print("不使用代理。")

    try:
        print("\n正在调用 llm_service._async_generate...")
        test_prompt = "Hello from LLMService. Please reply with 'Service OK' to confirm."
        
        # 调用服务的异步方法
        response_text = await llm_service._async_generate(test_prompt)

        print("\n--- LLMService 响应 ---")
        pprint(response_text)
        print("---------------------------")

        if response_text and "Service OK" in response_text:
            print(f"\n成功! 从 Gemini 收到的消息: '{response_text.strip()}'")
            print("\n结论: LLMService 服务网络畅通，工作正常！")
        elif response_text:
            print(f"\n警告: 收到了响应，但可能不是预期的结果: '{response_text.strip()}'")
        else:
            print("\n错误: 未能从 LLMService 收到有效的响应。")

    except Exception as e:
        print(f"\n--- 测试失败 ---")
        print(f"测试 LLMService 时发生错误: {e}")
        print("\n请检查日志以获取更多详细信息，并验证您在 config.py 中的配置。")
    finally:
        # 关闭服务的线程池以确保脚本干净地退出
        llm_service.close()
        print("\n--- 测试结束 ---")


if __name__ == "__main__":
    # 使用 asyncio.run 来执行异步的主函数
    asyncio.run(test_llm_service_connection())