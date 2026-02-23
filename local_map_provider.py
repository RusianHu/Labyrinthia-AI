"""
Labyrinthia AI - 本地地图生成提供器
用于在后端安全接入本地地图算法，并可回退到LLM地图生成。
"""

from __future__ import annotations

import logging
import random
import re
from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple

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

        requirements = self._analyze_quest_requirements(quest_context, game_map.depth)
        rooms = self._build_rooms(width, height, requirements)

        self._init_walls(game_map)
        self._carve_rooms(game_map, rooms)
        self._connect_rooms(game_map, rooms, requirements)
        self._assign_room_types(rooms, game_map.depth, requirements)
        self._paint_room_types(game_map, rooms)
        stairs = self._place_stairs(game_map, rooms, game_map.depth)
        self._place_special_terrain(game_map, rooms, stairs)
        self._place_events(game_map, quest_context)

        validation_report = self._validate_and_repair_map(game_map, rooms, stairs, quest_context)
        monster_hints = self._build_monster_hints(game_map, rooms, quest_context)

        if not isinstance(game_map.generation_metadata, dict):
            game_map.generation_metadata = {}
        game_map.generation_metadata.update(
            {
                "local_requirements": requirements,
                "local_validation": validation_report,
            }
        )

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

    def _build_rooms(
        self,
        width: int,
        height: int,
        requirements: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        req = requirements or {}

        def _safe_int(value: Any, default: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        min_rooms = max(3, _safe_int(req.get("min_rooms", 4), 4))
        max_rooms = max(min_rooms, min(12, _safe_int(req.get("max_rooms", 10), 10)))
        room_count = max(min_rooms, min(max_rooms, (width * height) // 120 if width * height > 0 else min_rooms))

        rooms: List[Dict[str, Any]] = []
        attempts = room_count * 24
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

    def _connect_rooms(
        self,
        game_map: GameMap,
        rooms: List[Dict[str, Any]],
        requirements: Optional[Dict[str, Any]] = None,
    ) -> None:
        if len(rooms) <= 1:
            return

        req = requirements or {}
        style = str(req.get("layout_style", "standard"))

        if style == "hub":
            center = rooms[0]
            for room in rooms[1:]:
                self._connect_two_rooms(game_map, center, room)
            return

        if style == "linear":
            for idx in range(len(rooms) - 1):
                self._connect_two_rooms(game_map, rooms[idx], rooms[idx + 1])
            return

        self._connect_all_rooms(game_map, rooms)

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

        if tile.terrain in {
            TerrainType.STAIRS_UP,
            TerrainType.STAIRS_DOWN,
            TerrainType.TRAP,
            TerrainType.TREASURE,
            TerrainType.DOOR,
        }:
            return

        if tile.terrain == TerrainType.WALL:
            tile.terrain = TerrainType.FLOOR

        if not tile.room_type:
            tile.room_type = "corridor"

    def _assign_room_types(
        self,
        rooms: List[Dict[str, Any]],
        depth: int,
        requirements: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not rooms:
            return

        req = requirements or {}
        needs_boss = bool(req.get("needs_boss_room", False)) or depth >= config.game.max_quest_floors
        needs_treasure = bool(req.get("needs_treasure_room", False))
        needs_special = max(0, int(req.get("needs_special_rooms", 0)))

        rooms[0]["type"] = "entrance"

        if len(rooms) > 1:
            if needs_boss:
                rooms[-1]["type"] = "boss"
            else:
                rooms[-1]["type"] = "special"

        assigned_special = 0
        assigned_treasure = 0

        for i in range(1, max(1, len(rooms) - 1)):
            if rooms[i]["type"] != "normal":
                continue

            if assigned_treasure < (1 if needs_treasure else 0):
                rooms[i]["type"] = "treasure"
                assigned_treasure += 1
                continue

            if assigned_special < needs_special:
                rooms[i]["type"] = "special"
                assigned_special += 1
                continue

            roll = random.random()
            if roll < 0.2:
                rooms[i]["type"] = "treasure"
            elif roll < 0.45:
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
        event_tiles = [
            (x, y)
            for (x, y), tile in game_map.tiles.items()
            if tile.terrain in {TerrainType.FLOOR, TerrainType.DOOR}
            and not tile.has_event
            and not tile.character_id
        ]
        random.shuffle(event_tiles)

        def _to_bool(value: Any, default_value: bool = False) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"true", "1", "yes", "y", "on"}:
                    return True
                if normalized in {"false", "0", "no", "n", "off", ""}:
                    return False
            if value is None:
                return default_value
            return bool(value)

        def _default_event_payload(event_type: str) -> Dict[str, Any]:
            if event_type == "combat":
                return {
                    "monster_count": random.randint(1, 3),
                    "difficulty": random.choice(["easy", "medium", "hard"]),
                }
            if event_type == "treasure":
                return {
                    "treasure_type": random.choice(["gold", "item", "magic_item"]),
                    "value": random.randint(50, 300),
                }
            if event_type == "trap":
                from trap_schema import trap_validator

                trap_type = random.choice(["damage", "debuff", "teleport"])
                payload = {
                    "trap_type": trap_type,
                    "trap_name": "本地生成陷阱",
                    "detect_dc": random.randint(12, 18),
                    "disarm_dc": random.randint(15, 20),
                    "save_dc": random.randint(12, 16),
                    "damage": random.randint(6, 24),
                }
                try:
                    normalized = trap_validator.validate_and_normalize(payload)
                    if isinstance(normalized, dict) and normalized:
                        return normalized
                except Exception as exc:
                    logger.warning(f"Trap payload normalize failed, using fallback trap payload: {exc}")

                return {
                    "trap_type": payload["trap_type"],
                    "trap_name": payload["trap_name"],
                    "detect_dc": payload["detect_dc"],
                    "disarm_dc": payload["disarm_dc"],
                    "save_dc": payload["save_dc"],
                    "damage": payload["damage"],
                }
            if event_type == "mystery":
                return {"mystery_type": random.choice(["puzzle", "riddle", "choice"])}
            return {"story_type": random.choice(["discovery", "memory", "vision", "encounter"])}

        # 任务专属事件（按楼层过滤）
        if quest_context and isinstance(quest_context.get("special_events"), list):
            current_depth = max(1, int(getattr(game_map, "depth", 1)))
            for event_data in quest_context["special_events"]:
                if not isinstance(event_data, dict):
                    continue
                if not self._matches_depth_hint(event_data, current_depth):
                    continue

                if not event_tiles:
                    break
                x, y = event_tiles.pop()
                tile = game_map.get_tile(x, y)
                if not tile:
                    continue
                tile.has_event = True
                tile.event_type = event_data.get("event_type", "story")
                tile.is_event_hidden = True
                tile.event_triggered = False
                tile.event_data = {
                    "quest_event_id": event_data.get("id") or event_data.get("event_id"),
                    "name": event_data.get("name", "任务事件"),
                    "description": event_data.get("description", ""),
                    "progress_value": event_data.get("progress_value", 0.0),
                    "is_mandatory": _to_bool(event_data.get("is_mandatory", False), default_value=False),
                }

        # 普通事件
        normal_event_count = min(8, max(2, len(event_tiles) // 18))
        event_types = ["combat", "treasure", "story", "trap", "mystery"]
        for _ in range(normal_event_count):
            if not event_tiles:
                break
            x, y = event_tiles.pop()
            tile = game_map.get_tile(x, y)
            if not tile:
                continue

            event_type = random.choice(event_types)
            tile.has_event = True
            tile.event_type = event_type
            tile.is_event_hidden = random.choice([True, True, False])
            tile.event_triggered = False
            tile.event_data = _default_event_payload(event_type)

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

        room_intents = []
        for room in rooms:
            room_type = room.get("type", "normal")
            intents: Dict[str, Any] = {
                "id": room.get("id"),
                "role": room_type,
                "event_intents": [],
                "monster_intents": {},
            }
            if room_type == "boss":
                intents["monster_intents"] = {"difficulty": "boss", "count": max(1, boss_count)}
            elif room_type == "special":
                intents["event_intents"] = ["story", "mystery"]
            elif room_type == "treasure":
                intents["event_intents"] = ["treasure"]
            else:
                intents["monster_intents"] = {"difficulty": difficulty_map.get(quest_type, "medium"), "count": 1}
            room_intents.append(intents)

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
                "blueprint_mode": False,
            },
            "room_intents": room_intents,
            "corridor_intents": [],
        }

        if not config.game.local_map_monster_hints_enabled:
            hint["spawn_points"] = []

        return hint

    def _analyze_quest_requirements(self, quest_context: Optional[Dict[str, Any]], depth: int) -> Dict[str, Any]:
        requirements = {
            "min_rooms": 3,
            "max_rooms": 8,
            "needs_boss_room": False,
            "needs_treasure_room": False,
            "needs_special_rooms": 0,
            "layout_style": "standard",
        }

        if not quest_context:
            if depth >= config.game.max_quest_floors:
                requirements["needs_boss_room"] = True
                requirements["layout_style"] = "linear"
            return requirements

        quest_type = str(quest_context.get("quest_type", "exploration"))
        if quest_type == "boss_fight":
            requirements["needs_boss_room"] = True
            requirements["layout_style"] = "linear"
        elif quest_type == "treasure_hunt":
            requirements["needs_treasure_room"] = True
            requirements["needs_special_rooms"] = 1
        elif quest_type == "exploration":
            requirements["layout_style"] = "hub"
            requirements["needs_special_rooms"] = 1

        special_events = quest_context.get("special_events") if isinstance(quest_context.get("special_events"), list) else []
        special_monsters = quest_context.get("special_monsters") if isinstance(quest_context.get("special_monsters"), list) else []
        current_floor_events = [
            event for event in special_events
            if isinstance(event, dict) and self._matches_depth_hint(event, depth)
        ]
        current_floor_monsters = [
            monster for monster in special_monsters
            if isinstance(monster, dict) and self._matches_depth_hint(monster, depth)
        ]

        required_rooms = max(3, len(current_floor_events) + len(current_floor_monsters))
        requirements["min_rooms"] = min(10, max(requirements["min_rooms"], required_rooms))

        if depth >= config.game.max_quest_floors:
            requirements["needs_boss_room"] = True
            requirements["layout_style"] = "linear"

        return requirements

    def _connect_two_rooms(self, game_map: GameMap, room1: Dict[str, Any], room2: Dict[str, Any]) -> None:
        x1, y1 = self._center(room1)
        x2, y2 = self._center(room2)
        self._carve_corridor(game_map, x1, y1, x2, y1)
        self._carve_corridor(game_map, x2, y1, x2, y2)

    def _connect_all_rooms(self, game_map: GameMap, rooms: List[Dict[str, Any]]) -> None:
        if len(rooms) <= 1:
            return

        distances: List[Tuple[float, int, int]] = []
        for i in range(len(rooms)):
            for j in range(i + 1, len(rooms)):
                x1, y1 = self._center(rooms[i])
                x2, y2 = self._center(rooms[j])
                d = abs(x1 - x2) + abs(y1 - y2)
                distances.append((d, i, j))
        distances.sort(key=lambda item: item[0])

        parent = list(range(len(rooms)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> bool:
            pa = find(a)
            pb = find(b)
            if pa == pb:
                return False
            parent[pa] = pb
            return True

        used_edges: List[Tuple[int, int]] = []
        for _, i, j in distances:
            if union(i, j):
                self._connect_two_rooms(game_map, rooms[i], rooms[j])
                used_edges.append((i, j))
                if len(used_edges) >= len(rooms) - 1:
                    break

        extra_edges = min(2, max(0, len(distances) - len(used_edges)))
        for _, i, j in distances[-extra_edges:]:
            if random.random() < 0.3:
                self._connect_two_rooms(game_map, rooms[i], rooms[j])

    def _neighbors4(self, x: int, y: int) -> List[Tuple[int, int]]:
        return [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]

    def _is_walkable_for_pathing(self, tile: Optional[MapTile]) -> bool:
        if not tile:
            return False
        return tile.terrain in self.WALKABLE_TERRAINS

    def _collect_reachable_positions(self, game_map: GameMap, start: Tuple[int, int]) -> Set[Tuple[int, int]]:
        start_tile = game_map.get_tile(*start)
        if not self._is_walkable_for_pathing(start_tile):
            return set()

        visited: Set[Tuple[int, int]] = {start}
        queue: deque[Tuple[int, int]] = deque([start])

        while queue:
            cx, cy = queue.popleft()
            for nx, ny in self._neighbors4(cx, cy):
                if (nx, ny) in visited:
                    continue
                tile = game_map.get_tile(nx, ny)
                if not self._is_walkable_for_pathing(tile):
                    continue
                visited.add((nx, ny))
                queue.append((nx, ny))

        return visited

    def _get_key_targets(self, game_map: GameMap, stairs: Dict[str, Optional[Tuple[int, int]]]) -> List[Tuple[int, int]]:
        targets: List[Tuple[int, int]] = []
        if stairs.get("up"):
            targets.append(stairs["up"])
        if stairs.get("down"):
            targets.append(stairs["down"])

        for (x, y), tile in game_map.tiles.items():
            if not tile.has_event:
                continue
            event_data = tile.event_data if isinstance(tile.event_data, dict) else {}
            if event_data.get("is_mandatory") is True:
                targets.append((x, y))

        deduped: List[Tuple[int, int]] = []
        seen: Set[Tuple[int, int]] = set()
        for pos in targets:
            if pos not in seen:
                seen.add(pos)
                deduped.append(pos)
        return deduped

    def _repair_unreachable_targets(
        self,
        game_map: GameMap,
        reachable: Set[Tuple[int, int]],
        targets: List[Tuple[int, int]],
    ) -> int:
        repaired = 0
        if not reachable:
            return repaired

        for tx, ty in targets:
            if (tx, ty) in reachable:
                continue

            best_src: Optional[Tuple[int, int]] = None
            best_dist = 10**9
            for sx, sy in reachable:
                dist = abs(tx - sx) + abs(ty - sy)
                if dist < best_dist:
                    best_dist = dist
                    best_src = (sx, sy)

            if not best_src:
                continue

            sx, sy = best_src
            end_x, end_y = tx, ty
            target_tile = game_map.get_tile(tx, ty)
            if target_tile and target_tile.terrain in {TerrainType.STAIRS_UP, TerrainType.STAIRS_DOWN}:
                neighbor_candidates: List[Tuple[int, int]] = []
                for nx, ny in self._neighbors4(tx, ty):
                    ntile = game_map.get_tile(nx, ny)
                    if not ntile:
                        continue
                    if ntile.terrain in {TerrainType.STAIRS_UP, TerrainType.STAIRS_DOWN}:
                        continue
                    neighbor_candidates.append((nx, ny))
                if neighbor_candidates:
                    neighbor_candidates.sort(key=lambda pos: abs(pos[0] - sx) + abs(pos[1] - sy))
                    end_x, end_y = neighbor_candidates[0]

            self._carve_corridor(game_map, sx, sy, end_x, sy)
            self._carve_corridor(game_map, end_x, sy, end_x, end_y)
            repaired += 1
            reachable.update(self._collect_reachable_positions(game_map, (sx, sy)))

        return repaired

    def _validate_and_repair_map(
        self,
        game_map: GameMap,
        rooms: List[Dict[str, Any]],
        stairs: Dict[str, Optional[Tuple[int, int]]],
        quest_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        report: Dict[str, Any] = {
            "connectivity_ok": True,
            "repaired_targets": 0,
            "unreachable_targets_before": 0,
            "unreachable_targets_after": 0,
            "required_target_count": 0,
            "walkable_tiles": 0,
            "warnings": [],
        }

        if not rooms:
            report["warnings"].append("rooms_empty")
            report["connectivity_ok"] = False
            return report

        start = stairs.get("up") or self._center(rooms[0])
        reachable = self._collect_reachable_positions(game_map, start)
        targets = self._get_key_targets(game_map, stairs)
        report["required_target_count"] = len(targets)

        unreachable_before = [t for t in targets if t not in reachable]
        report["unreachable_targets_before"] = len(unreachable_before)

        if unreachable_before:
            repaired = self._repair_unreachable_targets(game_map, reachable, unreachable_before)
            report["repaired_targets"] = repaired
            reachable = self._collect_reachable_positions(game_map, start)

        unreachable_after = [t for t in targets if t not in reachable]
        report["unreachable_targets_after"] = len(unreachable_after)
        report["connectivity_ok"] = len(unreachable_after) == 0

        walkable = sum(1 for tile in game_map.tiles.values() if tile.terrain in self.WALKABLE_TERRAINS)
        report["walkable_tiles"] = walkable

        min_walkable = max(20, int(game_map.width * game_map.height * 0.15))
        if walkable < min_walkable:
            report["warnings"].append("walkable_area_low")

        if quest_context and isinstance(quest_context.get("special_events"), list):
            current_depth = max(1, int(getattr(game_map, "depth", 1)))
            mandatory_total = sum(
                1
                for e in quest_context["special_events"]
                if isinstance(e, dict)
                and self._matches_depth_hint(e, current_depth)
                and e.get("is_mandatory") is True
            )
            placed_mandatory = sum(
                1
                for tile in game_map.tiles.values()
                if tile.has_event
                and isinstance(tile.event_data, dict)
                and tile.event_data.get("is_mandatory") is True
            )
            report["mandatory_events_expected"] = mandatory_total
            report["mandatory_events_placed"] = placed_mandatory
            if mandatory_total > placed_mandatory:
                report["warnings"].append("mandatory_events_partially_placed")

        return report

    def _matches_depth_hint(self, data: Dict[str, Any], depth: int) -> bool:
        floor_number = data.get("floor_number")
        if isinstance(floor_number, int):
            return floor_number == depth

        location_hint = str(data.get("location_hint", "") or "")
        if not location_hint:
            return True

        numbers = [int(match) for match in re.findall(r"\d+", location_hint)]
        if not numbers:
            return True
        return depth in numbers


local_map_provider = LocalMapProvider()
