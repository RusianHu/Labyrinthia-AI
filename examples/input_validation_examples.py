"""
Labyrinthia AI - 输入验证使用示例
Input Validation Usage Examples

展示如何在实际场景中使用输入验证器
"""

import sys
import os

# 添加父目录到路径以便导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from input_validator import input_validator


def example_1_basic_validation():
    """示例1: 基础验证"""
    print("\n" + "="*60)
    print("示例1: 基础玩家名称验证")
    print("="*60)
    
    # 正常输入
    name = "张三"
    result = input_validator.validate_player_name(name)
    
    if result.is_valid:
        print(f"✓ 名称 '{name}' 验证通过")
        print(f"  清理后的值: {result.sanitized_value}")
    else:
        print(f"✗ 名称 '{name}' 验证失败")
        print(f"  错误: {result.error_message}")


def example_2_handling_malicious_input():
    """示例2: 处理恶意输入"""
    print("\n" + "="*60)
    print("示例2: 处理恶意输入")
    print("="*60)
    
    malicious_inputs = [
        "<script>alert('xss')</script>",
        "'; DROP TABLE users--",
        "../../../etc/passwd",
        "test; rm -rf /"
    ]
    
    for malicious_input in malicious_inputs:
        result = input_validator.validate_player_name(malicious_input)
        print(f"\n输入: {malicious_input}")
        print(f"结果: {'✓ 通过' if result.is_valid else '✗ 拒绝'}")
        if not result.is_valid:
            print(f"原因: {result.error_message}")


def example_3_api_integration():
    """示例3: API集成模式"""
    print("\n" + "="*60)
    print("示例3: API集成模式")
    print("="*60)
    
    # 模拟API请求数据
    request_data = {
        "player_name": "测试玩家123",
        "character_class": "wizard"
    }
    
    print(f"请求数据: {request_data}")
    
    # 验证玩家名称
    name_result = input_validator.validate_player_name(request_data["player_name"])
    if not name_result.is_valid:
        print(f"✗ 验证失败: {name_result.error_message}")
        return
    
    # 验证职业
    class_result = input_validator.validate_character_class(request_data["character_class"])
    if not class_result.is_valid:
        print(f"⚠ 职业无效，使用默认值: {class_result.sanitized_value}")
    
    # 使用清理后的值
    print(f"\n✓ 验证通过，使用清理后的值:")
    print(f"  玩家名称: {name_result.sanitized_value}")
    print(f"  角色职业: {class_result.sanitized_value}")
    
    # 检查警告
    if name_result.warnings:
        print(f"\n⚠ 警告:")
        for warning in name_result.warnings:
            print(f"  - {warning}")


def example_4_save_data_validation():
    """示例4: 存档数据验证"""
    print("\n" + "="*60)
    print("示例4: 存档数据验证")
    print("="*60)
    
    # 正常存档
    valid_save = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "player": {
            "name": "勇者",
            "level": 10,
            "hp": 150
        },
        "current_map": {
            "name": "地下城第三层",
            "width": 20,
            "height": 20
        }
    }
    
    result = input_validator.validate_save_data(valid_save)
    
    if result.is_valid:
        print("✓ 存档数据验证通过")
        if result.warnings:
            print("\n⚠ 警告:")
            for warning in result.warnings:
                print(f"  - {warning}")
    else:
        print(f"✗ 存档数据验证失败: {result.error_message}")
    
    # 无效存档（缺少字段）
    print("\n测试无效存档（缺少current_map）:")
    invalid_save = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "player": {"name": "勇者"}
    }
    
    result = input_validator.validate_save_data(invalid_save)
    print(f"结果: {'✓ 通过' if result.is_valid else '✗ 拒绝'}")
    if not result.is_valid:
        print(f"原因: {result.error_message}")


def example_5_range_validation():
    """示例5: 范围验证"""
    print("\n" + "="*60)
    print("示例5: 整数范围验证")
    print("="*60)
    
    # 验证玩家等级
    test_levels = [1, 5, 10, 20, 25, -5, "abc"]
    
    for level in test_levels:
        result = input_validator.validate_integer_range(
            level, 
            min_value=1, 
            max_value=20, 
            field_name="玩家等级"
        )
        
        print(f"\n输入等级: {level}")
        print(f"结果: {'✓ 有效' if result.is_valid else '✗ 无效'}")
        print(f"清理后的值: {result.sanitized_value}")
        if not result.is_valid:
            print(f"错误: {result.error_message}")


def example_6_file_upload():
    """示例6: 文件上传验证"""
    print("\n" + "="*60)
    print("示例6: 文件上传验证")
    print("="*60)
    
    # 模拟文件上传
    test_files = [
        ("save.json", b'{"test": "data"}', "正常JSON文件"),
        ("save.txt", b'{"test": "data"}', "错误扩展名"),
        ("../../../etc/passwd.json", b'data', "路径遍历攻击"),
    ]
    
    for filename, content, description in test_files:
        print(f"\n测试: {description}")
        print(f"文件名: {filename}")
        
        result = input_validator.validate_file_upload(
            filename=filename,
            content=content,
            allowed_extensions=['json'],
            max_size_mb=10.0
        )
        
        print(f"结果: {'✓ 允许' if result.is_valid else '✗ 拒绝'}")
        if not result.is_valid:
            print(f"原因: {result.error_message}")


def example_7_sanitization():
    """示例7: 数据清理"""
    print("\n" + "="*60)
    print("示例7: HTML和Shell参数清理")
    print("="*60)
    
    # HTML清理
    print("\nHTML清理:")
    html_inputs = [
        "正常文本",
        "<script>alert('xss')</script>",
        "Test & <test> 'quote'"
    ]
    
    for text in html_inputs:
        sanitized = input_validator.sanitize_html(text)
        print(f"  原始: {text}")
        print(f"  清理: {sanitized}")
        print()
    
    # Shell参数清理
    print("Shell参数清理:")
    shell_inputs = [
        "test.txt",
        "test file.txt",
        "test; rm -rf /"
    ]
    
    for arg in shell_inputs:
        sanitized = input_validator.sanitize_shell_arg(arg)
        print(f"  原始: {arg}")
        print(f"  清理: {sanitized}")
        print()


def example_8_complete_workflow():
    """示例8: 完整工作流"""
    print("\n" + "="*60)
    print("示例8: 完整的用户注册工作流")
    print("="*60)
    
    # 模拟用户注册数据
    user_data = {
        "player_name": "新玩家2024",
        "character_class": "WIZARD",
        "email": "player@example.com"  # 假设的额外字段
    }
    
    print(f"用户提交的数据: {user_data}")
    print("\n开始验证流程...")
    
    errors = []
    warnings = []
    sanitized_data = {}
    
    # 1. 验证玩家名称
    print("\n1. 验证玩家名称...")
    name_result = input_validator.validate_player_name(user_data["player_name"])
    if name_result.is_valid:
        sanitized_data["player_name"] = name_result.sanitized_value
        print(f"   ✓ 通过: {name_result.sanitized_value}")
        if name_result.warnings:
            warnings.extend(name_result.warnings)
    else:
        errors.append(f"玩家名称: {name_result.error_message}")
        print(f"   ✗ 失败: {name_result.error_message}")
    
    # 2. 验证角色职业
    print("\n2. 验证角色职业...")
    class_result = input_validator.validate_character_class(user_data["character_class"])
    if class_result.is_valid:
        sanitized_data["character_class"] = class_result.sanitized_value
        print(f"   ✓ 通过: {class_result.sanitized_value}")
    else:
        # 职业验证失败时使用默认值
        sanitized_data["character_class"] = class_result.sanitized_value
        warnings.append(f"职业: {class_result.error_message}")
        print(f"   ⚠ 使用默认值: {class_result.sanitized_value}")
    
    # 3. 其他字段验证（示例）
    print("\n3. 验证其他字段...")
    sanitized_data["email"] = user_data.get("email", "")
    print(f"   ✓ Email: {sanitized_data['email']}")
    
    # 4. 汇总结果
    print("\n" + "-"*60)
    print("验证结果汇总:")
    print("-"*60)
    
    if errors:
        print("\n✗ 验证失败，发现以下错误:")
        for error in errors:
            print(f"  - {error}")
        print("\n无法继续注册流程")
    else:
        print("\n✓ 验证通过！")
        print(f"\n清理后的数据:")
        for key, value in sanitized_data.items():
            print(f"  {key}: {value}")
        
        if warnings:
            print(f"\n⚠ 警告信息:")
            for warning in warnings:
                print(f"  - {warning}")
        
        print("\n可以继续注册流程")


def main():
    """运行所有示例"""
    print("\n" + "="*80)
    print("Labyrinthia AI - 输入验证使用示例")
    print("="*80)
    
    example_1_basic_validation()
    example_2_handling_malicious_input()
    example_3_api_integration()
    example_4_save_data_validation()
    example_5_range_validation()
    example_6_file_upload()
    example_7_sanitization()
    example_8_complete_workflow()
    
    print("\n" + "="*80)
    print("所有示例运行完成！")
    print("="*80)
    print("\n提示: 查看 SECURITY_INPUT_VALIDATION.md 了解更多详细信息")


if __name__ == "__main__":
    main()

