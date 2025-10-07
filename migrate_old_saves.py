"""
迁移旧存档到新的用户目录结构
Migrate old save files to new user directory structure
"""

import os
import json
import shutil
import uuid
from pathlib import Path
from datetime import datetime


def migrate_old_saves():
    """将旧的存档文件迁移到新的用户目录结构"""
    
    saves_dir = Path("saves")
    users_dir = saves_dir / "users"
    
    # 确保用户目录存在
    users_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建一个默认用户ID用于迁移旧存档
    default_user_id = "00000000-0000-0000-0000-000000000000"
    default_user_dir = users_dir / default_user_id
    default_user_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 60)
    print("迁移旧存档到新的用户目录结构")
    print("=" * 60)
    
    # 查找所有旧的存档文件（在saves根目录下的.json文件）
    old_saves = list(saves_dir.glob("*.json"))
    
    if not old_saves:
        print("\n✓ 没有发现需要迁移的旧存档")
        return
    
    print(f"\n发现 {len(old_saves)} 个旧存档文件")
    
    migrated_count = 0
    failed_count = 0
    
    for old_save_path in old_saves:
        try:
            print(f"\n处理: {old_save_path.name}")
            
            # 读取存档数据
            with open(old_save_path, 'r', encoding='utf-8') as f:
                save_data = json.load(f)
            
            # 获取存档信息
            player_name = save_data.get("player", {}).get("name", "Unknown")
            save_id = save_data.get("id", old_save_path.stem)
            
            print(f"  角色: {player_name}")
            print(f"  存档ID: {save_id}")
            
            # 新的存档路径
            new_save_path = default_user_dir / f"{save_id}.json"
            
            # 复制文件到新位置
            shutil.copy2(old_save_path, new_save_path)
            print(f"  ✓ 已复制到: {new_save_path}")
            
            # 备份原文件（重命名为.old）
            backup_path = old_save_path.with_suffix('.json.old')
            old_save_path.rename(backup_path)
            print(f"  ✓ 原文件已备份为: {backup_path.name}")
            
            migrated_count += 1
            
        except Exception as e:
            print(f"  ✗ 迁移失败: {e}")
            failed_count += 1
    
    # 创建用户元数据
    metadata_path = default_user_dir / "user_metadata.json"
    metadata = {
        "user_id": default_user_id,
        "created_at": datetime.now().isoformat(),
        "last_access": datetime.now().isoformat(),
        "note": "这是从旧版本迁移的默认用户，包含所有旧存档"
    }
    
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    print("\n" + "=" * 60)
    print("迁移完成！")
    print("=" * 60)
    print(f"成功迁移: {migrated_count} 个存档")
    print(f"失败: {failed_count} 个存档")
    print(f"\n默认用户ID: {default_user_id}")
    print(f"存档位置: {default_user_dir}")
    print("\n注意：")
    print("1. 旧存档文件已重命名为 .json.old 作为备份")
    print("2. 所有旧存档已迁移到默认用户目录")
    print("3. 您可以通过导出/导入功能将存档迁移到您的实际用户账户")
    print("=" * 60)


def create_user_cookie_helper():
    """创建一个帮助脚本，用于设置默认用户的Cookie"""
    
    helper_html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>设置默认用户Cookie</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 50px auto;
            padding: 20px;
            background: #f5f5f5;
        }
        .container {
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 {
            color: #5e35b1;
        }
        .info {
            background: #e3f2fd;
            padding: 15px;
            border-radius: 4px;
            margin: 20px 0;
        }
        button {
            background: #5e35b1;
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
        }
        button:hover {
            background: #7e57c2;
        }
        .success {
            background: #c8e6c9;
            padding: 15px;
            border-radius: 4px;
            margin: 20px 0;
            display: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔧 设置默认用户Cookie</h1>
        
        <div class="info">
            <p><strong>说明：</strong></p>
            <p>如果您想访问从旧版本迁移的存档，需要设置默认用户的Cookie。</p>
            <p>点击下面的按钮将自动设置Cookie，然后您就可以访问所有旧存档了。</p>
        </div>
        
        <button onclick="setDefaultUserCookie()">设置默认用户Cookie</button>
        
        <div id="success" class="success">
            <p><strong>✓ Cookie已设置成功！</strong></p>
            <p>现在您可以 <a href="/">返回游戏</a> 并访问旧存档了。</p>
        </div>
        
        <div class="info" style="margin-top: 30px;">
            <p><strong>提示：</strong></p>
            <ul>
                <li>设置Cookie后，您将能看到所有从旧版本迁移的存档</li>
                <li>您可以将这些存档导出，然后导入到您的实际用户账户</li>
                <li>如果您想使用新的用户账户，请清除浏览器Cookie</li>
            </ul>
        </div>
    </div>
    
    <script>
        function setDefaultUserCookie() {
            // 设置默认用户ID的Cookie
            const defaultUserId = '00000000-0000-0000-0000-000000000000';
            const expiryDate = new Date();
            expiryDate.setDate(expiryDate.getDate() + 30); // 30天后过期
            
            document.cookie = `labyrinthia_user_id=${defaultUserId}; expires=${expiryDate.toUTCString()}; path=/; SameSite=Lax`;
            
            // 显示成功消息
            document.getElementById('success').style.display = 'block';
        }
    </script>
</body>
</html>
"""
    
    helper_path = Path("static") / "set_default_user.html"
    with open(helper_path, 'w', encoding='utf-8') as f:
        f.write(helper_html)
    
    print(f"\n✓ 已创建Cookie设置帮助页面: {helper_path}")
    print(f"  访问 http://127.0.0.1:8001/static/set_default_user.html 来设置默认用户Cookie")


if __name__ == "__main__":
    try:
        # 迁移旧存档
        migrate_old_saves()
        
        # 创建Cookie设置帮助页面
        create_user_cookie_helper()
        
        print("\n✅ 迁移完成！")
        print("\n下一步：")
        print("1. 访问 http://127.0.0.1:8001/static/set_default_user.html")
        print("2. 点击按钮设置默认用户Cookie")
        print("3. 返回游戏主页，您将看到所有旧存档")
        print("4. 可以导出这些存档，然后导入到您的实际用户账户")
        
    except Exception as e:
        print(f"\n❌ 迁移失败: {e}")
        import traceback
        traceback.print_exc()

