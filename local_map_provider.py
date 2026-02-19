"""
Labyrinthia AI - 本地地图生成提供器
用于在后端安全接入本地地图算法，并可回退到LLM地图生成。
"""

from __future__ import annotations

import logging
import random
from typing import Any, Dict, List, Optional, Tuple

from config import config
from data_models import GameMap, MapTile, TerrainType


logger = logging.getLogger(__name__)


class LocalMapProvider:
    """后端本地地图提供器（轻量可回退实现）"""

    WALKABLE_TERRAINS = {
        TerrainType.FLOOR,
        TerrainType.DOOR,
        TerrainType.TRAP,
        TerrainType.TREASURE,
        TerrainType.STAIRS_UP,
        TerrainType.STAIRS_DOWN,
    }

    def generate_map(
        self,
        width: int,
        height: int,
        depth: int,
        theme: str,
        quest_context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[GameMap, Dict[str, Any]]:
        """生成本地地图并返回 (GameMap, monster_hints)"""
        game_map = GameMap()
        game_map.width = width
        game_map.height = height
        game_map.depth = max(1, depth)
        game_map.floor_theme = self._infer_floor_theme(theme, quest_context)
        game_map.name = self._build_map_name(theme, game_map.depth)
        game_map.description = self._build_map_description(theme, quest_context)

        rooms = self._build_rooms(width, height)
        self._init_walls(game_map)
        self._carve_rooms(game_map, rooms)
        self._connect_rooms(game_map, rooms)
        self._assign_room_types(rooms, game_map.depth)
        self._paint_room_types(game_map, rooms)
        stairs = self._place_stairs(game_map, rooms, game_map.depth)
        self._place_special_terrain(game_map, rooms, stairs)
        self._place_events(game_map, quest_context)

        monster_hints = self._build_monster_hints(game_map, rooms, quest_context)
        return game_map, monster_hints

    def _infer_floor_theme(self, theme: str, quest_context: Optional[Dict[str, Any]]) -> str:
        valid = {
            "normal",
            "magic",
            "abandoned",
            "cave",
            "combat",
            "grassland",
            "desert",
            "farmland",
            "snowfield",
            "town",
        }
        if isinstance(theme, str) and theme in valid:
            return theme

        if quest_context:
            for candidate in quest_context.get("map_themes", []):
                if candidate in valid:
                    return candidate

            quest_type = quest_context.get("quest_type", "exploration")
            mapping = {
                "boss_fight": "combat",
                "exploration": "abandoned",
                "rescue": "cave",
                "investigation": "town",
            }
            if quest_type in mapping:
                return mapping[quest_type]

        return "normal"

    def _build_map_name(self, theme: str, depth: int) -> str:
        name = theme if isinstance(theme, str) and theme.strip() else "冒险区域"
        if "阶段/层级" in name:
            return name
        return f"{name}（第{depth}阶段/层级）"

    def _build_map_description(self, theme: str, quest_context: Optional[Dict[str, Any]]) -> str:
        quest_text = ""
        if quest_context:
            quest_text = quest_context.get("description", "") or ""
        if quest_text:
            return f"围绕任务推进构建的区域：{quest_text}"
        if theme:
            return f"围绕{theme}主题构建的探索区域。"
        return "一个由本地算法构建的探索区域。"

    def _init_walls(self, game_map: GameMap) -> None:
        for x in range(game_map.width):
            for y in range(game_map.height):
                game_map.tiles[(x, y)] = MapTile(x=x, y=y, terrain=TerrainType.WALL)

    def _build_rooms(self, width: int, height: int) -> List[Dict[str, Any]]:
        room_count = max(4, min(10, (width * height) // 120))
        rooms: List[Dict[str, Any]] = []
        attempts = room_count * 20
        room_id = 1

        while len(rooms) < room_count and attempts > 0:
            attempts -= 1
            rw = random.randint(4, 8)
            rh = random.randint(4, 8)
            if width - rw - 2 <= 1 or height - rh - 2 <= 1:
                break

            rx = random.randint(1, width - rw - 2)
            ry = random.randint(1, height - rh - 2)
            room = {
                "id": f"room-{room_id}",
                "x": rx,
                "y": ry,
                "width": rw,
                "height": rh,
                "type": "normal",
            }

            if any(self._overlap(room, r) for r in rooms):
                continue

            rooms.append(room)
            room_id += 1

        if not rooms:
            fallback = {
                "id": "room-1",
                "x": 1,
                "y": 1,
                "width": max(4, width - 2),
                "height": max(4, height - 2),
                "type": "entrance",
            }
            rooms.append(fallback)

        return rooms

    def _overlap(self, a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        margin = 1
        return (
            a["x"] - margin < b["x"] + b["width"] + margin
            and a["x"] + a["width"] + margin > b["x"] - margin
            and a["y"] - margin < b["y"] + b["height"] + margin
            and a["y"] + a["height"] + margin > b["y"] - margin
        )

    def _carve_rooms(self, game_map: GameMap, rooms: List[Dict[str, Any]]) -> None:
        for room in rooms:
            for x in range(room["x"], room["x"] + room["width"]):
                for y in range(room["y"], room["y"] + room["height"]):
                    tile = game_map.get_tile(x, y)
                    if not tile:
                        continue
                    tile.terrain = TerrainType.FLOOR
                    tile.room_id = room["id"]
                    tile.room_type = room["type"]

    def _center(self, room: Dict[str, Any]) -> Tuple[int, int]:
        return room["x"] + room["width"] // 2, room["y"] + room["height"] // 2

    def _connect_rooms(self, game_map: GameMap, rooms: List[Dict[str, Any]]) -> None:
        for idx in range(len(rooms) - 1):
            x1, y1 = self._center(rooms[idx])
            x2, y2 = self._center(rooms[idx + 1])
            self._carve_corridor(game_map, x1, y1, x2, y1)
            self._carve_corridor(game_map, x2, y1, x2, y2)

    def _carve_corridor(self, game_map: GameMap, x1: int, y1: int, x2: int, y2: int) -> None:
        if x1 == x2:
            for y in range(min(y1, y2), max(y1, y2) + 1):
                self._set_corridor_tile(game_map, x1, y)
            return

        for x in range(min(x1, x2), max(x1, x2) + 1):
            self._set_corridor_tile(game_map, x, y1)

    def _set_corridor_tile(self, game_map: GameMap, x: int, y: int) -> None:
        tile = game_map.get_tile(x, y)
        if not tile:
            return
        tile.terrain = TerrainType.FLOOR
        if not tile.room_type:
            tile.room_type = "corridor"

    def _assign_room_types(self, rooms: List[Dict[str, Any]], depth: int) -> None:
        if not rooms:
            return

        rooms[0]["type"] = "entrance"
        if len(rooms) > 1 and depth >= config.game.max_quest_floors:
            rooms[-1]["type"] = "boss"
        elif len(rooms) > 1:
            rooms[-1]["type"] = "special"

        for i in range(1, max(1, len(rooms) - 1)):
            if rooms[i]["type"] != "normal":
                continue
            roll = random.random()
            if roll < 0.2:
                rooms[i]["type"] = "treasure"
            elif roll < 0.4:
                rooms[i]["type"] = "special"

    def _paint_room_types(self, game_map: GameMap, rooms: List[Dict[str, Any]]) -> None:
        for room in rooms:
            room_type = room.get("type", "normal")
            room_id = room["id"]
            for x in range(room["x"], room["x"] + room["width"]):
                for y in range(room["y"], room["y"] + room["height"]):
                    tile = game_map.get_tile(x, y)
                    if tile and tile.room_id == room_id:
                        tile.room_type = room_type

    def _place_stairs(
        self,
        game_map: GameMap,
        rooms: List[Dict[str, Any]],
        depth: int,
    ) -> Dict[str, Optional[Tuple[int, int]]]:
        stairs: Dict[str, Optional[Tuple[int, int]]] = {"up": None, "down": None}
        if not rooms:
            return stairs

        if depth > 1:
            ux, uy = self._center(rooms[0])
            tile = game_map.get_tile(ux, uy)
            if tile:
                tile.terrain = TerrainType.STAIRS_UP
                stairs["up"] = (ux, uy)

        if depth < config.game.max_quest_floors and len(rooms) > 1:
            dx, dy = self._center(rooms[-1])
            tile = game_map.get_tile(dx, dy)
            if tile:
                tile.terrain = TerrainType.STAIRS_DOWN
                stairs["down"] = (dx, dy)

        return stairs

    def _place_special_terrain(
        self,
        game_map: GameMap,
        rooms: List[Dict[str, Any]],
        stairs: Dict[str, Optional[Tuple[int, int]]],
    ) -> None:
        blocked = set()
        if stairs.get("up"):
            blocked.add(stairs["up"])
        if stairs.get("down"):
            blocked.add(stairs["down"])

        floor_tiles = [
            pos for pos, tile in game_map.tiles.items()
            if tile.terrain == TerrainType.FLOOR and pos not in blocked
        ]

        random.shuffle(floor_tiles)
        trap_count = min(4, max(1, len(floor_tiles) // 30))
        treasure_count = min(3, max(1, len(floor_tiles) // 40))

        for _ in range(trap_count):
            if not floor_tiles:
                break
            x, y = floor_tiles.pop()
            tile = game_map.get_tile(x, y)
            if tile:
                tile.terrain = TerrainType.TRAP
                tile.trap_detected = False
                tile.trap_disarmed = False

        for _ in range(treasure_count):
            if not floor_tiles:
                break
            x, y = floor_tiles.pop()
            tile = game_map.get_tile(x, y)
            if tile and tile.terrain == TerrainType.FLOOR:
                tile.terrain = TerrainType.TREASURE

        self._place_doors(game_map, blocked)

    def _place_doors(self, game_map: GameMap, blocked: set[Tuple[int, int]]) -> None:
        candidates: List[Tuple[int, int]] = []
        for (x, y), tile in game_map.tiles.items():
            if (x, y) in blocked:
                continue
            if tile.terrain != TerrainType.FLOOR:
                continue

            neighbors = [
                game_map.get_tile(x + 1, y),
                game_map.get_tile(x - 1, y),
                game_map.get_tile(x, y + 1),
                game_map.get_tile(x, y - 1),
            ]
            has_corridor = any(n and n.room_type == "corridor" for n in neighbors)
            has_room = any(n and n.room_type not in ("", "corridor") for n in neighbors)
            wall_count = sum(1 for n in neighbors if n and n.terrain == TerrainType.WALL)

            if has_corridor and has_room and wall_count >= 1:
                candidates.append((x, y))

        random.shuffle(candidates)
        door_target = min(8, max(1, len(candidates) // 3))
        for x, y in candidates[:door_target]:
            tile = game_map.get_tile(x, y)
            if tile and tile.terrain == TerrainType.FLOOR:
                tile.terrain = TerrainType.DOOR

    def _place_events(self, game_map: GameMap, quest_context: Optional[Dict[str, Any]]) -> None:
        floor_tiles = [
            (x, y)
            for (x, y), tile in game_map.tiles.items()
            if tile.terrain in {TerrainType.FLOOR, TerrainType.DOOR, TerrainType.TRAP, TerrainType.TREASURE}
            and not tile.has_event
            and not tile.character_id
        ]
        random.shuffle(floor_tiles)

        # 任务专属事件
        if quest_context and isinstance(quest_context.get("special_events"), list):
            for event_data in quest_context["special_events"]:
                if not floor_tiles:
                    break
                x, y = floor_tiles.pop()
                tile = game_map.get_tile(x, y)
                if not tile:
                    continue
                tile.has_event = True
                tile.event_type = event_data.get("event_type", "story")
                tile.is_event_hidden = True
                tile.event_triggered = False
                tile.event_data = {
                    "quest_event_id": event_data.get("id"),
                    "name": event_data.get("name", "任务事件"),
                    "description": event_data.get("description", ""),
                    "progress_value": event_data.get("progress_value", 0.0),
                    "is_mandatory": event_data.get("is_mandatory", True),
                }

        # 普通事件
        normal_event_count = min(6, max(2, len(floor_tiles) // 20))
        event_types = ["combat", "treasure", "story", "trap", "mystery"]
        for _ in range(normal_event_count):
            if not floor_tiles:
                break
            x, y = floor_tiles.pop()
            tile = game_map.get_tile(x, y)
            if not tile:
                continue

            event_type = random.choice(event_types)
            tile.has_event = True
            tile.event_type = event_type
            tile.is_event_hidden = random.choice([True, True, False])
            tile.event_triggered = False

            if event_type == "combat":
                tile.event_data = {
                    "monster_count": random.randint(1, 3),
                    "difficulty": random.choice(["easy", "medium", "hard"]),
                }
            elif event_type == "treasure":
                tile.event_data = {
                    "treasure_type": random.choice(["gold", "item", "magic_item"]),
                    "value": random.randint(50, 300),
                }
            elif event_type == "trap":
                tile.event_data = {
                    "trap_type": random.choice(["damage", "debuff", "teleport"]),
                    "trap_name": "本地生成陷阱",
                    "detect_dc": random.randint(12, 18),
                    "disarm_dc": random.randint(15, 20),
                    "save_dc": random.randint(12, 16),
                    "damage": random.randint(6, 24),
                }
            elif event_type == "mystery":
                tile.event_data = {
                    "mystery_type": random.choice(["puzzle", "riddle", "choice"]),
                }
            else:
                tile.event_data = {
                    "story_type": random.choice(["discovery", "memory", "vision", "encounter"]),
                }

    def _build_monster_hints(
        self,
        game_map: GameMap,
        rooms: List[Dict[str, Any]],
        quest_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        quest_type = "exploration"
        if quest_context and isinstance(quest_context.get("quest_type"), str):
            quest_type = quest_context["quest_type"]

        difficulty_map = {
            "boss_fight": "hard",
            "exploration": "medium",
            "rescue": "medium",
            "investigation": "normal",
        }

        floor_tiles = [
            (x, y, tile)
            for (x, y), tile in game_map.tiles.items()
            if tile.terrain in self.WALKABLE_TERRAINS and tile.terrain not in {TerrainType.STAIRS_UP, TerrainType.STAIRS_DOWN}
        ]

        normal_candidates: List[Tuple[int, int]] = []
        boss_candidates: List[Tuple[int, int]] = []
        special_candidates: List[Tuple[int, int]] = []

        for x, y, tile in floor_tiles:
            room_type = tile.room_type or "normal"
            if room_type == "boss":
                boss_candidates.append((x, y))
            elif room_type == "special":
                special_candidates.append((x, y))
            else:
                normal_candidates.append((x, y))

        random.shuffle(normal_candidates)
        random.shuffle(boss_candidates)
        random.shuffle(special_candidates)

        depth = max(1, game_map.depth)
        encounter_count = max(1, min(8, max(1, len(rooms) // 2)))
        boss_count = 1 if depth >= config.game.max_quest_floors else 0
        if quest_type == "boss_fight":
            boss_count = max(1, boss_count)
            encounter_count = min(8, encounter_count + 1)

        spawn_points: List[Dict[str, Any]] = []

        for _ in range(encounter_count):
            if normal_candidates:
                x, y = normal_candidates.pop()
            elif special_candidates:
                x, y = special_candidates.pop()
            elif boss_candidates:
                x, y = boss_candidates.pop()
            else:
                break
            spawn_points.append({"x": x, "y": y, "role": "encounter"})

        for _ in range(boss_count):
            if boss_candidates:
                x, y = boss_candidates.pop()
            elif special_candidates:
                x, y = special_candidates.pop()
            elif normal_candidates:
                x, y = normal_candidates.pop()
            else:
                break
            spawn_points.append({"x": x, "y": y, "role": "boss"})

        hint = {
            "source": "local_map_provider",
            "spawn_strategy": "llm_generate_by_positions",
            "recommended_player_level": max(1, min(30, 1 + depth * 2)),
            "encounter_difficulty": difficulty_map.get(quest_type, "medium"),
            "encounter_count": encounter_count,
            "boss_count": boss_count,
            "spawn_points": spawn_points,
            "llm_context": {
                "quest_type": quest_type,
                "map_title": game_map.name,
                "map_depth": depth,
                "floor_theme": game_map.floor_theme,
                "width": game_map.width,
                "height": game_map.height,
            },
        }

        if not config.game.local_map_monster_hints_enabled:
            hint["spawn_points"] = []

        return hint


local_map_provider = LocalMapProvider()
