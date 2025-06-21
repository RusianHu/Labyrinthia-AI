#!/usr/bin/env python3
"""
Ubuntu服务器Gemini API修复启用脚本
Enable Ubuntu server Gemini API fix script
"""

import os
import sys
import re
from pathlib import Path

def check_current_config():
    """检查当前配置"""
    print("=== 检查当前配置 ===")
    
    config_file = Path("config.py")
    if not config_file.exists():
        print("❌ 错误：找不到config.py文件")
        return False
    
    with open(config_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查是否已有内容清理配置
    if "use_content_sanitization" in content:
        # 检查当前设置
        sanitization_match = re.search(r'use_content_sanitization:\s*bool\s*=\s*(True|False)', content)
        if sanitization_match:
            current_setting = sanitization_match.group(1)
            print(f"✅ 找到内容清理配置：use_content_sanitization = {current_setting}")
            return current_setting == "True"
        else:
            print("⚠️  找到内容清理配置但无法解析设置")
            return False
    else:
        print("❌ 未找到内容清理配置")
        return False

def enable_content_sanitization():
    """启用内容清理功能"""
    print("\n=== 启用内容清理功能 ===")
    
    config_file = Path("config.py")
    with open(config_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 更新配置
    if "use_content_sanitization: bool = False" in content:
        content = content.replace(
            "use_content_sanitization: bool = False",
            "use_content_sanitization: bool = True"
        )
        print("✅ 已启用内容清理功能")
    elif "use_content_sanitization: bool = True" in content:
        print("✅ 内容清理功能已经启用")
        return True
    else:
        print("❌ 无法找到内容清理配置项")
        return False
    
    # 写回文件
    with open(config_file, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✅ 配置文件已更新")
    return True

def check_dependencies():
    """检查依赖文件"""
    print("\n=== 检查依赖文件 ===")
    
    required_files = [
        "content_sanitizer.py",
        "llm_service.py",
        "gemini_api.py"
    ]
    
    all_present = True
    for file_name in required_files:
        file_path = Path(file_name)
        if file_path.exists():
            print(f"✅ {file_name}")
        else:
            print(f"❌ {file_name} - 文件缺失")
            all_present = False
    
    return all_present

def test_sanitizer():
    """测试内容清理器"""
    print("\n=== 测试内容清理器 ===")

    try:
        from content_sanitizer import content_sanitizer

        # 测试基本功能
        test_text = "测试\t文本\x00包含\r\n问题字符"
        cleaned = content_sanitizer.sanitize_text(test_text)

        print(f"原文: {repr(test_text)}")
        print(f"清理后: {repr(cleaned)}")

        # 测试中文内容保留
        chinese_test = "任务：探索地下城"
        chinese_cleaned = content_sanitizer.sanitize_text(chinese_test)

        print(f"中文测试原文: {chinese_test}")
        print(f"中文测试清理后: {chinese_cleaned}")

        if len(cleaned) != len(test_text) and chinese_test == chinese_cleaned:
            print("✅ 内容清理器工作正常，中文内容保留完整")
            return True
        elif len(cleaned) != len(test_text):
            print("⚠️  内容清理器工作，但可能影响中文内容")
            return True
        else:
            print("⚠️  内容清理器可能未启用")
            return False

    except ImportError as e:
        print(f"❌ 无法导入内容清理器: {e}")
        return False
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False

def show_usage_instructions():
    """显示使用说明"""
    print("\n=== 使用说明 ===")
    print("1. 内容清理功能已启用，将自动处理以下问题：")
    print("   - Tab字符和其他控制字符")
    print("   - Markdown代码围栏")
    print("   - 复杂JSON结构")
    print("   - 支持Gemini API和OpenRouter API")
    print()
    print("2. 重启应用以使配置生效：")
    print("   python main.py")
    print()
    print("3. 监控日志以确认功能正常：")
    print("   - 查看 'Content sanitized' 日志信息")
    print("   - 确认复杂LLM请求不再超时")
    print("   - 确认中文任务内容显示正常")
    print()
    print("4. 如需调整清理强度，编辑config.py：")
    print("   - aggressive_sanitization = False (保守模式，推荐)")
    print("   - aggressive_sanitization = True (激进模式)")
    print()
    print("5. 如果任务内容显示异常：")
    print("   - 运行 'python test_chinese_content.py' 测试中文内容")
    print("   - 检查日志中的清理信息")
    print("   - 考虑临时禁用清理功能进行对比")

def main():
    """主函数"""
    print("Ubuntu服务器Gemini API修复启用脚本")
    print("=" * 50)
    
    # 检查当前配置
    is_enabled = check_current_config()
    
    # 检查依赖文件
    deps_ok = check_dependencies()
    if not deps_ok:
        print("\n❌ 依赖文件检查失败，请确保所有必要文件存在")
        return 1
    
    # 如果未启用，则启用
    if not is_enabled:
        success = enable_content_sanitization()
        if not success:
            print("\n❌ 启用内容清理功能失败")
            return 1
    
    # 测试功能
    test_ok = test_sanitizer()
    if not test_ok:
        print("\n⚠️  内容清理器测试未通过，但配置已更新")
    
    # 显示使用说明
    show_usage_instructions()
    
    print("\n✅ Ubuntu服务器Gemini API修复配置完成！")
    print("现在可以重启应用以使用修复功能。")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
