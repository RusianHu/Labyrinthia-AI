"""
Labyrinthia AI - 内容生成器
Content generator for the Labyrinthia AI game
"""

import random
import asyncio
import logging
import uuid
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import asdict
from enum import Enum

from config import config
from data_models import (
    GameMap, MapTile, TerrainType, Character, Monster, Quest, Item,
    CharacterClass, CreatureType, DamageType
)
from llm_service import llm_service
from prompt_manager import prompt_manager
from async_task_manager import async_performance_monitor


logger = logging.getLogger(__name__)


class LLMInteractionType(Enum):
    """LLM交互类型"""
    MOVEMENT = "movement"
    COMBAT_ATTACK = "combat_attack"
    COMBAT_DEFENSE = "combat_defense"
    ITEM_USE = "item_use"
    EVENT_TRIGGER = "event_trigger"
    MAP_TRANSITION = "map_transition"
    QUEST_PROGRESS = "quest_progress"
    EXPLORATION = "exploration"


class GameContext:
    """游戏上下文信息类"""

    def __init__(self):
        self.recent_events: List[str] = []
        self.combat_events: List[str] = []
        self.movement_history: List[Tuple[int, int]] = []
        self.triggered_events: List[Dict[str, Any]] = []
        self.item_interactions: List[Dict[str, Any]] = []
        self.quest_updates: List[Dict[str, Any]] = []

    def add_event(self, event: str, event_type: str = "general"):
        """添加事件到上下文"""
        self.recent_events.append(f"[{event_type}] {event}")

        # 根据事件类型分类存储
        if event_type == "combat":
            self.combat_events.append(event)
        elif event_type == "item":
            self.item_interactions.append({"event": event, "timestamp": len(self.recent_events)})
        elif event_type == "quest":
            self.quest_updates.append({"event": event, "timestamp": len(self.recent_events)})

        # 保持事件列表不过长
        if len(self.recent_events) > 20:
            self.recent_events = self.recent_events[-15:]

    def add_movement(self, position: Tuple[int, int]):
        """添加移动历史"""
        self.movement_history.append(position)
        if len(self.movement_history) > 10:
            self.movement_history = self.movement_history[-8:]

    def get_context_summary(self) -> str:
        """获取上下文摘要"""
        summary_parts = []

        if self.recent_events:
            recent = self.recent_events[-5:]  # 最近5个事件
            summary_parts.append(f"最近事件: {'; '.join(recent)}")

        if self.combat_events:
            recent_combat = self.combat_events[-3:]  # 最近3个战斗事件
            summary_parts.append(f"战斗情况: {'; '.join(recent_combat)}")

        if self.movement_history:
            recent_moves = self.movement_history[-3:]  # 最近3次移动
            summary_parts.append(f"移动轨迹: {' -> '.join([f'({x},{y})' for x, y in recent_moves])}")

        return " | ".join(summary_parts) if summary_parts else "无特殊事件"

    def clear_old_events(self):
        """清理旧事件"""
        # 保留最近的重要事件
        self.recent_events = self.recent_events[-10:]
        self.combat_events = self.combat_events[-5:]
        self.movement_history = self.movement_history[-5:]


class ContentGenerator:
    """内容生成器类"""
    
    def __init__(self):
        self.cache = {}  # 简单的内存缓存
    
    @async_performance_monitor
    async def generate_dungeon_map(self, width: int = 20, height: int = 20,
                                 depth: int = 1, theme: str = "classic",
                                 quest_context: Optional[Dict[str, Any]] = None) -> GameMap:
        """生成地下城地图"""
        game_map = GameMap()
        game_map.width = width
        game_map.height = height
        game_map.depth = depth
        
        # 构建任务相关的提示信息
        quest_info = ""
        if quest_context:
            special_events = quest_context.get('special_events', [])
            special_monsters = quest_context.get('special_monsters', [])

            quest_info = f"""

        当前任务信息：
        - 任务类型：{quest_context.get('quest_type', 'exploration')}
        - 任务标题：{quest_context.get('title', '未知任务')}
        - 任务描述：{quest_context.get('description', '探索地下城')}
        - 目标楼层：{quest_context.get('target_floors', [depth])}
        - 建议主题：{quest_context.get('map_themes', [theme])}
        - 当前楼层：第{depth}层（共{config.game.max_quest_floors}层）
        - 专属事件：{len(special_events)}个
        - 专属怪物：{len(special_monsters)}个
        - 故事背景：{quest_context.get('story_context', '神秘的地下城探索')}

        楼层定位：
        {'- 这是起始层，应该相对安全，适合新手探索' if depth == 1 else ''}
        {'- 这是中间层，难度适中，包含重要的任务元素' if 1 < depth < config.game.max_quest_floors else ''}
        {'- 这是最终层，应该包含任务的高潮和结局' if depth == config.game.max_quest_floors else ''}

        请根据任务信息和楼层定位调整地图的名称和描述，使其与任务背景和当前进度相符。
        """

        # 使用PromptManager生成地图名称、描述和地板主题
        try:
            map_prompt = prompt_manager.format_prompt(
                "map_info_generation",
                width=width,
                height=height,
                depth=depth,
                theme=theme,
                quest_info=quest_info
            )

            map_info = await llm_service._async_generate_json(map_prompt)
            if map_info:
                game_map.name = map_info.get("name", f"地下城第{depth}层")
                game_map.description = map_info.get("description", "一个神秘的地下城层")
                # 获取地板主题，验证是否为有效值
                floor_theme = map_info.get("floor_theme", "normal")
                valid_themes = ["normal", "magic", "abandoned", "cave", "combat", "grassland", "desert", "farmland", "snowfield", "town"]
                if floor_theme in valid_themes:
                    game_map.floor_theme = floor_theme
                else:
                    logger.warning(f"Invalid floor_theme '{floor_theme}', using 'normal'")
                    game_map.floor_theme = "normal"
        except Exception as e:
            logger.error(f"Failed to generate map info: {e}")
            game_map.name = f"地下城第{depth}层"
            game_map.description = "一个神秘的地下城层"
            game_map.floor_theme = "normal"
        
        # 生成基础地图结构
        await self._generate_map_layout(game_map, quest_context)

        return game_map
    
    async def _generate_map_layout(self, game_map: GameMap, quest_context: Optional[Dict[str, Any]] = None):
        """生成地图布局"""
        # 初始化所有瓦片为墙壁
        for x in range(game_map.width):
            for y in range(game_map.height):
                tile = MapTile(x=x, y=y, terrain=TerrainType.WALL)
                game_map.tiles[(x, y)] = tile

        # 根据任务需求调整房间生成策略
        room_requirements = self._analyze_quest_requirements(quest_context, game_map.depth)

        # 生成房间和走廊
        rooms = self._generate_rooms_with_quest_context(
            game_map.width, game_map.height, room_requirements
        )

        # 在地图上放置房间
        for room in rooms:
            self._carve_room(game_map, room)

        # 连接房间（考虑任务路径需求）
        self._connect_rooms_strategically(game_map, rooms, room_requirements)

        # 验证和调整房间类型配置
        rooms = await self._validate_and_adjust_room_types(game_map, rooms, quest_context)

        # 放置特殊地形
        await self._place_special_terrain(game_map, rooms)

        # 生成地图事件
        await self._generate_map_events(game_map, rooms, quest_context)

    def _analyze_quest_requirements(self, quest_context: Optional[Dict[str, Any]], depth: int) -> Dict[str, Any]:
        """分析任务需求，确定地图生成策略"""
        requirements = {
            "min_rooms": 3,
            "max_rooms": 8,
            "needs_boss_room": False,
            "needs_treasure_room": False,
            "needs_special_rooms": 0,
            "quest_events_count": 0,
            "quest_monsters_count": 0,
            "layout_style": "standard"  # standard, linear, hub, maze
        }

        if not quest_context:
            return requirements

        # 分析任务类型
        quest_type = quest_context.get('quest_type', 'exploration')

        if quest_type == 'boss_fight':
            requirements["needs_boss_room"] = True
            requirements["layout_style"] = "linear"  # Boss任务使用线性布局
        elif quest_type == 'treasure_hunt':
            requirements["needs_treasure_room"] = True
            requirements["needs_special_rooms"] = 2
        elif quest_type == 'exploration':
            requirements["needs_special_rooms"] = 1
            requirements["layout_style"] = "hub"  # 探索任务使用中心辐射布局

        # 分析特殊事件和怪物
        special_events = quest_context.get('special_events', [])
        special_monsters = quest_context.get('special_monsters', [])

        # 筛选适合当前楼层的事件和怪物
        current_depth_events = [
            event for event in special_events
            if not event.get('location_hint') or str(depth) in event.get('location_hint', '')
        ]
        current_depth_monsters = [
            monster for monster in special_monsters
            if not monster.get('location_hint') or str(depth) in monster.get('location_hint', '')
        ]

        requirements["quest_events_count"] = len(current_depth_events)
        requirements["quest_monsters_count"] = len(current_depth_monsters)

        # 根据事件和怪物数量调整房间需求
        min_rooms_needed = max(3, requirements["quest_events_count"] + requirements["quest_monsters_count"])
        requirements["min_rooms"] = min(min_rooms_needed, 10)

        # 最终层特殊处理
        if depth == config.game.max_quest_floors:
            requirements["needs_boss_room"] = True
            requirements["layout_style"] = "linear"

        return requirements

    def _generate_rooms_with_quest_context(self, width: int, height: int,
                                         requirements: Dict[str, Any]) -> List[Dict[str, int]]:
        """根据任务需求生成房间"""
        rooms = []
        min_rooms = requirements["min_rooms"]
        max_rooms = requirements["max_rooms"]
        layout_style = requirements["layout_style"]

        # 确保地图足够大才生成房间
        if width < 6 or height < 6:
            room = {
                "x": 1, "y": 1,
                "width": width - 2, "height": height - 2,
                "type": "entrance"
            }
            rooms.append(room)
            return rooms

        max_possible_rooms = max(min_rooms, min(max_rooms, (width * height) // 40))
        target_rooms = random.randint(min_rooms, max_possible_rooms) if max_possible_rooms > min_rooms else min_rooms

        if layout_style == "linear":
            rooms = self._generate_linear_layout(width, height, target_rooms)
        elif layout_style == "hub":
            rooms = self._generate_hub_layout(width, height, target_rooms)
        else:  # standard
            rooms = self._generate_standard_layout(width, height, target_rooms)

        # 确保至少有一个房间
        if not rooms:
            room = {
                "x": 1, "y": 1,
                "width": min(4, width - 2), "height": min(4, height - 2),
                "type": "entrance"
            }
            rooms.append(room)

        return rooms

    def _generate_linear_layout(self, width: int, height: int, target_rooms: int) -> List[Dict[str, int]]:
        """生成线性布局（适合Boss战等）"""
        rooms = []
        room_width = max(3, (width - 2) // target_rooms)
        room_height = min(6, height - 2)

        for i in range(target_rooms):
            x = 1 + i * (room_width + 1)
            if x + room_width >= width:
                break

            room = {
                "x": x, "y": (height - room_height) // 2,
                "width": room_width, "height": room_height,
                "type": "boss" if i == target_rooms - 1 else ("entrance" if i == 0 else "normal"),
                "id": str(uuid.uuid4())
            }
            rooms.append(room)

        return rooms

    def _generate_hub_layout(self, width: int, height: int, target_rooms: int) -> List[Dict[str, int]]:
        """生成中心辐射布局（适合探索任务）"""
        rooms = []

        # 中心房间
        center_size = min(4, width // 3, height // 3)
        center_x = (width - center_size) // 2
        center_y = (height - center_size) // 2

        center_room = {
            "x": center_x, "y": center_y,
            "width": center_size, "height": center_size,
            "type": "entrance",
            "id": str(uuid.uuid4())
        }
        rooms.append(center_room)

        # 周围房间
        positions = [
            (1, 1), (width - 5, 1), (1, height - 5), (width - 5, height - 5),
            (center_x, 1), (center_x, height - 5), (1, center_y), (width - 5, center_y)
        ]

        for i, (x, y) in enumerate(positions[:target_rooms - 1]):
            if x + 4 < width and y + 4 < height:
                room = {
                    "x": x, "y": y,
                    "width": 4, "height": 4,
                    "type": "normal",
                    "id": str(uuid.uuid4())
                }
                rooms.append(room)

        return rooms

    def _generate_standard_layout(self, width: int, height: int, target_rooms: int) -> List[Dict[str, int]]:
        """生成标准随机布局"""
        return self._generate_rooms(width, height)  # 使用原有的随机生成逻辑

    def _connect_rooms_strategically(self, game_map: GameMap, rooms: List[Dict[str, int]],
                                   requirements: Dict[str, Any]):
        """策略性连接房间"""
        if not rooms:
            return

        layout_style = requirements["layout_style"]

        if layout_style == "linear":
            # 线性连接
            for i in range(len(rooms) - 1):
                self._connect_two_rooms(game_map, rooms[i], rooms[i + 1])
        elif layout_style == "hub":
            # 中心辐射连接
            if rooms:
                center_room = rooms[0]  # 第一个房间是中心
                for room in rooms[1:]:
                    self._connect_two_rooms(game_map, center_room, room)
        else:
            # 标准连接 - 确保所有房间都连接
            self._connect_all_rooms(game_map, rooms)

    def _connect_two_rooms(self, game_map: GameMap, room1: Dict[str, int], room2: Dict[str, int]):
        """连接两个特定房间"""
        # 获取房间最近的边界点
        connection_points = self._find_closest_connection_points(room1, room2)
        if not connection_points:
            return

        x1, y1, x2, y2 = connection_points

        # 创建L形走廊连接
        self._carve_corridor(game_map, x1, y1, x2, y1)  # 水平
        self._carve_corridor(game_map, x2, y1, x2, y2)  # 垂直

    def _connect_all_rooms(self, game_map: GameMap, rooms: List[Dict[str, int]]):
        """确保所有房间都连接 - 使用最小生成树算法"""
        if len(rooms) <= 1:
            return

        # 计算所有房间对之间的距离
        distances = []
        for i in range(len(rooms)):
            for j in range(i + 1, len(rooms)):
                dist = self._calculate_room_distance(rooms[i], rooms[j])
                distances.append((dist, i, j))

        # 按距离排序
        distances.sort()

        # 使用并查集实现最小生成树
        parent = list(range(len(rooms)))

        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py
                return True
            return False

        # 连接房间
        connected_edges = 0
        for dist, i, j in distances:
            if union(i, j):
                self._connect_two_rooms(game_map, rooms[i], rooms[j])
                connected_edges += 1
                if connected_edges >= len(rooms) - 1:
                    break

        # 添加一些额外的连接以增加路径选择
        extra_connections = min(2, len(distances) - connected_edges)
        for dist, i, j in distances[connected_edges:connected_edges + extra_connections]:
            if random.random() < 0.3:  # 30%概率添加额外连接
                self._connect_two_rooms(game_map, rooms[i], rooms[j])

    def _find_closest_connection_points(self, room1: Dict[str, int], room2: Dict[str, int]) -> tuple:
        """找到两个房间最近的连接点"""
        # 获取房间中心点
        center1_x = room1["x"] + room1["width"] // 2
        center1_y = room1["y"] + room1["height"] // 2
        center2_x = room2["x"] + room2["width"] // 2
        center2_y = room2["y"] + room2["height"] // 2

        # 确定连接方向
        if abs(center1_x - center2_x) > abs(center1_y - center2_y):
            # 水平连接优先
            if center1_x < center2_x:
                # room1在左，room2在右
                x1 = room1["x"] + room1["width"]
                y1 = center1_y
                x2 = room2["x"] - 1
                y2 = center2_y
            else:
                # room1在右，room2在左
                x1 = room1["x"] - 1
                y1 = center1_y
                x2 = room2["x"] + room2["width"]
                y2 = center2_y
        else:
            # 垂直连接优先
            if center1_y < center2_y:
                # room1在上，room2在下
                x1 = center1_x
                y1 = room1["y"] + room1["height"]
                x2 = center2_x
                y2 = room2["y"] - 1
            else:
                # room1在下，room2在上
                x1 = center1_x
                y1 = room1["y"] - 1
                x2 = center2_x
                y2 = room2["y"] + room2["height"]

        return (x1, y1, x2, y2)

    def _calculate_room_distance(self, room1: Dict[str, int], room2: Dict[str, int]) -> float:
        """计算两个房间中心点之间的距离"""
        center1_x = room1["x"] + room1["width"] // 2
        center1_y = room1["y"] + room1["height"] // 2
        center2_x = room2["x"] + room2["width"] // 2
        center2_y = room2["y"] + room2["height"] // 2

        return ((center1_x - center2_x) ** 2 + (center1_y - center2_y) ** 2) ** 0.5

    def _generate_rooms(self, width: int, height: int) -> List[Dict[str, int]]:
        """生成房间列表"""
        rooms = []

        # 确保地图足够大才生成房间
        if width < 6 or height < 6:
            # 对于小地图，创建一个简单的房间
            room = {
                "x": 1, "y": 1,
                "width": width - 2, "height": height - 2
            }
            rooms.append(room)
            return rooms

        max_rooms = min(10, max(1, (width * height) // 50))

        for _ in range(max_rooms):
            # 根据地图大小调整房间尺寸
            max_room_width = min(8, width - 3)
            max_room_height = min(8, height - 3)
            min_room_size = min(3, max_room_width - 1, max_room_height - 1)

            if min_room_size < 3:
                min_room_size = 3
                max_room_width = max(min_room_size, max_room_width)
                max_room_height = max(min_room_size, max_room_height)

            room_width = random.randint(min_room_size, max_room_width)
            room_height = random.randint(min_room_size, max_room_height)

            # 确保房间能放在地图内
            max_x = width - room_width - 1
            max_y = height - room_height - 1

            if max_x < 1 or max_y < 1:
                continue

            x = random.randint(1, max_x)
            y = random.randint(1, max_y)

            new_room = {
                "x": x, "y": y,
                "width": room_width, "height": room_height,
                "type": "normal"
            }

            # 检查是否与现有房间重叠
            if not any(self._rooms_overlap(new_room, existing) for existing in rooms):
                rooms.append(new_room)

        # 确保至少有一个房间
        if not rooms:
            room = {
                "x": 1, "y": 1,
                "width": min(4, width - 2), "height": min(4, height - 2),
                "type": "entrance"
            }
            rooms.append(room)

        return rooms
    
    def _rooms_overlap(self, room1: Dict[str, int], room2: Dict[str, int]) -> bool:
        """检查两个房间是否重叠"""
        return (room1["x"] < room2["x"] + room2["width"] and
                room1["x"] + room1["width"] > room2["x"] and
                room1["y"] < room2["y"] + room2["height"] and
                room1["y"] + room1["height"] > room2["y"])
    
    def _carve_room(self, game_map: GameMap, room: Dict[str, int]):
        """在地图上雕刻房间"""
        room_type = room.get("type", "normal")
        room_id = room.get("id", str(uuid.uuid4()))

        for x in range(room["x"], room["x"] + room["width"]):
            for y in range(room["y"], room["y"] + room["height"]):
                if (x, y) in game_map.tiles:
                    tile = game_map.tiles[(x, y)]
                    tile.terrain = TerrainType.FLOOR
                    tile.room_type = room_type
                    tile.room_id = room_id
    
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
                    tile = game_map.tiles[(x1, y)]
                    tile.terrain = TerrainType.FLOOR
                    if not tile.room_type:  # 只有未分配房间类型的瓦片才设为走廊
                        tile.room_type = "corridor"
        else:  # 水平走廊
            for x in range(min(x1, x2), max(x1, x2) + 1):
                if (x, y1) in game_map.tiles:
                    tile = game_map.tiles[(x, y1)]
                    tile.terrain = TerrainType.FLOOR
                    if not tile.room_type:  # 只有未分配房间类型的瓦片才设为走廊
                        tile.room_type = "corridor"
    
    async def _place_special_terrain(self, game_map: GameMap, rooms: List[Dict[str, int]]):
        """放置特殊地形"""
        if not rooms:
            return

        # 为房间分配类型
        room_types = self._assign_room_types(rooms, game_map.depth)

        # 更新地图瓦片的房间类型
        self._update_map_room_types(game_map, rooms, room_types)

        # 根据楼层深度智能放置楼梯
        current_depth = game_map.depth
        max_floors = config.game.max_quest_floors

        # 只有非第一层才放置上楼梯
        if current_depth > 1:
            first_room = rooms[0]
            stairs_x = first_room["x"] + first_room["width"] // 2
            stairs_y = first_room["y"] + first_room["height"] // 2
            if (stairs_x, stairs_y) in game_map.tiles:
                game_map.tiles[(stairs_x, stairs_y)].terrain = TerrainType.STAIRS_UP

        # 只有非最后一层才放置下楼梯
        if current_depth < max_floors and len(rooms) > 1:
            last_room = rooms[-1]
            stairs_x = last_room["x"] + last_room["width"] // 2
            stairs_y = last_room["y"] + last_room["height"] // 2
            if (stairs_x, stairs_y) in game_map.tiles:
                game_map.tiles[(stairs_x, stairs_y)].terrain = TerrainType.STAIRS_DOWN

        # 智能放置门
        self._place_doors_intelligently(game_map, rooms, room_types)

        # 智能放置其他特殊地形
        self._place_special_features(game_map, rooms, room_types)
        


    def _assign_room_types(self, rooms: List[Dict[str, int]], depth: int) -> List[str]:
        """为房间分配类型"""
        if not rooms:
            return []

        room_types = []

        for i, room in enumerate(rooms):
            # 检查房间是否已经有合适的类型
            existing_type = room.get("type", "normal")

            # 对于最终层，强制最后一个房间为Boss房间
            if depth == config.game.max_quest_floors and i == len(rooms) - 1:
                room_type = "boss"
            # 如果房间已经有非normal类型，保持不变
            elif existing_type != "normal":
                room_type = existing_type
            # 否则重新分配类型
            else:
                if i == 0:
                    room_type = "entrance"  # 第一个房间是入口
                elif i == len(rooms) - 1:
                    if depth == config.game.max_quest_floors:
                        room_type = "boss"  # 最终层的最后房间是Boss房
                    else:
                        room_type = "exit"  # 其他层的最后房间是出口房
                elif len(rooms) >= 4 and i == len(rooms) // 2:
                    room_type = "treasure"  # 中间房间作为宝库
                elif random.random() < 0.3:
                    room_type = "special"  # 30%概率为特殊房间
                else:
                    room_type = "normal"  # 普通房间

            room_types.append(room_type)
            # 更新房间字典中的类型
            room["type"] = room_type

        return room_types

    def _update_room_tiles_type(self, room: Dict[str, int], room_type: str):
        """更新房间内瓦片的类型（用于已有类型的房间）"""
        # 这个方法在房间雕刻时会被调用，这里只是占位符
        pass

    def _update_map_room_types(self, game_map: GameMap, rooms: List[Dict[str, int]], room_types: List[str]):
        """更新地图瓦片的房间类型"""
        for i, room in enumerate(rooms):
            if i < len(room_types):
                room_type = room_types[i]
                room_id = room.get("id")

                # 更新房间内所有瓦片的类型
                for x in range(room["x"], room["x"] + room["width"]):
                    for y in range(room["y"], room["y"] + room["height"]):
                        tile = game_map.get_tile(x, y)
                        if tile and tile.terrain == TerrainType.FLOOR:
                            # 只更新属于这个房间的瓦片
                            if tile.room_id == room_id or (
                                not tile.room_id and tile.room_type not in ["corridor"]
                            ):
                                tile.room_type = room_type
                                if room_id:
                                    tile.room_id = room_id

    def _place_doors_intelligently(self, game_map: GameMap, rooms: List[Dict[str, int]], room_types: List[str]):
        """智能放置门 - 改进版本，确保门的合理连接"""
        # 第一步：为每个重要房间找到最佳门位置
        door_placements = []

        for i, room in enumerate(rooms):
            room_type = room_types[i] if i < len(room_types) else "normal"

            # 确定房间是否需要门
            needs_door = self._room_needs_door(room_type)
            if not needs_door:
                continue

            # 找到该房间的最佳门位置
            best_door_positions = self._find_best_door_positions(game_map, room, room_type)

            if best_door_positions:
                # 选择最佳位置（优先选择连接质量最高的）
                best_position = best_door_positions[0]
                door_placements.append(best_position)

        # 第二步：验证门的放置并实际放置
        validated_doors = self._validate_and_place_doors(game_map, door_placements)

        # 第三步：为没有门的重要房间强制添加门
        self._ensure_critical_rooms_have_doors(game_map, rooms, room_types, validated_doors)

        logger.info(f"成功放置 {len(validated_doors)} 个门")

    def _room_needs_door(self, room_type: str) -> bool:
        """判断房间类型是否需要门"""
        # 重要房间必须有门
        if room_type in ["treasure", "boss", "special"]:
            return True
        # 普通房间70%概率有门（提高概率）
        elif room_type == "normal":
            return random.random() < 0.7
        # 入口房间30%概率有门（提高概率）
        elif room_type == "entrance":
            return random.random() < 0.3
        return False

    def _find_best_door_positions(self, game_map: GameMap, room: Dict[str, int], room_type: str) -> List[tuple]:
        """为房间找到最佳门位置"""
        candidates = []

        # 获取房间边界上的所有位置
        room_edges = self._get_room_edge_positions(room)

        for edge_x, edge_y in room_edges:
            # 检查边界位置外侧是否有走廊
            door_score = self._evaluate_door_position(game_map, edge_x, edge_y, room)
            if door_score > 0:
                candidates.append((edge_x, edge_y, room_type, door_score))

        # 按评分排序，返回最佳位置
        candidates.sort(key=lambda x: x[3], reverse=True)
        return candidates[:3]  # 返回最多3个最佳位置

    def _get_room_edge_positions(self, room: Dict[str, int]) -> List[tuple]:
        """获取房间边界位置（房间内侧边界）"""
        edges = []

        # 上边界（房间内第一行）
        for x in range(room["x"] + 1, room["x"] + room["width"] - 1):
            edges.append((x, room["y"]))

        # 下边界（房间内最后一行）
        for x in range(room["x"] + 1, room["x"] + room["width"] - 1):
            edges.append((x, room["y"] + room["height"] - 1))

        # 左边界（房间内第一列）
        for y in range(room["y"] + 1, room["y"] + room["height"] - 1):
            edges.append((room["x"], y))

        # 右边界（房间内最后一列）
        for y in range(room["y"] + 1, room["y"] + room["height"] - 1):
            edges.append((room["x"] + room["width"] - 1, y))

        return edges

    def _evaluate_door_position(self, game_map: GameMap, x: int, y: int, room: Dict[str, int]) -> float:
        """评估门位置的质量分数"""
        score = 0.0

        # 检查该位置是否是房间内的地板
        tile = game_map.get_tile(x, y)
        if not tile or tile.terrain != TerrainType.FLOOR:
            return 0.0

        # 检查四个方向，寻找走廊连接
        directions = [(0, 1), (0, -1), (1, 0), (-1, 0)]
        corridor_connections = 0
        room_connections = 0

        for dx, dy in directions:
            adj_x, adj_y = x + dx, y + dy
            adj_tile = game_map.get_tile(adj_x, adj_y)

            if adj_tile and adj_tile.terrain == TerrainType.FLOOR:
                if adj_tile.room_type == "corridor":
                    corridor_connections += 1
                    score += 10.0  # 连接走廊得高分
                elif adj_tile.room_type and adj_tile.room_type != "corridor":
                    # 检查是否连接到不同房间
                    if not self._is_point_in_room(adj_x, adj_y, room):
                        room_connections += 1
                        score += 5.0  # 连接其他房间得中等分

        # 必须至少有一个走廊连接才是有效门位置
        if corridor_connections == 0:
            return 0.0

        # 奖励有多个连接的位置（但不要太多）
        if corridor_connections == 1:
            score += 5.0  # 单一走廊连接是理想的
        elif corridor_connections == 2:
            score += 2.0  # 两个走廊连接可以接受
        else:
            score -= 5.0  # 太多连接可能是交叉路口，不适合放门

        return score

    def _validate_and_place_doors(self, game_map: GameMap, door_placements: List[tuple]) -> List[tuple]:
        """验证门的放置并实际放置门"""
        validated_doors = []

        for x, y, room_type, score in door_placements:
            # 最终验证门的连接质量
            if self._validate_door_connection(game_map, x, y):
                # 在房间边界外的走廊位置放置门
                door_position = self._find_corridor_position_for_door(game_map, x, y)
                if door_position:
                    door_x, door_y = door_position
                    tile = game_map.tiles.get((door_x, door_y))
                    if tile:
                        tile.terrain = TerrainType.DOOR
                        # 保持走廊类型标记
                        tile.room_type = "corridor"
                        validated_doors.append((door_x, door_y, room_type))
                        logger.debug(f"在位置 ({door_x}, {door_y}) 为 {room_type} 房间放置门")

        return validated_doors

    def _validate_door_connection(self, game_map: GameMap, x: int, y: int) -> bool:
        """验证门位置的连接是否合理"""
        directions = [(0, 1), (0, -1), (1, 0), (-1, 0)]
        corridor_count = 0
        room_count = 0

        for dx, dy in directions:
            adj_x, adj_y = x + dx, y + dy
            adj_tile = game_map.get_tile(adj_x, adj_y)

            if adj_tile and adj_tile.terrain == TerrainType.FLOOR:
                if adj_tile.room_type == "corridor":
                    corridor_count += 1
                elif adj_tile.room_type and adj_tile.room_type != "corridor":
                    room_count += 1

        # 门必须连接走廊和房间，或者连接两个不同区域
        return corridor_count >= 1 and (room_count >= 1 or corridor_count >= 1)

    def _find_corridor_position_for_door(self, game_map: GameMap, room_x: int, room_y: int) -> Optional[tuple]:
        """为房间位置找到相邻的走廊位置来放置门"""
        directions = [(0, 1), (0, -1), (1, 0), (-1, 0)]

        for dx, dy in directions:
            corridor_x, corridor_y = room_x + dx, room_y + dy
            corridor_tile = game_map.get_tile(corridor_x, corridor_y)

            if (corridor_tile and
                corridor_tile.terrain == TerrainType.FLOOR and
                corridor_tile.room_type == "corridor"):
                return (corridor_x, corridor_y)

        return None

    def _ensure_critical_rooms_have_doors(self, game_map: GameMap, rooms: List[Dict[str, int]],
                                        room_types: List[str], existing_doors: List[tuple]):
        """确保关键房间都有门"""
        critical_room_types = ["treasure", "boss", "special"]
        existing_door_rooms = set()

        # 记录已有门的房间
        for door_x, door_y, room_type in existing_doors:
            existing_door_rooms.add(room_type)

        # 为没有门的关键房间强制添加门
        for i, room in enumerate(rooms):
            room_type = room_types[i] if i < len(room_types) else "normal"

            if room_type in critical_room_types and room_type not in existing_door_rooms:
                # 强制为这个房间找一个门位置
                emergency_door = self._place_emergency_door(game_map, room, room_type)
                if emergency_door:
                    existing_doors.append(emergency_door)
                    logger.warning(f"为关键房间 {room_type} 强制添加紧急门")

    def _place_emergency_door(self, game_map: GameMap, room: Dict[str, int], room_type: str) -> Optional[tuple]:
        """为关键房间强制放置紧急门"""
        # 获取房间所有边界位置
        room_edges = self._get_room_edge_positions(room)

        for edge_x, edge_y in room_edges:
            # 寻找任何可能的走廊连接
            directions = [(0, 1), (0, -1), (1, 0), (-1, 0)]

            for dx, dy in directions:
                corridor_x, corridor_y = edge_x + dx, edge_y + dy
                corridor_tile = game_map.get_tile(corridor_x, corridor_y)

                if (corridor_tile and
                    corridor_tile.terrain == TerrainType.FLOOR and
                    corridor_tile.room_type == "corridor"):

                    # 在走廊位置放置门
                    corridor_tile.terrain = TerrainType.DOOR
                    corridor_tile.room_type = "corridor"
                    return (corridor_x, corridor_y, room_type)

        return None

    def _get_room_edges(self, room: Dict[str, int]) -> List[tuple]:
        """获取房间边界点"""
        edges = []

        # 上边界
        for x in range(room["x"], room["x"] + room["width"]):
            edges.append((x, room["y"]))

        # 下边界
        for x in range(room["x"], room["x"] + room["width"]):
            edges.append((x, room["y"] + room["height"] - 1))

        # 左边界
        for y in range(room["y"], room["y"] + room["height"]):
            edges.append((room["x"], y))

        # 右边界
        for y in range(room["y"], room["y"] + room["height"]):
            edges.append((room["x"] + room["width"] - 1, y))

        return edges

    def _is_room_entrance(self, game_map: GameMap, x: int, y: int, room: Dict[str, int]) -> bool:
        """检查位置是否是房间入口（连接到走廊）"""
        tile = game_map.get_tile(x, y)
        if not tile or tile.terrain != TerrainType.FLOOR:
            return False

        # 检查相邻位置是否有走廊
        directions = [(0, 1), (0, -1), (1, 0), (-1, 0)]
        has_corridor_connection = False

        for dx, dy in directions:
            adj_x, adj_y = x + dx, y + dy
            adj_tile = game_map.get_tile(adj_x, adj_y)

            if adj_tile and adj_tile.terrain == TerrainType.FLOOR:
                # 使用房间类型信息判断是否为走廊
                if adj_tile.room_type == "corridor":
                    has_corridor_connection = True
                    break
                # 或者检查是否在房间外（备用方法）
                elif not self._is_point_in_room(adj_x, adj_y, room):
                    has_corridor_connection = True
                    break

        return has_corridor_connection

    def _is_point_in_room(self, x: int, y: int, room: Dict[str, int]) -> bool:
        """检查点是否在房间内"""
        return (room["x"] <= x < room["x"] + room["width"] and
                room["y"] <= y < room["y"] + room["height"])

    def _place_special_features(self, game_map: GameMap, rooms: List[Dict[str, int]], room_types: List[str]):
        """智能放置特殊地形"""
        for i, room in enumerate(rooms):
            room_type = room_types[i] if i < len(room_types) else "normal"

            # 获取房间内的地板瓦片（排除门和楼梯）
            room_floor_tiles = self._get_room_floor_tiles(game_map, room)

            # 根据房间类型放置特殊地形
            if room_type == "treasure":
                self._place_treasure_room_features(game_map, room, room_floor_tiles)
            elif room_type == "boss":
                self._place_boss_room_features(game_map, room, room_floor_tiles)
            elif room_type == "special":
                self._place_special_room_features(game_map, room, room_floor_tiles)
            elif room_type == "normal":
                self._place_normal_room_features(game_map, room, room_floor_tiles)

        # 在走廊中放置一些陷阱
        self._place_corridor_traps(game_map, rooms)

    def _get_room_floor_tiles(self, game_map: GameMap, room: Dict[str, int]) -> List[tuple]:
        """获取房间内的可用地板瓦片"""
        room_floor_tiles = []
        for x in range(room["x"], room["x"] + room["width"]):
            for y in range(room["y"], room["y"] + room["height"]):
                tile = game_map.get_tile(x, y)
                if (tile and tile.terrain == TerrainType.FLOOR and
                    not tile.character_id):
                    room_floor_tiles.append((x, y))
        return room_floor_tiles

    def _place_treasure_room_features(self, game_map: GameMap, room: Dict[str, int], floor_tiles: List[tuple]):
        """在宝库房间放置特殊地形"""
        if not floor_tiles:
            return

        # 宝库房间：多个宝藏，可能有守护陷阱
        treasure_count = min(3, max(1, len(floor_tiles) // 4))

        # 优先在房间中心放置主要宝藏
        center_x = room["x"] + room["width"] // 2
        center_y = room["y"] + room["height"] // 2
        center_tiles = [(x, y) for x, y in floor_tiles
                       if abs(x - center_x) <= 1 and abs(y - center_y) <= 1]

        if center_tiles:
            x, y = random.choice(center_tiles)
            game_map.tiles[(x, y)].terrain = TerrainType.TREASURE
            floor_tiles.remove((x, y))
            treasure_count -= 1

        # 放置其他宝藏
        for _ in range(treasure_count):
            if floor_tiles:
                x, y = random.choice(floor_tiles)
                game_map.tiles[(x, y)].terrain = TerrainType.TREASURE
                floor_tiles.remove((x, y))

        # 30%概率在入口附近放置守护陷阱
        if random.random() < 0.3 and floor_tiles:
            entrance_tiles = self._get_room_entrance_tiles(room, floor_tiles)
            if entrance_tiles:
                x, y = random.choice(entrance_tiles)
                game_map.tiles[(x, y)].terrain = TerrainType.TRAP

    def _place_boss_room_features(self, game_map: GameMap, room: Dict[str, int], floor_tiles: List[tuple]):
        """在Boss房间放置特殊地形"""
        if not floor_tiles:
            return

        # Boss房间：可能有宝藏和战术陷阱
        if random.random() < 0.7 and floor_tiles:  # 70%概率有宝藏
            # 在房间后方放置宝藏
            back_tiles = [(x, y) for x, y in floor_tiles
                         if x >= room["x"] + room["width"] * 0.7]
            if back_tiles:
                x, y = random.choice(back_tiles)
                game_map.tiles[(x, y)].terrain = TerrainType.TREASURE
                floor_tiles.remove((x, y))

        # 40%概率放置战术陷阱
        if random.random() < 0.4 and len(floor_tiles) >= 2:
            trap_count = min(2, len(floor_tiles) // 6)
            for _ in range(trap_count):
                if floor_tiles:
                    x, y = random.choice(floor_tiles)
                    game_map.tiles[(x, y)].terrain = TerrainType.TRAP
                    floor_tiles.remove((x, y))

    def _place_special_room_features(self, game_map: GameMap, room: Dict[str, int], floor_tiles: List[tuple]):
        """在特殊房间放置特殊地形"""
        if not floor_tiles:
            return

        # 特殊房间：平衡的陷阱和宝藏
        feature_count = min(2, len(floor_tiles) // 3)

        for _ in range(feature_count):
            if not floor_tiles:
                break

            if random.random() < 0.6:  # 60%概率放置陷阱
                x, y = random.choice(floor_tiles)
                game_map.tiles[(x, y)].terrain = TerrainType.TRAP
            else:  # 40%概率放置宝藏
                x, y = random.choice(floor_tiles)
                game_map.tiles[(x, y)].terrain = TerrainType.TREASURE

            floor_tiles.remove((x, y))

    def _place_normal_room_features(self, game_map: GameMap, room: Dict[str, int], floor_tiles: List[tuple]):
        """在普通房间放置特殊地形"""
        if not floor_tiles:
            return

        # 普通房间：少量随机特殊地形
        if len(floor_tiles) >= 6 and random.random() < 0.25:  # 25%概率有特殊地形
            if random.random() < 0.7:  # 70%概率是陷阱
                x, y = random.choice(floor_tiles)
                game_map.tiles[(x, y)].terrain = TerrainType.TRAP
            else:  # 30%概率是宝藏
                x, y = random.choice(floor_tiles)
                game_map.tiles[(x, y)].terrain = TerrainType.TREASURE

    def _place_corridor_traps(self, game_map: GameMap, rooms: List[Dict[str, int]]):
        """在走廊中放置陷阱"""
        # 找到走廊瓦片（标记为corridor类型的地板）
        corridor_tiles = []
        for (x, y), tile in game_map.tiles.items():
            if (tile.terrain == TerrainType.FLOOR and
                tile.room_type == "corridor" and
                not tile.character_id):
                corridor_tiles.append((x, y))

        # 在走廊中放置少量陷阱
        if corridor_tiles:
            trap_count = min(3, max(1, len(corridor_tiles) // 10))  # 每10个走廊瓦片最多1个陷阱
            for _ in range(trap_count):
                if corridor_tiles:
                    x, y = random.choice(corridor_tiles)
                    game_map.tiles[(x, y)].terrain = TerrainType.TRAP
                    corridor_tiles.remove((x, y))

    def _get_room_entrance_tiles(self, room: Dict[str, int], floor_tiles: List[tuple]) -> List[tuple]:
        """获取房间入口附近的瓦片"""
        entrance_tiles = []
        # 房间前1/3区域被认为是入口区域
        entrance_boundary = room["x"] + room["width"] // 3

        for x, y in floor_tiles:
            if x <= entrance_boundary:
                entrance_tiles.append((x, y))

        return entrance_tiles

    @async_performance_monitor
    async def generate_encounter_monsters(self, player_level: int,
                                        encounter_difficulty: str = "medium",
                                        quest_context: Optional[Dict[str, Any]] = None) -> List[Monster]:
        """
        生成遭遇怪物（已重构为使用MonsterSpawnManager）

        Args:
            player_level: 玩家等级
            encounter_difficulty: 遭遇难度
            quest_context: 任务上下文（可选）

        Returns:
            生成的怪物列表
        """
        from monster_spawn_manager import monster_spawn_manager
        return await monster_spawn_manager.generate_encounter_monsters(
            player_level, encounter_difficulty, quest_context
        )
    
    @async_performance_monitor
    async def generate_random_items(self, count: int = 1,
                                  item_level: int = 1) -> List[Item]:
        """生成随机物品（使用并发生成提高效率）"""
        item_types = ["weapon", "armor", "consumable", "misc"]
        rarities = ["common", "uncommon", "rare", "epic", "legendary"]

        # 根据物品等级调整稀有度权重
        rarity_weights = [50, 30, 15, 4, 1]  # 基础权重
        if item_level > 5:
            rarity_weights = [30, 40, 20, 8, 2]
        if item_level > 10:
            rarity_weights = [20, 30, 30, 15, 5]

        # 准备所有物品的生成参数
        item_params = []
        for _ in range(count):
            item_type = random.choice(item_types)
            rarity = random.choices(rarities, weights=rarity_weights)[0]
            item_params.append((item_type, rarity))

        # 定义单个物品生成函数
        async def generate_single_item(item_type: str, rarity: str) -> Optional[Item]:
            """生成单个物品"""
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
                    return item
            except Exception as e:
                logger.error(f"Failed to generate item: {e}")
                # 创建默认物品
                item = Item()
                item.name = f"神秘的{item_type}"
                item.description = "一个神秘的物品"
                item.item_type = item_type
                item.rarity = rarity
                return item

        # 并发生成所有物品
        tasks = [generate_single_item(item_type, rarity) for item_type, rarity in item_params]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 收集成功生成的物品
        items = []
        for result in results:
            if isinstance(result, Item):
                items.append(result)
            elif isinstance(result, Exception):
                logger.error(f"Failed to generate item: {result}")

        return items

    async def generate_loot_items(self, player_level: int, rarity: str = "common",
                                item_types: Optional[List[str]] = None, count: int = 1) -> List[Item]:
        """生成战利品物品（使用并发生成提高效率）"""
        # 如果指定了物品类型，使用并发生成
        if item_types:
            # 准备生成任务
            tasks = []
            for _ in range(count):
                for item_type in item_types:
                    tasks.append(self.generate_random_items(1, player_level))
                    if len(tasks) >= count:
                        break
                if len(tasks) >= count:
                    break

            # 并发生成所有物品
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 收集成功生成的物品并设置类型和稀有度
            items = []
            type_index = 0
            for result in results:
                if isinstance(result, list) and result:
                    item = result[0]
                    item.item_type = item_types[type_index % len(item_types)]
                    item.rarity = rarity
                    items.append(item)
                    type_index += 1
                elif isinstance(result, Exception):
                    logger.error(f"Failed to generate loot item: {result}")

                if len(items) >= count:
                    break

            return items[:count]
        else:
            # 使用原有的generate_random_items方法（已经是并发的）
            items = await self.generate_random_items(count, player_level)
            # 设置稀有度
            for item in items:
                item.rarity = rarity
            return items

    async def generate_quest_chain(self, player_level: int,
                                 chain_length: int = 1) -> List[Quest]:
        """生成任务链（开发阶段简化）"""
        quests = []

        # 生成主线任务（开发阶段简化为单个任务）
        max_floors = config.game.max_quest_floors
        main_quest_prompt = f"""
        为等级{player_level}的玩家生成1个DnD风格的主线任务，适合在{max_floors}层地下城中完成。

        任务设计要求：
        1. 任务目标明确，有清晰的故事线
        2. 每层都有相应的子目标和挑战
        3. 专属事件和怪物要与任务主题紧密相关
        4. 进度分配合理，确保玩家能在{max_floors}层内完成任务

        请返回JSON格式：
        {{
            "quests": [
                {{
                    "title": "任务标题（中文，简洁有力）",
                    "description": "任务描述（详细说明任务背景和目标，适合{max_floors}层地下城）",
                    "objectives": ["第1层：初步探索和准备", "第2层：深入调查", "第{max_floors}层：完成最终目标"],
                    "experience_reward": {500 + player_level * 50},
                    "story_context": "详细的故事背景，包括任务起因、目标和意义",
                    "progress_percentage": 0,
                    "quest_type": "exploration",
                    "target_floors": {list(range(1, max_floors + 1))},
                    "map_themes": ["地下城", "古老遗迹", "神秘洞穴"],
                    "special_events": [
                        {{
                            "id": "event_1",
                            "event_type": "story",
                            "name": "关键线索发现",
                            "description": "发现与任务目标相关的重要线索或古老文献",
                            "trigger_condition": "探索特定区域",
                            "progress_value": 15.0,
                            "is_mandatory": true,
                            "location_hint": "第1层"
                        }},
                        {{
                            "id": "event_2",
                            "event_type": "mystery",
                            "name": "古老机关",
                            "description": "需要解开的古老机关或谜题，阻挡前进道路",
                            "trigger_condition": "接近关键区域",
                            "progress_value": 20.0,
                            "is_mandatory": true,
                            "location_hint": "第2层"
                        }},
                        {{
                            "id": "event_3",
                            "event_type": "combat",
                            "name": "最终对决",
                            "description": "与任务最终boss的决战",
                            "trigger_condition": "到达任务目标位置",
                            "progress_value": 35.0,
                            "is_mandatory": true,
                            "location_hint": "第{max_floors}层"
                        }}
                    ],
                    "special_monsters": [
                        {{
                            "id": "monster_1",
                            "name": "守护哨兵",
                            "description": "保护入口的古老守护者",
                            "challenge_rating": {player_level * 0.8},
                            "is_boss": false,
                            "progress_value": 10.0,
                            "spawn_condition": "进入特定区域时",
                            "location_hint": "第1层的关键通道"
                        }},
                        {{
                            "id": "monster_2",
                            "name": "任务终极Boss",
                            "description": "任务的最终敌人，拥有强大力量",
                            "challenge_rating": {player_level + 1.0},
                            "is_boss": true,
                            "progress_value": 30.0,
                            "spawn_condition": "玩家接近任务目标时",
                            "location_hint": "第{max_floors}层的核心区域"
                        }}
                    ]
                }}
            ]
        }}

        重要提示：
        - 确保任务内容丰富但不过于复杂
        - 专属事件和怪物的进度值总和应该合理分配
        - 每个楼层都应该有相应的挑战和奖励
        - 任务描述要生动有趣，符合DnD风格
        """
        
        try:
            # 定义任务生成的JSON schema
            quest_schema = {
                "type": "object",
                "properties": {
                    "quests": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "objectives": {"type": "array", "items": {"type": "string"}},
                                "experience_reward": {"type": "integer"},
                                "story_context": {"type": "string"},
                                "progress_percentage": {"type": "number"},
                                "quest_type": {"type": "string"},
                                "target_floors": {"type": "array", "items": {"type": "integer"}},
                                "map_themes": {"type": "array", "items": {"type": "string"}},
                                "special_events": {"type": "array"},
                                "special_monsters": {"type": "array"}
                            }
                        }
                    }
                }
            }

            # 使用复杂内容生成方法，确保在Ubuntu服务器上的兼容性
            result = await llm_service.generate_complex_content(
                prompt=main_quest_prompt,
                context_data={
                    "player_level": player_level,
                    "max_floors": max_floors,
                    "chain_length": chain_length
                },
                schema=quest_schema
            )
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

                    # 新增：任务专属内容
                    quest.quest_type = quest_data.get("quest_type", "exploration")
                    quest.target_floors = quest_data.get("target_floors", [1, 2])
                    quest.map_themes = quest_data.get("map_themes", ["地下城"])

                    # 处理专属事件
                    from data_models import QuestEvent
                    for event_data in quest_data.get("special_events", []):
                        event = QuestEvent()
                        event.event_type = event_data.get("event_type", "story")
                        event.name = event_data.get("name", "")
                        event.description = event_data.get("description", "")
                        event.trigger_condition = event_data.get("trigger_condition", "")
                        event.progress_value = event_data.get("progress_value", 0.0)
                        event.is_mandatory = event_data.get("is_mandatory", True)
                        event.location_hint = event_data.get("location_hint", "")
                        quest.special_events.append(event)

                    # 处理专属怪物
                    from data_models import QuestMonster
                    for monster_data in quest_data.get("special_monsters", []):
                        monster = QuestMonster()
                        monster.name = monster_data.get("name", "")
                        monster.description = monster_data.get("description", "")
                        monster.challenge_rating = monster_data.get("challenge_rating", 1.0)
                        monster.is_boss = monster_data.get("is_boss", False)
                        monster.progress_value = monster_data.get("progress_value", 0.0)
                        monster.spawn_condition = monster_data.get("spawn_condition", "")
                        monster.location_hint = monster_data.get("location_hint", "")
                        quest.special_monsters.append(monster)

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

    def find_stairs_position(self, game_map: GameMap, stairs_type: TerrainType) -> Optional[Tuple[int, int]]:
        """查找指定类型楼梯的位置"""
        for (x, y), tile in game_map.tiles.items():
            if tile.terrain == stairs_type:
                return (x, y)
        return None

    def get_stairs_spawn_position(self, game_map: GameMap, stairs_type: TerrainType) -> Optional[Tuple[int, int]]:
        """获取楼梯附近的生成位置"""
        stairs_pos = self.find_stairs_position(game_map, stairs_type)
        if not stairs_pos:
            return None

        stairs_x, stairs_y = stairs_pos

        # 查找楼梯周围的空地板位置
        for radius in range(1, 4):  # 逐渐扩大搜索范围
            candidates = []
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    if dx == 0 and dy == 0:  # 跳过楼梯本身
                        continue

                    x, y = stairs_x + dx, stairs_y + dy
                    tile = game_map.get_tile(x, y)

                    if (tile and
                        tile.terrain == TerrainType.FLOOR and
                        not tile.character_id):
                        candidates.append((x, y))

            if candidates:
                # 优先选择距离楼梯最近的位置
                candidates.sort(key=lambda pos: abs(pos[0] - stairs_x) + abs(pos[1] - stairs_y))
                return candidates[0]

        # 如果楼梯周围没有空位，返回楼梯位置本身
        return stairs_pos

    async def _generate_map_events(self, game_map: GameMap, rooms: List[Dict[str, int]], quest_context: Optional[Dict[str, Any]] = None):
        """为地图生成事件"""
        floor_tiles = [(x, y) for (x, y), tile in game_map.tiles.items()
                      if tile.terrain == TerrainType.FLOOR and not tile.character_id]

        if not floor_tiles:
            return

        # 首先放置任务专属事件
        quest_events_placed = 0
        if quest_context and quest_context.get('special_events'):
            special_events = quest_context['special_events']
            current_depth = game_map.depth

            # 筛选适合当前楼层的专属事件
            suitable_events = [
                event for event in special_events
                if not event.get('location_hint') or str(current_depth) in event.get('location_hint', '')
            ]

            # 放置专属事件
            for event_data in suitable_events[:min(len(suitable_events), len(floor_tiles) // 4)]:
                if floor_tiles:
                    x, y = random.choice(floor_tiles)
                    floor_tiles.remove((x, y))

                    tile = game_map.get_tile(x, y)
                    if tile:
                        tile.has_event = True
                        tile.event_type = event_data.get('event_type', 'story')
                        tile.is_event_hidden = True  # 任务事件通常隐藏
                        tile.event_triggered = False
                        tile.event_data = {
                            'quest_event_id': event_data.get('id'),
                            'name': event_data.get('name'),
                            'description': event_data.get('description'),
                            'progress_value': event_data.get('progress_value', 0.0),
                            'is_mandatory': event_data.get('is_mandatory', True)
                        }
                        quest_events_placed += 1

        # 计算普通事件数量（基于地图大小，减去已放置的任务事件）
        total_tiles = len(floor_tiles)
        normal_event_count = max(2, total_tiles // 20) - quest_events_placed

        if normal_event_count > 0 and floor_tiles:
            # 随机选择普通事件位置
            event_positions = random.sample(floor_tiles, min(normal_event_count, len(floor_tiles)))

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

    async def _validate_and_adjust_room_types(self, game_map: GameMap, rooms: List[Dict[str, int]],
                                            quest_context: Optional[Dict[str, Any]] = None) -> List[Dict[str, int]]:
        """验证和调整房间类型配置，确保满足任务需求"""
        if not rooms:
            return rooms

        # 分析任务需求
        required_room_types = self._get_required_room_types(quest_context, game_map.depth)

        # 分配房间类型
        room_types = self._assign_room_types_by_requirements(rooms, required_room_types)

        # 验证房间配置
        validation_result = self._validate_room_configuration(rooms, room_types, required_room_types)

        if not validation_result["is_valid"]:
            logger.warning(f"房间配置验证失败: {validation_result['issues']}")
            # 尝试自动修复
            rooms, room_types = await self._auto_fix_room_configuration(
                game_map, rooms, room_types, required_room_types, validation_result
            )

        # 应用房间类型到地图瓦片
        self._apply_room_types_to_map(game_map, rooms, room_types)

        # 为房间添加类型信息
        for i, room in enumerate(rooms):
            room["type"] = room_types[i] if i < len(room_types) else "normal"

        logger.info(f"房间类型分配完成: {dict(zip(room_types, [room_types.count(t) for t in set(room_types)]))}")
        return rooms

    def _get_required_room_types(self, quest_context: Optional[Dict[str, Any]], depth: int) -> Dict[str, Any]:
        """根据任务上下文和楼层深度确定必需的房间类型"""
        required = {
            "entrance": 1,  # 至少需要一个入口房间
            "normal": 1,    # 至少需要一个普通房间
            "treasure": 0,
            "boss": 0,
            "special": 0,
            "corridor": True  # 需要走廊连接
        }

        if not quest_context:
            return required

        # 根据任务类型调整需求
        quest_type = quest_context.get('quest_type', 'exploration')

        if quest_type == 'boss_fight' or depth == config.game.max_quest_floors:
            required["boss"] = 1
            required["treasure"] = 1  # Boss房间通常有宝藏
        elif quest_type == 'treasure_hunt':
            required["treasure"] = max(2, depth)  # 寻宝任务需要更多宝藏房间
            required["special"] = 1
        elif quest_type == 'exploration':
            required["special"] = 1
            if depth > 1:
                required["treasure"] = 1

        # 根据特殊事件调整需求
        special_events = quest_context.get('special_events', [])
        current_depth_events = [
            event for event in special_events
            if not event.get('location_hint') or str(depth) in event.get('location_hint', '')
        ]

        # 为每个特殊事件至少需要一个特殊房间
        if current_depth_events:
            required["special"] = max(required["special"], len(current_depth_events))

        return required

    def _assign_room_types_by_requirements(self, rooms: List[Dict[str, int]], required_room_types: Dict[str, Any]) -> List[str]:
        """为房间分配类型"""
        room_types = ["normal"] * len(rooms)

        if not rooms:
            return room_types

        # 第一个房间通常是入口
        room_types[0] = "entrance"
        assigned_count = {"entrance": 1, "normal": len(rooms) - 1}

        # 分配必需的特殊房间
        available_indices = list(range(1, len(rooms)))  # 除了入口房间

        # 分配Boss房间（通常在最后）
        if required_room_types.get("boss", 0) > 0 and available_indices:
            boss_index = available_indices[-1]  # 最后一个房间
            room_types[boss_index] = "boss"
            available_indices.remove(boss_index)
            assigned_count["boss"] = 1
            assigned_count["normal"] -= 1

        # 分配宝藏房间
        treasure_needed = required_room_types.get("treasure", 0)
        for _ in range(min(treasure_needed, len(available_indices))):
            if available_indices:
                treasure_index = random.choice(available_indices)
                room_types[treasure_index] = "treasure"
                available_indices.remove(treasure_index)
                assigned_count["treasure"] = assigned_count.get("treasure", 0) + 1
                assigned_count["normal"] -= 1

        # 分配特殊房间
        special_needed = required_room_types.get("special", 0)
        for _ in range(min(special_needed, len(available_indices))):
            if available_indices:
                special_index = random.choice(available_indices)
                room_types[special_index] = "special"
                available_indices.remove(special_index)
                assigned_count["special"] = assigned_count.get("special", 0) + 1
                assigned_count["normal"] -= 1

        return room_types

    def _validate_room_configuration(self, rooms: List[Dict[str, int]], room_types: List[str],
                                   required_room_types: Dict[str, Any]) -> Dict[str, Any]:
        """验证房间配置是否满足需求"""
        issues = []

        # 统计实际房间类型
        actual_counts = {}
        for room_type in room_types:
            actual_counts[room_type] = actual_counts.get(room_type, 0) + 1

        # 检查必需房间类型
        for room_type, required_count in required_room_types.items():
            if room_type == "corridor":
                continue  # 走廊单独检查

            actual_count = actual_counts.get(room_type, 0)
            if actual_count < required_count:
                issues.append(f"缺少{room_type}房间: 需要{required_count}个，实际{actual_count}个")

        # 检查入口房间
        if actual_counts.get("entrance", 0) == 0:
            issues.append("缺少入口房间")

        # 检查房间总数是否合理
        if len(rooms) < 3:
            issues.append(f"房间数量过少: {len(rooms)}个（建议至少3个）")

        return {
            "is_valid": len(issues) == 0,
            "issues": issues,
            "actual_counts": actual_counts
        }

    async def _auto_fix_room_configuration(self, game_map: GameMap, rooms: List[Dict[str, int]],
                                         room_types: List[str], required_room_types: Dict[str, Any],
                                         validation_result: Dict[str, Any]) -> Tuple[List[Dict[str, int]], List[str]]:
        """自动修复房间配置问题"""
        logger.info("尝试自动修复房间配置...")

        # 如果房间数量不足，尝试添加房间
        if len(rooms) < 3:
            additional_rooms = await self._add_emergency_rooms(game_map, rooms, 3 - len(rooms))
            rooms.extend(additional_rooms)
            room_types.extend(["normal"] * len(additional_rooms))

        # 重新分配房间类型以满足需求
        room_types = self._assign_room_types_by_requirements(rooms, required_room_types)

        # 再次验证
        new_validation = self._validate_room_configuration(rooms, room_types, required_room_types)
        if new_validation["is_valid"]:
            logger.info("房间配置自动修复成功")
        else:
            logger.warning(f"房间配置自动修复后仍有问题: {new_validation['issues']}")

        return rooms, room_types

    async def _add_emergency_rooms(self, game_map: GameMap, existing_rooms: List[Dict[str, int]],
                                 count: int) -> List[Dict[str, int]]:
        """在地图中添加紧急房间"""
        new_rooms = []

        # 寻找可用空间
        for _ in range(count):
            room_position = self._find_available_space_for_room(game_map, existing_rooms + new_rooms)
            if room_position:
                new_room = {
                    "x": room_position[0],
                    "y": room_position[1],
                    "width": room_position[2],
                    "height": room_position[3],
                    "type": "normal",
                    "id": str(uuid.uuid4())
                }

                # 在地图上雕刻新房间
                self._carve_room(game_map, new_room)

                # 连接到现有房间网络
                if existing_rooms or new_rooms:
                    nearest_room = self._find_nearest_room(new_room, existing_rooms + new_rooms)
                    if nearest_room:
                        self._connect_two_rooms(game_map, new_room, nearest_room)

                new_rooms.append(new_room)
                logger.info(f"添加紧急房间: {new_room}")

        return new_rooms

    def _find_available_space_for_room(self, game_map: GameMap, existing_rooms: List[Dict[str, int]]) -> Optional[Tuple[int, int, int, int]]:
        """寻找可用空间来放置新房间"""
        min_room_size = 3
        max_room_size = 6

        # 尝试多次寻找合适位置
        for _ in range(50):
            width = random.randint(min_room_size, min(max_room_size, game_map.width - 2))
            height = random.randint(min_room_size, min(max_room_size, game_map.height - 2))
            x = random.randint(1, game_map.width - width - 1)
            y = random.randint(1, game_map.height - height - 1)

            # 检查是否与现有房间重叠
            new_room = {"x": x, "y": y, "width": width, "height": height}
            if not self._room_overlaps_with_existing(new_room, existing_rooms):
                return (x, y, width, height)

        return None

    def _room_overlaps_with_existing(self, new_room: Dict[str, int], existing_rooms: List[Dict[str, int]]) -> bool:
        """检查新房间是否与现有房间重叠"""
        for existing_room in existing_rooms:
            if self._rooms_overlap(new_room, existing_room):
                return True
        return False

    def _rooms_overlap(self, room1: Dict[str, int], room2: Dict[str, int]) -> bool:
        """检查两个房间是否重叠（包括缓冲区）"""
        # 添加1格缓冲区
        r1_left = room1["x"] - 1
        r1_right = room1["x"] + room1["width"] + 1
        r1_top = room1["y"] - 1
        r1_bottom = room1["y"] + room1["height"] + 1

        r2_left = room2["x"] - 1
        r2_right = room2["x"] + room2["width"] + 1
        r2_top = room2["y"] - 1
        r2_bottom = room2["y"] + room2["height"] + 1

        return not (r1_right <= r2_left or r2_right <= r1_left or
                   r1_bottom <= r2_top or r2_bottom <= r1_top)

    def _find_nearest_room(self, target_room: Dict[str, int], rooms: List[Dict[str, int]]) -> Optional[Dict[str, int]]:
        """找到距离目标房间最近的房间"""
        if not rooms:
            return None

        min_distance = float('inf')
        nearest_room = None

        for room in rooms:
            distance = self._calculate_room_distance(target_room, room)
            if distance < min_distance:
                min_distance = distance
                nearest_room = room

        return nearest_room

    def _apply_room_types_to_map(self, game_map: GameMap, rooms: List[Dict[str, int]], room_types: List[str]):
        """将房间类型应用到地图瓦片"""
        for i, room in enumerate(rooms):
            room_type = room_types[i] if i < len(room_types) else "normal"
            room_id = room.get("id", f"room_{i}")

            # 为房间内的所有地板瓦片设置房间类型
            for x in range(room["x"], room["x"] + room["width"]):
                for y in range(room["y"], room["y"] + room["height"]):
                    tile = game_map.get_tile(x, y)
                    if tile and tile.terrain == TerrainType.FLOOR:
                        tile.room_type = room_type
                        tile.room_id = room_id


# 全局内容生成器实例
content_generator = ContentGenerator()

__all__ = ["ContentGenerator", "content_generator"]
