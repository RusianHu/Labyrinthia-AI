"""
Labyrinthia AI - 内容生成器
Content generator for the Labyrinthia AI game
"""

import random
import asyncio
import logging
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import asdict

from config import config
from data_models import (
    GameMap, MapTile, TerrainType, Character, Monster, Quest, Item,
    CharacterClass, CreatureType, DamageType
)
from llm_service import llm_service


logger = logging.getLogger(__name__)


class ContentGenerator:
    """内容生成器类"""
    
    def __init__(self):
        self.cache = {}  # 简单的内存缓存
    
    async def generate_dungeon_map(self, width: int = 20, height: int = 20, 
                                 depth: int = 1, theme: str = "classic") -> GameMap:
        """生成地下城地图"""
        game_map = GameMap()
        game_map.width = width
        game_map.height = height
        game_map.depth = depth
        
        # 使用LLM生成地图名称和描述
        map_prompt = f"""
        为一个{width}x{height}的地下城第{depth}层生成名称和描述。
        主题：{theme}
        
        请返回JSON格式：
        {{
            "name": "地图名称",
            "description": "地图描述"
        }}
        """
        
        try:
            map_info = await llm_service._async_generate_json(map_prompt)
            if map_info:
                game_map.name = map_info.get("name", f"地下城第{depth}层")
                game_map.description = map_info.get("description", "一个神秘的地下城层")
        except Exception as e:
            logger.error(f"Failed to generate map info: {e}")
            game_map.name = f"地下城第{depth}层"
            game_map.description = "一个神秘的地下城层"
        
        # 生成基础地图结构
        await self._generate_map_layout(game_map)
        
        return game_map
    
    async def _generate_map_layout(self, game_map: GameMap):
        """生成地图布局"""
        # 初始化所有瓦片为墙壁
        for x in range(game_map.width):
            for y in range(game_map.height):
                tile = MapTile(x=x, y=y, terrain=TerrainType.WALL)
                game_map.tiles[(x, y)] = tile
        
        # 生成房间和走廊
        rooms = self._generate_rooms(game_map.width, game_map.height)
        
        # 在地图上放置房间
        for room in rooms:
            self._carve_room(game_map, room)
        
        # 连接房间
        self._connect_rooms(game_map, rooms)
        
        # 放置特殊地形
        await self._place_special_terrain(game_map, rooms)

        # 生成地图事件
        await self._generate_map_events(game_map, rooms)
    
    def _generate_rooms(self, width: int, height: int) -> List[Dict[str, int]]:
        """生成房间列表"""
        rooms = []
        max_rooms = min(10, (width * height) // 50)
        
        for _ in range(max_rooms):
            room_width = random.randint(4, 8)
            room_height = random.randint(4, 8)
            x = random.randint(1, width - room_width - 1)
            y = random.randint(1, height - room_height - 1)
            
            new_room = {
                "x": x, "y": y, 
                "width": room_width, "height": room_height
            }
            
            # 检查是否与现有房间重叠
            if not any(self._rooms_overlap(new_room, existing) for existing in rooms):
                rooms.append(new_room)
        
        return rooms
    
    def _rooms_overlap(self, room1: Dict[str, int], room2: Dict[str, int]) -> bool:
        """检查两个房间是否重叠"""
        return (room1["x"] < room2["x"] + room2["width"] and
                room1["x"] + room1["width"] > room2["x"] and
                room1["y"] < room2["y"] + room2["height"] and
                room1["y"] + room1["height"] > room2["y"])
    
    def _carve_room(self, game_map: GameMap, room: Dict[str, int]):
        """在地图上雕刻房间"""
        for x in range(room["x"], room["x"] + room["width"]):
            for y in range(room["y"], room["y"] + room["height"]):
                if (x, y) in game_map.tiles:
                    game_map.tiles[(x, y)].terrain = TerrainType.FLOOR
    
    def _connect_rooms(self, game_map: GameMap, rooms: List[Dict[str, int]]):
        """连接房间"""
        for i in range(len(rooms) - 1):
            room1 = rooms[i]
            room2 = rooms[i + 1]
            
            # 获取房间中心点
            x1 = room1["x"] + room1["width"] // 2
            y1 = room1["y"] + room1["height"] // 2
            x2 = room2["x"] + room2["width"] // 2
            y2 = room2["y"] + room2["height"] // 2
            
            # 创建L形走廊
            self._carve_corridor(game_map, x1, y1, x2, y1)  # 水平
            self._carve_corridor(game_map, x2, y1, x2, y2)  # 垂直
    
    def _carve_corridor(self, game_map: GameMap, x1: int, y1: int, x2: int, y2: int):
        """雕刻走廊"""
        if x1 == x2:  # 垂直走廊
            for y in range(min(y1, y2), max(y1, y2) + 1):
                if (x1, y) in game_map.tiles:
                    game_map.tiles[(x1, y)].terrain = TerrainType.FLOOR
        else:  # 水平走廊
            for x in range(min(x1, x2), max(x1, x2) + 1):
                if (x, y1) in game_map.tiles:
                    game_map.tiles[(x, y1)].terrain = TerrainType.FLOOR
    
    async def _place_special_terrain(self, game_map: GameMap, rooms: List[Dict[str, int]]):
        """放置特殊地形"""
        if not rooms:
            return
        
        # 在第一个房间放置上楼梯
        first_room = rooms[0]
        stairs_x = first_room["x"] + first_room["width"] // 2
        stairs_y = first_room["y"] + first_room["height"] // 2
        if (stairs_x, stairs_y) in game_map.tiles:
            game_map.tiles[(stairs_x, stairs_y)].terrain = TerrainType.STAIRS_UP
        
        # 在最后一个房间放置下楼梯
        if len(rooms) > 1:
            last_room = rooms[-1]
            stairs_x = last_room["x"] + last_room["width"] // 2
            stairs_y = last_room["y"] + last_room["height"] // 2
            if (stairs_x, stairs_y) in game_map.tiles:
                game_map.tiles[(stairs_x, stairs_y)].terrain = TerrainType.STAIRS_DOWN
        
        # 随机放置门、陷阱和宝藏
        floor_tiles = [(x, y) for (x, y), tile in game_map.tiles.items() 
                      if tile.terrain == TerrainType.FLOOR]
        
        # 放置门
        for _ in range(min(3, len(floor_tiles) // 10)):
            if floor_tiles:
                x, y = random.choice(floor_tiles)
                game_map.tiles[(x, y)].terrain = TerrainType.DOOR
                floor_tiles.remove((x, y))
        
        # 放置陷阱
        for _ in range(min(2, len(floor_tiles) // 15)):
            if floor_tiles:
                x, y = random.choice(floor_tiles)
                game_map.tiles[(x, y)].terrain = TerrainType.TRAP
                floor_tiles.remove((x, y))
        
        # 放置宝藏
        for _ in range(min(3, len(floor_tiles) // 12)):
            if floor_tiles:
                x, y = random.choice(floor_tiles)
                game_map.tiles[(x, y)].terrain = TerrainType.TREASURE
                floor_tiles.remove((x, y))
    
    async def generate_encounter_monsters(self, player_level: int, 
                                        encounter_difficulty: str = "medium") -> List[Monster]:
        """生成遭遇怪物"""
        # 根据难度确定怪物数量和挑战等级
        difficulty_config = {
            "easy": {"count": (1, 2), "cr_modifier": 0.5},
            "medium": {"count": (1, 3), "cr_modifier": 1.0},
            "hard": {"count": (2, 4), "cr_modifier": 1.5},
            "deadly": {"count": (3, 6), "cr_modifier": 2.0}
        }
        
        config_data = difficulty_config.get(encounter_difficulty, difficulty_config["medium"])
        monster_count = random.randint(*config_data["count"])
        base_cr = max(0.25, player_level * config_data["cr_modifier"])
        
        monsters = []
        
        # 批量生成怪物
        tasks = []
        for i in range(monster_count):
            cr = base_cr + random.uniform(-0.5, 0.5)
            cr = max(0.25, cr)
            
            context = f"为等级{player_level}的玩家生成挑战等级{cr:.1f}的怪物，遭遇难度：{encounter_difficulty}"
            tasks.append(llm_service.generate_monster(cr, context))
        
        # 等待所有怪物生成完成
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Monster):
                monsters.append(result)
            elif isinstance(result, Exception):
                logger.error(f"Failed to generate monster: {result}")
        
        return monsters
    
    async def generate_random_items(self, count: int = 1, 
                                  item_level: int = 1) -> List[Item]:
        """生成随机物品"""
        items = []
        
        item_types = ["weapon", "armor", "consumable", "misc"]
        rarities = ["common", "uncommon", "rare", "epic", "legendary"]
        
        # 根据物品等级调整稀有度权重
        rarity_weights = [50, 30, 15, 4, 1]  # 基础权重
        if item_level > 5:
            rarity_weights = [30, 40, 20, 8, 2]
        if item_level > 10:
            rarity_weights = [20, 30, 30, 15, 5]
        
        for _ in range(count):
            item_type = random.choice(item_types)
            rarity = random.choices(rarities, weights=rarity_weights)[0]
            
            # 使用LLM生成物品
            prompt = f"""
            生成一个DnD风格的{item_type}物品，稀有度为{rarity}，适合等级{item_level}的角色。
            
            请返回JSON格式：
            {{
                "name": "物品名称",
                "description": "物品描述",
                "value": 物品价值（金币）,
                "weight": 物品重量,
                "properties": {{
                    "damage": "伤害（如果是武器）",
                    "armor_class": "护甲等级（如果是护甲）",
                    "effect": "特殊效果"
                }}
            }}
            """
            
            try:
                result = await llm_service._async_generate_json(prompt)
                if result:
                    item = Item()
                    item.name = result.get("name", f"神秘的{item_type}")
                    item.description = result.get("description", "一个神秘的物品")
                    item.item_type = item_type
                    item.value = result.get("value", 10)
                    item.weight = result.get("weight", 1.0)
                    item.rarity = rarity
                    item.properties = result.get("properties", {})
                    items.append(item)
            except Exception as e:
                logger.error(f"Failed to generate item: {e}")
                # 创建默认物品
                item = Item()
                item.name = f"神秘的{item_type}"
                item.description = "一个神秘的物品"
                item.item_type = item_type
                item.rarity = rarity
                items.append(item)
        
        return items
    
    async def generate_quest_chain(self, player_level: int,
                                 chain_length: int = 1) -> List[Quest]:
        """生成任务链（开发阶段简化）"""
        quests = []

        # 生成主线任务（开发阶段简化为单个任务）
        main_quest_prompt = f"""
        为等级{player_level}的玩家生成1个DnD风格的主线任务，适合在2层地下城中完成。

        请返回JSON格式：
        {{
            "quests": [
                {{
                    "title": "任务标题",
                    "description": "任务描述（简短，适合2层地下城）",
                    "objectives": ["探索第一层", "进入第二层", "完成最终目标"],
                    "experience_reward": 500,
                    "story_context": "故事背景描述",
                    "progress_percentage": 0
                }}
            ]
        }}

        开发阶段：任务应该在2个地图层内完成，目标简洁明确。
        """
        
        try:
            result = await llm_service._async_generate_json(main_quest_prompt)
            if result and "quests" in result:
                for i, quest_data in enumerate(result["quests"]):
                    quest = Quest()
                    quest.title = quest_data.get("title", f"任务 {i+1}")
                    quest.description = quest_data.get("description", "")
                    quest.objectives = quest_data.get("objectives", [])
                    quest.completed_objectives = [False] * len(quest.objectives)
                    quest.experience_reward = quest_data.get("experience_reward", 500)
                    quest.story_context = quest_data.get("story_context", "")
                    quest.progress_percentage = quest_data.get("progress_percentage", 0.0)

                    # 第一个任务设为激活状态
                    if i == 0:
                        quest.is_active = True

                    quests.append(quest)
        except Exception as e:
            logger.error(f"Failed to generate quest chain: {e}")
        
        return quests
    
    def get_spawn_positions(self, game_map: GameMap, count: int = 1) -> List[Tuple[int, int]]:
        """获取可生成位置"""
        floor_tiles = [(x, y) for (x, y), tile in game_map.tiles.items()
                      if tile.terrain == TerrainType.FLOOR and not tile.character_id]

        if len(floor_tiles) < count:
            return floor_tiles

        return random.sample(floor_tiles, count)

    async def _generate_map_events(self, game_map: GameMap, rooms: List[Dict[str, int]]):
        """为地图生成事件"""
        floor_tiles = [(x, y) for (x, y), tile in game_map.tiles.items()
                      if tile.terrain == TerrainType.FLOOR and not tile.character_id]

        if not floor_tiles:
            return

        # 计算事件数量（基于地图大小）
        total_tiles = len(floor_tiles)
        event_count = max(3, total_tiles // 20)  # 每20个地板瓦片至少1个事件

        # 随机选择事件位置
        event_positions = random.sample(floor_tiles, min(event_count, len(floor_tiles)))

        for x, y in event_positions:
            tile = game_map.get_tile(x, y)
            if tile:
                # 随机选择事件类型
                event_types = ["combat", "treasure", "story", "trap", "mystery"]
                event_type = random.choice(event_types)

                # 设置事件属性
                tile.has_event = True
                tile.event_type = event_type
                tile.is_event_hidden = random.choice([True, True, False])  # 2/3概率隐藏
                tile.event_triggered = False

                # 根据事件类型设置事件数据
                if event_type == "combat":
                    tile.event_data = {
                        "monster_count": random.randint(1, 3),
                        "difficulty": random.choice(["easy", "medium", "hard"])
                    }
                elif event_type == "treasure":
                    tile.event_data = {
                        "treasure_type": random.choice(["gold", "item", "magic_item"]),
                        "value": random.randint(50, 500)
                    }
                elif event_type == "story":
                    tile.event_data = {
                        "story_type": random.choice(["discovery", "memory", "vision", "encounter"])
                    }
                elif event_type == "trap":
                    tile.event_data = {
                        "trap_type": random.choice(["damage", "debuff", "teleport"]),
                        "damage": random.randint(10, 30)
                    }
                elif event_type == "mystery":
                    tile.event_data = {
                        "mystery_type": random.choice(["puzzle", "riddle", "choice"])
                    }


# 全局内容生成器实例
content_generator = ContentGenerator()

__all__ = ["ContentGenerator", "content_generator"]
