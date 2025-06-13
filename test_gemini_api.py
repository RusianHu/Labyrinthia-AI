"""
Gemini API 连通性测试脚本
"""

import sys
import os
from pprint import pprint
import base64
from pathlib import Path

# 将项目根目录添加到Python路径中，以便导入其他模块
# Add the project root to the Python path to allow importing other modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import config, LLMProvider
from gemini_api import GeminiAPI

# --- Test Helper Functions ---

def create_test_image(filename="test_image.png") -> Path:
    """创建一个简单的1x1像素的PNG图像用于测试"""
    path = Path(filename)
    if path.exists():
        return path
    
    # 1x1 transparent PNG
    png_data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    path.write_bytes(png_data)
    print(f"\n创建了测试图像: {path.absolute()}")
    return path

def print_test_header(name):
    print(f"\n--- 开始测试: {name} ---")

def print_test_footer(name, success):
    status = "成功" if success else "失败"
    print(f"--- 测试结束: {name} | 状态: {status} ---")

# --- Test Cases ---

def test_gemini_connection(client: GeminiAPI):
    """测试与Gemini API的基本连接。"""
    test_name = "Gemini API 连通性"
    print_test_header(test_name)
    success = False
    try:
        test_prompt = "Hello, Gemini. Please respond with 'OK' if you can hear me."
        print(f"发送测试提示: '{test_prompt}'")
        
        # 构建测试用的generation_config
        test_generation_config = {}
        if config.llm.use_generation_params:
            test_generation_config["temperature"] = 0.1  # 测试用低温度确保一致性

        response = client.single_turn(
            model=config.llm.model_name,
            text=test_prompt,
            generation_config=test_generation_config
        )

        print("\nAPI 响应:")
        pprint(response)

        if response and response.get("candidates"):
            candidate = response["candidates"][0]
            if candidate.get("content", {}).get("parts", [{}])[0].get("text"):
                text_response = candidate["content"]["parts"][0]["text"]
                print(f"\n从 Gemini 收到的消息: '{text_response.strip()}'")
                success = True
            else:
                finish_reason = candidate.get("finishReason", "未知")
                print(f"\n警告: API 调用已完成，但未收到文本内容。结束原因: {finish_reason}")
        else:
            print("\n错误: API 响应格式无效或为空。")
    except Exception as e:
        print(f"\n错误: {e}")
    
    print_test_footer(test_name, success)
    return success

def test_json_output(client: GeminiAPI):
    """测试强制JSON输出功能。"""
    test_name = "JSON 输出"
    print_test_header(test_name)
    success = False
    try:
        test_prompt = "Generate a JSON object with two keys: 'name' (string) and 'level' (integer)."
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "level": {"type": "integer"}
            },
            "required": ["name", "level"]
        }
        print(f"发送测试提示: '{test_prompt}'")
        
        response = client.single_turn_json(
            model=config.llm.model_name,
            text=test_prompt,
            schema=schema
        )

        print("\nAPI 响应:")
        pprint(response)

        if response and response.get("candidates"):
            text_response = response["candidates"][0]["content"]["parts"][0]["text"]
            print(f"\n收到的原始文本: {text_response}")
            import json
            try:
                data = json.loads(text_response)
                if isinstance(data, dict) and "name" in data and "level" in data:
                    print(f"成功解析JSON: {data}")
                    success = True
                else:
                    print("错误: 解析的JSON格式不正确。")
            except json.JSONDecodeError:
                print("错误: 未能将响应解析为JSON。")
        else:
            print("\n错误: API 响应格式无效或为空。")
    except Exception as e:
        print(f"\n错误: {e}")

    print_test_footer(test_name, success)
    return success

def test_chat_session(client: GeminiAPI):
    """测试多轮对话功能。"""
    test_name = "多轮对话 (ChatSession)"
    print_test_header(test_name)
    success = False
    try:
        print("启动新的聊天会话...")
        chat = client.start_chat(
            model=config.llm.model_name,
            system_prompt="You are a helpful assistant that remembers previous parts of the conversation."
        )
        
        # Turn 1
        print("\n第一轮对话:")
        prompt1 = "My name is Roo."
        print(f"  -> 用户: {prompt1}")
        response1 = chat.send(prompt1)
        text1 = response1["candidates"][0]["content"]["parts"][0]["text"].strip()
        print(f"  <- 模型: {text1}")

        # Turn 2
        print("\n第二轮对话:")
        prompt2 = "What is my name?"
        print(f"  -> 用户: {prompt2}")
        response2 = chat.send(prompt2)
        text2 = response2["candidates"][0]["content"]["parts"][0]["text"].strip()
        print(f"  <- 模型: {text2}")

        if "roo" in text2.lower():
            print("\n成功: 模型记住了之前的对话内容。")
            success = True
        else:
            print("\n错误: 模型未能记住之前的对话内容。")
            
        print("\n会话历史:")
        pprint(chat.history)

    except Exception as e:
        print(f"\n错误: {e}")

    print_test_footer(test_name, success)
    return success

def test_text_embedding(client: GeminiAPI):
    """测试文本嵌入功能。"""
    test_name = "文本嵌入 (Embedding)"
    print_test_header(test_name)
    success = False
    try:
        test_text = "This is a test for text embedding."
        print(f"要嵌入的文本: '{test_text}'")
        
        embedding = client.embed_text(text=test_text)
        
        if isinstance(embedding, list) and all(isinstance(x, float) for x in embedding):
            print(f"成功生成嵌入向量，维度: {len(embedding)}")
            print(f"向量预览: {embedding[:5]}...")
            success = True
        else:
            print("错误: 返回的嵌入不是浮点数列表。")
            pprint(embedding)

    except Exception as e:
        print(f"\n错误: {e}")

    print_test_footer(test_name, success)
    return success

def test_multimodal_input(client: GeminiAPI, image_path: Path):
    """测试多模态输入（文本+图像）。"""
    test_name = "多模态输入 (Vision)"
    print_test_header(test_name)
    success = False
    if not image_path.exists():
        print(f"警告: 找不到测试图像 {image_path}，跳过此测试。")
        print_test_footer(test_name, False)
        return False
        
    try:
        prompt = "What is in this image?"
        print(f"发送提示: '{prompt}' 和图像: '{image_path.name}'")
        
        response = client.multimodal_input(
            model=config.llm.model_name, # 使用支持视觉的模型
            text=prompt,
            image_path=str(image_path)
        )

        print("\nAPI 响应:")
        pprint(response)

        if response and response.get("candidates"):
            text_response = response["candidates"][0]["content"]["parts"][0]["text"]
            print(f"\n模型对图像的描述: '{text_response.strip()}'")
            # A simple check for a plausible description
            if text_response.strip():
                success = True
        else:
            print("\n错误: API 响应格式无效或为空。")
            
    except Exception as e:
        print(f"\n错误: {e}")

    print_test_footer(test_name, success)
    return success

def test_list_models(client: GeminiAPI):
    """测试列出可用模型的功能。"""
    test_name = "列出模型"
    print_test_header(test_name)
    success = False
    try:
        print("正在获取可用模型列表...")
        models_response = client.list_models()
        
        if models_response and "models" in models_response:
            print(f"成功获取 {len(models_response['models'])} 个模型。")
            # 查找我们正在使用的模型
            current_model_found = any(
                m["name"] == f"models/{config.llm.model_name}" for m in models_response["models"]
            )
            if current_model_found:
                print(f"当前配置的模型 'models/{config.llm.model_name}' 在列表中找到。")
                success = True
            else:
                print(f"警告: 当前配置的模型 'models/{config.llm.model_name}' 未在列表中找到。")
            
            # 打印一些模型名称
            print("\n部分可用模型:")
            for model in models_response["models"][:5]:
                print(f"- {model['name']} ({model.get('displayName', 'N/A')})")
        else:
            print("错误: 未能获取有效的模型列表。")
            pprint(models_response)

    except Exception as e:
        print(f"\n错误: {e}")

    print_test_footer(test_name, success)
    return success

def main():
    """运行所有Gemini API测试。"""
    print("--- 开始 Gemini API 功能测试套件 ---")

    # 1. 检查配置
    llm_config = config.llm
    
    # 检查当前提供商是否为Gemini
    if llm_config.provider != LLMProvider.GEMINI:
        print(f"\n信息: 当前配置的LLM提供商是 '{llm_config.provider.value}'，而不是 'gemini'。")
        print("将跳过 Gemini API 的特定测试。")
        print("\n--- 测试结束 ---")
        return

    api_key = llm_config.api_key
    if not api_key or "AIzaSy" not in api_key:
        print("\n错误：Gemini API 密钥未在 config.py 中配置或无效。")
        print("请在 config.py 文件中为Gemini提供商设置 config.llm.api_key。")
        return

    print(f"\n使用的模型: {llm_config.model_name}")
    print(f"使用的端点: {llm_config.gemini_endpoint}")
    
    # 2. 配置代理
    proxies = {}
    if llm_config.use_proxy and llm_config.proxy_url:
        proxies = {"http": llm_config.proxy_url, "https": llm_config.proxy_url}
        print(f"使用代理: {llm_config.proxy_url}")
    else:
        print("不使用代理。")

    # 3. 初始化客户端
    try:
        print("\n正在初始化 GeminiAPI 客户端...")
        client = GeminiAPI(
            api_key=api_key,
            endpoint=llm_config.gemini_endpoint,
            api_version=llm_config.gemini_api_version,
            default_timeout=llm_config.timeout,
            proxies=proxies,
        )
    except Exception as e:
        print(f"客户端初始化失败: {e}")
        return

    # 4. 创建测试资源
    test_image_path = create_test_image()

    # 5. 运行测试
    results = {
        "connection": test_gemini_connection(client),
        "json_output": test_json_output(client),
        "chat_session": test_chat_session(client),
        "embedding": test_text_embedding(client),
        "multimodal": test_multimodal_input(client, test_image_path),
        "list_models": test_list_models(client),
    }
    
    # 6. 清理测试资源
    if test_image_path.exists():
        test_image_path.unlink()
        print(f"\n删除了测试图像: {test_image_path.absolute()}")

    # 7. 总结
    print("\n--- 测试套件总结 ---")
    all_passed = True
    for test_name, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"- {test_name.replace('_', ' ').title()}: {status}")
        if not passed:
            all_passed = False
    
    print("\n--- 测试结束 ---")
    if not all_passed:
        print("\n部分测试失败，请检查上面的输出。")
        sys.exit(1)
    else:
        print("\n所有测试均已通过！")

if __name__ == "__main__":
    main()