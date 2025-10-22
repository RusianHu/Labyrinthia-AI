"""查找指定游戏ID的存档"""
import sys
sys.path.insert(0, '.')
from pathlib import Path
import json

# 查找这个游戏ID的存档
game_id = '15368e8a-26cf-4aa4-b917-507a9868cd47'
saves_dir = Path('saves/users')

print(f'🔍 搜索游戏ID: {game_id}')
print(f'📁 存档目录: {saves_dir}')
print()

found = False
user_id_found = None

if saves_dir.exists():
    for user_dir in saves_dir.iterdir():
        if user_dir.is_dir():
            save_file = user_dir / f'{game_id}.json'
            if save_file.exists():
                print(f'✅ 找到存档!')
                print(f'   用户ID: {user_dir.name}')
                print(f'   文件路径: {save_file}')
                
                # 读取存档信息
                with open(save_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                player = data.get('player', {})
                stats = player.get('stats', {})
                current_map = data.get('current_map', {})
                
                print(f'   玩家名称: {player.get("name", "未知")}')
                print(f'   玩家等级: {stats.get("level", "未知")}')
                print(f'   回合数: {data.get("turn_count", 0)}')
                print(f'   地图: {current_map.get("name", "未知")}')
                print(f'   地图深度: {current_map.get("depth", "未知")}')
                
                found = True
                user_id_found = user_dir.name
                break

if not found:
    print('❌ 未找到该存档')
    print('💡 提示: 请检查游戏ID是否正确')
else:
    print()
    print('📋 可以使用以下方式加载:')
    print(f'   1. URL: http://127.0.0.1:8001/?game_id={game_id}')
    print(f'   2. 控制台: await game.debugForceLoadGame("{game_id}")')
    print(f'   3. API: POST /api/debug/force-load')
    print(f'      Body: {{"game_id": "{game_id}"}}')

