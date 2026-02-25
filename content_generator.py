"""
Labyrinthia AI - 内容生成器
Content generator for the Labyrinthia AI game
"""

import random
import asyncio
import logging
import re
import uuid
import json
import hashlib
from collections import deque
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
from generation_contract import (
    CONTRACT_VERSION,
    contract_hash,
    extract_contract_request,
    resolve_generation_contract,
)


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

        # 【优化】智能推断地图主题（防御性编程）
        inferred_theme = theme
        if quest_context:
            quest_type = quest_context.get('quest_type', 'exploration')
            quest_desc = quest_context.get('description', '').lower()
            map_themes = quest_context.get('map_themes', [])

            # 如果任务没有提供map_themes，根据quest_type和description智能推断
            if not map_themes:
                logger.info(f"Quest has no map_themes, inferring from quest_type '{quest_type}' and description")

                # 基于任务类型的默认主题
                type_theme_map = {
                    'investigation': 'town',
                    'rescue': 'cave',
                    'combat': 'combat',
                    'exploration': 'normal',
                    'mystery': 'abandoned',
                    'story': 'normal'
                }
                inferred_theme = type_theme_map.get(quest_type, 'normal')

                # 基于描述关键词进一步优化
                if any(kw in quest_desc for kw in ['城镇', '村庄', '街道', '聚居', '疾病', '居民', '镇']):
                    inferred_theme = 'town'
                elif any(kw in quest_desc for kw in ['森林', '林间', '树木', '野外', '草原']):
                    inferred_theme = 'grassland'
                elif any(kw in quest_desc for kw in ['农场', '田野', '种植', '庄稼', '草药']):
                    inferred_theme = 'farmland'
                elif any(kw in quest_desc for kw in ['洞穴', '地下', '潮湿', '矿井', '矿道']):
                    inferred_theme = 'cave'
                elif any(kw in quest_desc for kw in ['废弃', '遗忘', '古老', '破败', '荒废']):
                    inferred_theme = 'abandoned'
                elif any(kw in quest_desc for kw in ['魔法', '神殿', '法师', '符文', '魔力']):
                    inferred_theme = 'magic'
                elif any(kw in quest_desc for kw in ['战斗', '竞技', '血腥', '屠杀', '战场']):
                    inferred_theme = 'combat'
                elif any(kw in quest_desc for kw in ['雪', '冰', '寒冷', '冬季', '冰霜']):
                    inferred_theme = 'snowfield'
                elif any(kw in quest_desc for kw in ['沙漠', '荒地', '干旱', '沙丘']):
                    inferred_theme = 'desert'

                logger.info(f"Inferred theme: '{inferred_theme}' for quest '{quest_context.get('title', 'Unknown')}'")

        # 构建任务相关的提示信息
        quest_info = ""
        if quest_context:
            special_events = quest_context.get('special_events', [])
            special_monsters = quest_context.get('special_monsters', [])
            map_themes = quest_context.get('map_themes', [])

            # 如果没有map_themes，使用推断的主题
            theme_hint = map_themes if map_themes else [inferred_theme]

            quest_info = f"""

        当前任务信息：
        - 任务类型：{quest_context.get('quest_type', 'exploration')}
        - 任务标题：{quest_context.get('title', '未知任务')}
        - 任务描述：{quest_context.get('description', '探索区域')}
        - 目标楼层：{quest_context.get('target_floors', [depth])}
        - 建议主题：{theme_hint}（推断主题：{inferred_theme}）
        - 当前楼层：第{depth}层（共{config.game.max_quest_floors}层）
        - 专属事件：{len(special_events)}个
        - 专属怪物：{len(special_monsters)}个
        - 故事背景：{quest_context.get('story_context', '神秘的探索之旅')}

        楼层定位：
        {'- 这是起始层，应该相对安全，适合新手探索' if depth == 1 else ''}
        {'- 这是中间层，难度适中，包含重要的任务元素' if 1 < depth < config.game.max_quest_floors else ''}
        {'- 这是最终层，应该包含任务的高潮和结局' if depth == config.game.max_quest_floors else ''}

        请根据任务信息和楼层定位调整地图的名称和描述，使其与任务背景和当前进度相符。
        **重要**：请根据任务类型、描述和建议主题选择最贴切的floor_theme！
        """

        # 使用PromptManager生成地图名称、描述和地板主题
        try:
            map_prompt = prompt_manager.format_prompt(
                "map_info_generation",
                width=width,
                height=height,
                depth=depth,
                theme=inferred_theme,  # 使用推断的主题
                quest_info=quest_info
            )

            map_info = await llm_service._async_generate_json(map_prompt)
            if map_info:
                game_map.name = map_info.get("name", f"冒险区域（第{depth}阶段/层级）")
                game_map.description = map_info.get("description", "一个神秘的冒险区域")
                # 获取地板主题，验证是否为有效值
                floor_theme = map_info.get("floor_theme", "normal")
                valid_themes = ["normal", "magic", "abandoned", "cave", "combat", "grassland", "desert", "farmland", "snowfield", "town"]
                if floor_theme in valid_themes:
                    game_map.floor_theme = floor_theme
                    logger.info(f"Map '{game_map.name}' (depth {depth}) floor_theme set to: {floor_theme}")
                else:
                    logger.warning(f"Invalid floor_theme '{floor_theme}', using inferred theme '{inferred_theme}'")
                    game_map.floor_theme = inferred_theme if inferred_theme in valid_themes else "normal"
        except Exception as e:
            logger.error(f"Failed to generate map info: {e}")
            game_map.name = f"冒险区域（第{depth}阶段/层级）"
            game_map.description = "一个神秘的冒险区域"
            # 【修复】使用推断的主题而不是总是使用"normal"
            game_map.floor_theme = inferred_theme if inferred_theme in ["normal", "magic", "abandoned", "cave", "combat", "grassland", "desert", "farmland", "snowfield", "town"] else "normal"
            logger.info(f"Using fallback floor_theme: {game_map.floor_theme}")
        
        provided_contract, requested_contract_version, contract_source_hint = extract_contract_request(quest_context)
        contract_resolution = resolve_generation_contract(
            provided_contract=provided_contract,
            requested_version=requested_contract_version,
            source_hint=contract_source_hint,
        )
        generation_contract = contract_resolution.contract
        generation_contract_hash = contract_hash(generation_contract)

        # 生成基础地图结构（优先蓝图驱动，失败自动回退）
        layout_metadata = await self._generate_map_layout(
            game_map,
            quest_context,
            generation_contract=generation_contract,
        )

        if not isinstance(game_map.generation_metadata, dict):
            game_map.generation_metadata = {}
        if isinstance(layout_metadata, dict):
            game_map.generation_metadata.update(layout_metadata)

        game_map.generation_metadata.update(
            {
                "contract_version": generation_contract.get("contract_version", CONTRACT_VERSION),
                "contract_hash": generation_contract_hash,
                "contract_source": contract_resolution.source,
                "generation_contract": generation_contract,
                "contract_warnings": contract_resolution.warnings,
                "reproduction_bundle": self._build_generation_reproduction_bundle(
                    quest_context=quest_context,
                    generation_contract=generation_contract,
                    generation_contract_hash=generation_contract_hash,
                    game_map=game_map,
                ),
            }
        )

        return game_map
    
    async def _generate_map_layout(
        self,
        game_map: GameMap,
        quest_context: Optional[Dict[str, Any]] = None,
        generation_contract: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """生成地图布局（蓝图驱动优先，稳定算法回退）"""
        self._reset_map_tiles_to_walls(game_map)

        contract = generation_contract if isinstance(generation_contract, dict) else resolve_generation_contract().contract

        # 根据任务需求调整房间生成策略
        room_requirements = self._analyze_quest_requirements(quest_context, game_map.depth)

        layout_meta: Dict[str, Any] = {
            "blueprint_enabled": True,
            "blueprint_used": False,
            "blueprint_fallback_reason": "",
        }

        blueprint: Optional[Dict[str, Any]] = None
        try:
            blueprint = await self._generate_map_blueprint(
                game_map,
                room_requirements,
                quest_context,
                generation_contract=contract,
            )
            validated_blueprint, blueprint_report = self._validate_and_fix_blueprint(
                blueprint=blueprint,
                room_requirements=room_requirements,
                depth=game_map.depth,
                generation_contract=contract,
            )

            rooms, realization_errors = self._realize_rooms_from_blueprint(
                width=game_map.width,
                height=game_map.height,
                room_requirements=room_requirements,
                blueprint=validated_blueprint,
            )

            for room in rooms:
                self._carve_room(game_map, room)

            corridor_report = self._connect_rooms_from_blueprint(
                game_map=game_map,
                rooms=rooms,
                blueprint=validated_blueprint,
                requirements=room_requirements,
            )

            rooms = await self._validate_and_adjust_room_types(game_map, rooms, quest_context)
            await self._place_special_terrain(game_map, rooms)
            event_report = await self._generate_map_events(game_map, rooms, quest_context, blueprint=validated_blueprint)

            monster_hints = self._build_monster_hints_from_blueprint(game_map, rooms, validated_blueprint, quest_context)
            layout_meta.update(
                {
                    "blueprint_used": True,
                    "blueprint_report": blueprint_report,
                    "monster_hints": monster_hints,
                    "realization_errors": realization_errors,
                    "corridor_report": corridor_report,
                    "event_placement_report": event_report,
                    "reachability_proof": self._build_reachability_proof(game_map),
                }
            )
            return layout_meta
        except Exception as e:
            logger.exception(f"Blueprint pipeline failed, fallback to stable algorithm: {e}")
            layout_meta["blueprint_fallback_reason"] = str(e)
            # 防止蓝图流程中途失败留下半成品地图，回退前重置
            self._reset_map_tiles_to_walls(game_map)

        # 稳定算法回退路径
        rooms = self._generate_rooms_with_quest_context(
            game_map.width, game_map.height, room_requirements
        )

        for room in rooms:
            self._carve_room(game_map, room)

        self._connect_rooms_strategically(game_map, rooms, room_requirements)
        rooms = await self._validate_and_adjust_room_types(game_map, rooms, quest_context)
        await self._place_special_terrain(game_map, rooms)
        await self._generate_map_events(game_map, rooms, quest_context)

        layout_meta["blueprint_used"] = False
        layout_meta["reachability_proof"] = self._build_reachability_proof(game_map)
        return layout_meta

    def _build_reachability_proof(self, game_map: GameMap) -> Dict[str, Any]:
        walkable = {
            pos
            for pos, tile in game_map.tiles.items()
            if tile.terrain in {TerrainType.FLOOR, TerrainType.DOOR, TerrainType.TRAP, TerrainType.TREASURE, TerrainType.STAIRS_UP, TerrainType.STAIRS_DOWN}
        }
        if not walkable:
            return {
                "start": None,
                "targets": [],
                "reachable_targets": 0,
                "unreachable_targets": 0,
                "proof_ok": False,
            }

        stairs_up = next((pos for pos, tile in game_map.tiles.items() if tile.terrain == TerrainType.STAIRS_UP), None)
        start = stairs_up if stairs_up in walkable else next(iter(walkable))

        targets: List[Dict[str, Any]] = []
        mandatory_positions = [
            pos
            for pos, tile in game_map.tiles.items()
            if tile.has_event and isinstance(tile.event_data, dict) and tile.event_data.get("is_mandatory") is True
        ]
        for pos in mandatory_positions:
            targets.append({"type": "mandatory_event", "position": [pos[0], pos[1]]})

        stairs_down = next((pos for pos, tile in game_map.tiles.items() if tile.terrain == TerrainType.STAIRS_DOWN), None)
        if stairs_down:
            targets.append({"type": "stairs_down", "position": [stairs_down[0], stairs_down[1]]})

        def _bfs_shortest_path_len(start_pos: Tuple[int, int], target_pos: Tuple[int, int]) -> int:
            if target_pos not in walkable:
                return -1
            if start_pos == target_pos:
                return 0
            visited = {start_pos}
            queue = deque([(start_pos[0], start_pos[1], 0)])
            while queue:
                x, y, dist = queue.popleft()
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    nxt = (nx, ny)
                    if nxt not in walkable or nxt in visited:
                        continue
                    if nxt == target_pos:
                        return dist + 1
                    visited.add(nxt)
                    queue.append((nx, ny, dist + 1))
            return -1

        resolved_targets: List[Dict[str, Any]] = []
        reachable_count = 0
        for target in targets:
            pos_raw = target.get("position", [])
            if not isinstance(pos_raw, list) or len(pos_raw) != 2:
                continue
            tx, ty = int(pos_raw[0]), int(pos_raw[1])
            path_len = _bfs_shortest_path_len(start, (tx, ty))
            reachable = path_len >= 0
            if reachable:
                reachable_count += 1
            resolved_targets.append(
                {
                    "type": target.get("type", "unknown"),
                    "position": [tx, ty],
                    "reachable": reachable,
                    "path_length": path_len,
                }
            )

        unreachable_count = len(resolved_targets) - reachable_count
        return {
            "start": [start[0], start[1]],
            "targets": resolved_targets,
            "reachable_targets": reachable_count,
            "unreachable_targets": unreachable_count,
            "proof_ok": unreachable_count == 0,
        }

    def _build_generation_reproduction_bundle(
        self,
        quest_context: Optional[Dict[str, Any]],
        generation_contract: Dict[str, Any],
        generation_contract_hash: str,
        game_map: GameMap,
    ) -> Dict[str, Any]:
        ctx = quest_context if isinstance(quest_context, dict) else {}
        stable_seed_payload = {
            "quest_type": str(ctx.get("quest_type", "") or ""),
            "title": str(ctx.get("title", "") or ""),
            "description": str(ctx.get("description", "") or ""),
            "depth": int(getattr(game_map, "depth", 1) or 1),
            "width": int(getattr(game_map, "width", 0) or 0),
            "height": int(getattr(game_map, "height", 0) or 0),
            "contract_hash": generation_contract_hash,
        }
        stable_seed_raw = json.dumps(stable_seed_payload, ensure_ascii=False, sort_keys=True)
        stable_seed = hashlib.sha1(stable_seed_raw.encode("utf-8")).hexdigest()[:16]

        return {
            "contract_version": generation_contract.get("contract_version", CONTRACT_VERSION),
            "contract_hash": generation_contract_hash,
            "stable_seed": stable_seed,
            "patch_batches": [],
        }

    def _get_map_blueprint_schema(self, generation_contract: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """地图蓝图Schema：LLM只输出结构约束，不输出绝对坐标。"""
        contract = generation_contract if isinstance(generation_contract, dict) else resolve_generation_contract().contract
        blueprint_rules = contract.get("blueprint", {}) if isinstance(contract.get("blueprint"), dict) else {}

        room_sizes = blueprint_rules.get("room_size_whitelist") if isinstance(blueprint_rules.get("room_size_whitelist"), list) else ["small", "medium", "large"]
        placement_policies = blueprint_rules.get("placement_policy_whitelist") if isinstance(blueprint_rules.get("placement_policy_whitelist"), list) else ["center", "edge", "branch", "corridor_adjacent"]
        event_policy = blueprint_rules.get("event_policy_whitelist") if isinstance(blueprint_rules.get("event_policy_whitelist"), list) else ["mandatory", "optional", "forbidden"]
        corridor_kind = blueprint_rules.get("corridor_kind_whitelist") if isinstance(blueprint_rules.get("corridor_kind_whitelist"), list) else ["direct", "branch", "loop"]
        gate_whitelist = blueprint_rules.get("corridor_gate_whitelist") if isinstance(blueprint_rules.get("corridor_gate_whitelist"), list) else ["none", "locked", "key", "boss_gate"]
        risk_whitelist = blueprint_rules.get("corridor_risk_whitelist") if isinstance(blueprint_rules.get("corridor_risk_whitelist"), list) else ["low", "medium", "high", "deadly"]

        return {
            "type": "object",
            "properties": {
                "room_nodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "role": {
                                "type": "string",
                                "enum": ["entrance", "normal", "treasure", "boss", "special", "exit"],
                            },
                            "size": {"type": "string", "enum": room_sizes},
                            "placement_policy": {"type": "string", "enum": placement_policies},
                            "must_contain": {"type": "array", "items": {"type": "string"}},
                            "room_tags": {"type": "array", "items": {"type": "string"}},
                            "event_intents": {"type": "array", "items": {"type": "string"}},
                            "monster_intents": {
                                "type": "object",
                                "properties": {
                                    "difficulty": {"type": "string", "enum": ["easy", "medium", "hard", "boss"]},
                                    "count": {"type": "integer", "minimum": 0, "maximum": 8},
                                },
                            },
                        },
                        "required": ["id", "role"],
                    },
                },
                "corridor_edges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "from": {"type": "string"},
                            "to": {"type": "string"},
                            "kind": {"type": "string", "enum": corridor_kind},
                            "locked": {"type": "boolean"},
                            "risk_level": {"type": "string", "enum": risk_whitelist},
                            "gate_type": {"type": "string", "enum": gate_whitelist},
                            "encounter_bias": {"type": "string"},
                            "event_intents": {"type": "array", "items": {"type": "string"}},
                            "monster_intents": {
                                "type": "object",
                                "properties": {
                                    "difficulty": {"type": "string", "enum": ["easy", "medium", "hard", "boss"]},
                                    "count": {"type": "integer", "minimum": 0, "maximum": 6},
                                },
                            },
                        },
                        "required": ["from", "to"],
                    },
                },
                "quest_monster_bindings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "quest_monster_id": {"type": "string"},
                            "binding_type": {"type": "string", "enum": ["node", "edge"]},
                            "node_id": {"type": "string"},
                            "from": {"type": "string"},
                            "to": {"type": "string"},
                            "priority": {"type": "string", "enum": ["primary", "secondary"]},
                        },
                        "required": ["quest_monster_id", "binding_type"],
                    },
                },
                "event_plan": {
                    "type": "object",
                    "properties": {
                        "mandatory": {"type": "array", "items": {"type": "string"}},
                        "optional": {"type": "array", "items": {"type": "string"}},
                        "forbidden": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "progress_plan": {
                    "type": "object",
                    "properties": {
                        "completion_policy": {"type": "string", "enum": ["aggregate", "single_target_100", "hybrid"]},
                        "budget": {
                            "type": "object",
                            "properties": {
                                "events": {"type": "number"},
                                "quest_monsters": {"type": "number"},
                                "map_transition": {"type": "number"},
                                "exploration_buffer": {"type": "number"},
                            },
                        },
                        "final_objective_id": {"type": "string"},
                    },
                },
                "key_path": {"type": "array", "items": {"type": "string"},
                },
                "difficulty": {"type": "string", "enum": ["easy", "medium", "hard", "boss"]},
                "trap_density_cap": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
            "required": ["room_nodes", "corridor_edges"],
        }

    def _build_map_blueprint_prompt(
        self,
        game_map: GameMap,
        room_requirements: Dict[str, Any],
        quest_context: Optional[Dict[str, Any]],
    ) -> str:
        """构建蓝图提示词：明确禁止输出坐标。"""
        quest_text = ""
        if quest_context:
            quest_text = (
                f"任务类型: {quest_context.get('quest_type', 'exploration')}\n"
                f"任务标题: {quest_context.get('title', '未知任务')}\n"
                f"任务描述: {quest_context.get('description', '无')}\n"
            )

        return (
            "你是地下城结构规划器。请只输出结构化蓝图JSON，不要输出任何精确坐标。\n"
            "蓝图必须包含: room_nodes(房间节点), corridor_edges(通道边), 可选的quest_monster_bindings/event_plan/progress_plan。\n"
            "每个房间用id+role表示，不得包含x/y坐标。\n"
            "\n"
            f"地图尺寸: {game_map.width}x{game_map.height}, 深度: {game_map.depth}\n"
            f"房间需求: {room_requirements}\n"
            f"{quest_text}\n"
            "约束: \n"
            "1) 至少一个entrance。\n"
            "2) 最终层建议包含boss。\n"
            "3) corridor_edges确保整体连通。\n"
            "4) trap_density_cap不超过0.35。\n"
            "5) 事件/怪物意图使用短标签，如combat/treasure/trap/story/mystery。\n"
            "6) 支持placement_policy、must_contain、room_tags、risk_level、gate_type、encounter_bias。\n"
            "7) 严禁输出坐标、像素、绝对位置。"
        )

    async def _generate_map_blueprint(
        self,
        game_map: GameMap,
        room_requirements: Dict[str, Any],
        quest_context: Optional[Dict[str, Any]],
        generation_contract: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """调用LLM生成地图蓝图（结构约束层）。"""
        schema = self._get_map_blueprint_schema(generation_contract)
        prompt = self._build_map_blueprint_prompt(game_map, room_requirements, quest_context)
        blueprint = await llm_service._async_generate_json(prompt, schema=schema)
        if not isinstance(blueprint, dict) or not blueprint:
            raise ValueError("empty blueprint from llm")
        if "room_nodes" not in blueprint:
            raise ValueError("blueprint missing room_nodes")
        return blueprint

    def _sanitize_blueprint(
        self,
        blueprint: Dict[str, Any],
        generation_contract: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], int]:
        """白名单过滤蓝图字段，防止非法字段进入后续逻辑。"""
        allowed_top = {
            "room_nodes",
            "corridor_edges",
            "quest_monster_bindings",
            "event_plan",
            "progress_plan",
            "key_path",
            "difficulty",
            "trap_density_cap",
        }
        valid_event_types = {"combat", "treasure", "story", "trap", "mystery"}
        valid_room_roles = {"entrance", "normal", "treasure", "boss", "special", "exit"}
        valid_difficulty = {"easy", "medium", "hard", "boss"}

        contract = generation_contract if isinstance(generation_contract, dict) else resolve_generation_contract().contract
        blueprint_rules = contract.get("blueprint") if isinstance(contract.get("blueprint"), dict) else {}
        safety_rules = contract.get("safety") if isinstance(contract.get("safety"), dict) else {}

        room_size_whitelist = set(
            blueprint_rules.get("room_size_whitelist")
            if isinstance(blueprint_rules.get("room_size_whitelist"), list)
            else ["small", "medium", "large"]
        )
        placement_policy_whitelist = set(
            blueprint_rules.get("placement_policy_whitelist")
            if isinstance(blueprint_rules.get("placement_policy_whitelist"), list)
            else ["center", "edge", "branch", "corridor_adjacent"]
        )
        corridor_kind_whitelist = set(
            blueprint_rules.get("corridor_kind_whitelist")
            if isinstance(blueprint_rules.get("corridor_kind_whitelist"), list)
            else ["direct", "branch", "loop"]
        )
        corridor_gate_whitelist = set(
            blueprint_rules.get("corridor_gate_whitelist")
            if isinstance(blueprint_rules.get("corridor_gate_whitelist"), list)
            else ["none", "locked", "key", "boss_gate"]
        )
        corridor_risk_whitelist = set(
            blueprint_rules.get("corridor_risk_whitelist")
            if isinstance(blueprint_rules.get("corridor_risk_whitelist"), list)
            else ["low", "medium", "high", "deadly"]
        )

        max_nodes = max(1, int(blueprint_rules.get("max_nodes", 32) or 32))
        max_edges = max(1, int(blueprint_rules.get("max_edges", 96) or 96))
        max_intents_per_item = max(1, int(blueprint_rules.get("max_intents_per_item", 6) or 6))
        max_key_path_len = max(4, int(blueprint_rules.get("max_key_path_len", 64) or 64))
        max_id_len = max(16, int(safety_rules.get("max_id_length", 48) or 48))

        sanitized: Dict[str, Any] = {}
        filtered_count = 0

        def normalize_node_id(raw: Any) -> Optional[str]:
            if not isinstance(raw, str):
                return None
            candidate = raw.strip()
            if not candidate:
                return None
            candidate = re.sub(r"[^A-Za-z0-9_-]", "_", candidate)
            candidate = candidate[:max_id_len].strip("_")
            return candidate or None

        for k, v in blueprint.items():
            if k in allowed_top:
                sanitized[k] = v
            else:
                filtered_count += 1

        room_nodes: List[Dict[str, Any]] = []
        raw_nodes = sanitized.get("room_nodes") if isinstance(sanitized.get("room_nodes"), list) else []
        if len(raw_nodes) > max_nodes:
            filtered_count += len(raw_nodes) - max_nodes
            raw_nodes = raw_nodes[:max_nodes]

        for node in raw_nodes:
            if not isinstance(node, dict):
                filtered_count += 1
                continue
            nn: Dict[str, Any] = {}
            nid = normalize_node_id(node.get("id"))
            role = node.get("role")
            if nid:
                nn["id"] = nid
            if isinstance(role, str) and role in valid_room_roles:
                nn["role"] = role
            size = node.get("size")
            if isinstance(size, str) and size in room_size_whitelist:
                nn["size"] = size
            placement_policy = node.get("placement_policy")
            if isinstance(placement_policy, str) and placement_policy in placement_policy_whitelist:
                nn["placement_policy"] = placement_policy
            must_contain = node.get("must_contain")
            if isinstance(must_contain, list):
                nn["must_contain"] = [str(v) for v in must_contain[:8] if str(v).strip()]
            room_tags = node.get("room_tags")
            if isinstance(room_tags, list):
                nn["room_tags"] = [str(v) for v in room_tags[:8] if str(v).strip()]
            event_intents = node.get("event_intents")
            if isinstance(event_intents, list):
                validated_intents = [
                    e for e in event_intents if isinstance(e, str) and e in valid_event_types
                ]
                if len(validated_intents) > max_intents_per_item:
                    filtered_count += len(validated_intents) - max_intents_per_item
                    validated_intents = validated_intents[:max_intents_per_item]
                nn["event_intents"] = validated_intents
            monster_intents = node.get("monster_intents")
            if isinstance(monster_intents, dict):
                mi: Dict[str, Any] = {}
                mdiff = monster_intents.get("difficulty")
                if isinstance(mdiff, str) and mdiff in valid_difficulty:
                    mi["difficulty"] = mdiff
                mcount = monster_intents.get("count")
                if isinstance(mcount, int):
                    mi["count"] = max(0, min(8, mcount))
                if mi:
                    nn["monster_intents"] = mi
            if "id" in nn and "role" in nn:
                room_nodes.append(nn)
            else:
                filtered_count += 1

        corridor_edges: List[Dict[str, Any]] = []
        raw_edges = sanitized.get("corridor_edges") if isinstance(sanitized.get("corridor_edges"), list) else []
        if len(raw_edges) > max_edges:
            filtered_count += len(raw_edges) - max_edges
            raw_edges = raw_edges[:max_edges]

        for edge in raw_edges:
            if not isinstance(edge, dict):
                filtered_count += 1
                continue
            ee: Dict[str, Any] = {}
            frm = normalize_node_id(edge.get("from"))
            to = normalize_node_id(edge.get("to"))
            if frm and to:
                ee["from"] = frm
                ee["to"] = to
            else:
                filtered_count += 1
                continue
            kind = edge.get("kind")
            if isinstance(kind, str) and kind in corridor_kind_whitelist:
                ee["kind"] = kind
            locked = edge.get("locked")
            if isinstance(locked, bool):
                ee["locked"] = locked
            risk_level = edge.get("risk_level")
            if isinstance(risk_level, str) and risk_level in corridor_risk_whitelist:
                ee["risk_level"] = risk_level
            gate_type = edge.get("gate_type")
            if isinstance(gate_type, str) and gate_type in corridor_gate_whitelist:
                ee["gate_type"] = gate_type
            encounter_bias = edge.get("encounter_bias")
            if isinstance(encounter_bias, str) and encounter_bias.strip():
                ee["encounter_bias"] = encounter_bias.strip()[:32]
            event_intents = edge.get("event_intents")
            if isinstance(event_intents, list):
                validated_intents = [
                    e for e in event_intents if isinstance(e, str) and e in valid_event_types
                ]
                if len(validated_intents) > max_intents_per_item:
                    filtered_count += len(validated_intents) - max_intents_per_item
                    validated_intents = validated_intents[:max_intents_per_item]
                ee["event_intents"] = validated_intents
            monster_intents = edge.get("monster_intents")
            if isinstance(monster_intents, dict):
                mi = {}
                mdiff = monster_intents.get("difficulty")
                if isinstance(mdiff, str) and mdiff in valid_difficulty:
                    mi["difficulty"] = mdiff
                mcount = monster_intents.get("count")
                if isinstance(mcount, int):
                    mi["count"] = max(0, min(6, mcount))
                if mi:
                    ee["monster_intents"] = mi
            corridor_edges.append(ee)

        sanitized["room_nodes"] = room_nodes
        sanitized["corridor_edges"] = corridor_edges

        raw_bindings = sanitized.get("quest_monster_bindings") if isinstance(sanitized.get("quest_monster_bindings"), list) else []
        bindings: List[Dict[str, Any]] = []
        for binding in raw_bindings[:64]:
            if not isinstance(binding, dict):
                filtered_count += 1
                continue
            item: Dict[str, Any] = {}
            quest_monster_id = normalize_node_id(binding.get("quest_monster_id"))
            binding_type = binding.get("binding_type")
            if quest_monster_id:
                item["quest_monster_id"] = quest_monster_id
            if isinstance(binding_type, str) and binding_type in {"node", "edge"}:
                item["binding_type"] = binding_type
            if binding_type == "node":
                node_id = normalize_node_id(binding.get("node_id"))
                if node_id:
                    item["node_id"] = node_id
            if binding_type == "edge":
                frm = normalize_node_id(binding.get("from"))
                to = normalize_node_id(binding.get("to"))
                if frm and to:
                    item["from"] = frm
                    item["to"] = to
            priority = binding.get("priority")
            if isinstance(priority, str) and priority in {"primary", "secondary"}:
                item["priority"] = priority
            if "quest_monster_id" in item and "binding_type" in item:
                bindings.append(item)
            else:
                filtered_count += 1
        sanitized["quest_monster_bindings"] = bindings

        raw_event_plan = sanitized.get("event_plan") if isinstance(sanitized.get("event_plan"), dict) else {}
        sanitized["event_plan"] = {
            "mandatory": [str(v) for v in raw_event_plan.get("mandatory", []) if isinstance(v, str)][:16],
            "optional": [str(v) for v in raw_event_plan.get("optional", []) if isinstance(v, str)][:16],
            "forbidden": [str(v) for v in raw_event_plan.get("forbidden", []) if isinstance(v, str)][:16],
        }

        raw_progress_plan = sanitized.get("progress_plan") if isinstance(sanitized.get("progress_plan"), dict) else {}
        completion_policy = raw_progress_plan.get("completion_policy")
        if not isinstance(completion_policy, str) or completion_policy not in {"aggregate", "single_target_100", "hybrid"}:
            completion_policy = "aggregate"
        budget = raw_progress_plan.get("budget") if isinstance(raw_progress_plan.get("budget"), dict) else {}
        sanitized["progress_plan"] = {
            "completion_policy": completion_policy,
            "budget": {
                "events": float(budget.get("events", 0.0) or 0.0),
                "quest_monsters": float(budget.get("quest_monsters", 0.0) or 0.0),
                "map_transition": float(budget.get("map_transition", 0.0) or 0.0),
                "exploration_buffer": float(budget.get("exploration_buffer", 0.0) or 0.0),
            },
            "final_objective_id": str(raw_progress_plan.get("final_objective_id", "") or ""),
        }

        key_path = sanitized.get("key_path")
        if not isinstance(key_path, list):
            sanitized["key_path"] = []
        else:
            validated_path = [
                normalize_node_id(k)
                for k in key_path
                if normalize_node_id(k)
            ]
            if len(validated_path) > max_key_path_len:
                filtered_count += len(validated_path) - max_key_path_len
                validated_path = validated_path[:max_key_path_len]
            sanitized["key_path"] = validated_path

        difficulty = sanitized.get("difficulty")
        if not isinstance(difficulty, str) or difficulty not in valid_difficulty:
            sanitized["difficulty"] = "medium"

        cap = sanitized.get("trap_density_cap")
        if isinstance(cap, (float, int)):
            sanitized["trap_density_cap"] = max(0.0, min(0.35, float(cap)))
        else:
            sanitized["trap_density_cap"] = 0.2

        return sanitized, filtered_count

    def _validate_and_fix_blueprint(
        self,
        blueprint: Dict[str, Any],
        room_requirements: Dict[str, Any],
        depth: int,
        generation_contract: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """本地校验与修正：连通性、关键路径、难度/陷阱上限、非法字段过滤。"""
        fixed, filtered_count = self._sanitize_blueprint(blueprint, generation_contract)
        contract = generation_contract if isinstance(generation_contract, dict) else resolve_generation_contract().contract
        report: Dict[str, Any] = {
            "illegal_fields_filtered": filtered_count,
            "fixes": [],
        }

        min_rooms = max(1, int(room_requirements.get("min_rooms", 3)))
        max_rooms = max(min_rooms, int(room_requirements.get("max_rooms", 8)))

        nodes = fixed.get("room_nodes", [])
        if len(nodes) < min_rooms:
            for i in range(min_rooms - len(nodes)):
                nodes.append({"id": f"auto_room_{i}", "role": "normal"})
            report["fixes"].append("补齐最小房间数量")
        if len(nodes) > max_rooms:
            nodes = nodes[:max_rooms]
            report["fixes"].append("截断超额房间数量")

        # 保证id唯一
        seen = set()
        for idx, node in enumerate(nodes):
            nid = node.get("id", f"room_{idx}")
            if nid in seen:
                nid = f"{nid}_{idx}"
                node["id"] = nid
                report["fixes"].append("修复重复房间ID")
            seen.add(nid)

        role_set = {n.get("role") for n in nodes}
        if "entrance" not in role_set and nodes:
            nodes[0]["role"] = "entrance"
            report["fixes"].append("补充入口房间")

        needs_boss = bool(room_requirements.get("needs_boss_room", False)) or depth == config.game.max_quest_floors
        if needs_boss and "boss" not in role_set and nodes:
            nodes[-1]["role"] = "boss"
            report["fixes"].append("补充Boss房间")

        valid_ids = {n.get("id") for n in nodes if isinstance(n.get("id"), str)}
        edges = fixed.get("corridor_edges", [])
        dedup = set()
        filtered_edges = []
        for edge in edges:
            frm = edge.get("from")
            to = edge.get("to")
            if frm not in valid_ids or to not in valid_ids or frm == to:
                continue
            key = tuple(sorted([frm, to]))
            if key in dedup:
                continue
            dedup.add(key)
            filtered_edges.append(edge)

        if not filtered_edges and len(nodes) > 1:
            for i in range(len(nodes) - 1):
                filtered_edges.append({"from": nodes[i]["id"], "to": nodes[i + 1]["id"], "kind": "direct"})
            report["fixes"].append("补充基础连通边")

        adjacency: Dict[str, List[str]] = {nid: [] for nid in valid_ids}
        for edge in filtered_edges:
            a = edge["from"]
            b = edge["to"]
            adjacency[a].append(b)
            adjacency[b].append(a)

        # 连通性修复：将不连通分量串接
        if nodes:
            visited = set()
            components: List[List[str]] = []
            for node in nodes:
                nid = node["id"]
                if nid in visited:
                    continue
                comp = []
                dq = deque([nid])
                visited.add(nid)
                while dq:
                    cur = dq.popleft()
                    comp.append(cur)
                    for nxt in adjacency.get(cur, []):
                        if nxt not in visited:
                            visited.add(nxt)
                            dq.append(nxt)
                components.append(comp)

            if len(components) > 1:
                for i in range(len(components) - 1):
                    a = components[i][0]
                    b = components[i + 1][0]
                    filtered_edges.append({"from": a, "to": b, "kind": "direct"})
                    adjacency[a].append(b)
                    adjacency[b].append(a)
                report["fixes"].append("修复图连通性")

        # 关键路径可达修复
        entrance_id = next((n["id"] for n in nodes if n.get("role") == "entrance"), nodes[0]["id"] if nodes else "")
        target_id = next((n["id"] for n in nodes if n.get("role") == "boss"), "")
        if not target_id and nodes:
            target_id = nodes[-1]["id"]

        def is_reachable(src: str, dst: str) -> bool:
            if not src or not dst:
                return False
            q = deque([src])
            vis = {src}
            while q:
                cur = q.popleft()
                if cur == dst:
                    return True
                for nxt in adjacency.get(cur, []):
                    if nxt not in vis:
                        vis.add(nxt)
                        q.append(nxt)
            return False

        if entrance_id and target_id and not is_reachable(entrance_id, target_id):
            filtered_edges.append({"from": entrance_id, "to": target_id, "kind": "direct"})
            report["fixes"].append("修复关键路径可达")

        key_path = [k for k in fixed.get("key_path", []) if k in valid_ids]
        if len(key_path) < 2 and entrance_id and target_id and entrance_id != target_id:
            key_path = [entrance_id, target_id]
            report["fixes"].append("补充关键路径")

        fixed["room_nodes"] = nodes
        fixed["corridor_edges"] = filtered_edges
        fixed["key_path"] = key_path

        # 难度与陷阱密度上限
        cap = fixed.get("trap_density_cap", 0.2)
        safe_rules = contract.get("safety", {}) if isinstance(contract.get("safety"), dict) else {}
        trap_cap_limit = float(safe_rules.get("trap_density_cap", 0.35) or 0.35)
        fixed["trap_density_cap"] = max(0.0, min(trap_cap_limit, float(cap)))

        return fixed, report

    def _realize_rooms_from_blueprint(
        self,
        width: int,
        height: int,
        room_requirements: Dict[str, Any],
        blueprint: Dict[str, Any],
    ) -> Tuple[List[Dict[str, int]], List[Dict[str, Any]]]:
        """将蓝图房间节点映射为本地坐标房间，并输出落地异常报告。"""
        nodes = blueprint.get("room_nodes", []) if isinstance(blueprint.get("room_nodes"), list) else []
        target_rooms = len(nodes)
        realization_errors: List[Dict[str, Any]] = []

        if target_rooms <= 0:
            return self._generate_rooms_with_quest_context(width, height, room_requirements), realization_errors

        if width < 6 or height < 6:
            rooms = self._generate_rooms_with_quest_context(width, height, room_requirements)
            if not rooms:
                realization_errors.append({"reason": "map_too_small", "node_id": "*"})
                return rooms, realization_errors
            mapped_node = next((n for n in nodes if n.get("role") == "entrance"), nodes[0])
            room = rooms[0]
            room["id"] = mapped_node.get("id", room.get("id", str(uuid.uuid4())))
            room["type"] = mapped_node.get("role", room.get("type", "entrance"))
            room["blueprint_intents"] = {
                "event_intents": mapped_node.get("event_intents", []),
                "monster_intents": mapped_node.get("monster_intents", {}),
                "size": mapped_node.get("size", "small"),
                "placement_policy": mapped_node.get("placement_policy", "center"),
                "must_contain": mapped_node.get("must_contain", []),
                "room_tags": mapped_node.get("room_tags", []),
            }
            return rooms, realization_errors

        base_size = {
            "small": (4, 4),
            "medium": (6, 5),
            "large": (8, 7),
        }

        occupied: List[Dict[str, int]] = []
        rooms: List[Dict[str, int]] = []

        def intersects(candidate: Dict[str, int]) -> bool:
            padding = 1
            cx1 = candidate["x"] - padding
            cy1 = candidate["y"] - padding
            cx2 = candidate["x"] + candidate["width"] + padding
            cy2 = candidate["y"] + candidate["height"] + padding
            for r in occupied:
                rx1 = r["x"]
                ry1 = r["y"]
                rx2 = r["x"] + r["width"]
                ry2 = r["y"] + r["height"]
                if cx1 < rx2 and cx2 > rx1 and cy1 < ry2 and cy2 > ry1:
                    return True
            return False

        def candidate_positions(policy: str, rw: int, rh: int) -> List[Tuple[int, int]]:
            max_x = max(1, width - rw - 1)
            max_y = max(1, height - rh - 1)
            center_x = max(1, min(max_x, (width - rw) // 2))
            center_y = max(1, min(max_y, (height - rh) // 2))
            edge_positions = [
                (1, 1),
                (max_x, 1),
                (1, max_y),
                (max_x, max_y),
                (center_x, 1),
                (center_x, max_y),
                (1, center_y),
                (max_x, center_y),
            ]
            branch_positions = [
                (max(1, center_x - rw - 1), center_y),
                (min(max_x, center_x + rw + 1), center_y),
                (center_x, max(1, center_y - rh - 1)),
                (center_x, min(max_y, center_y + rh + 1)),
            ]

            if policy == "center":
                return [(center_x, center_y)] + branch_positions + edge_positions
            if policy == "edge":
                return edge_positions + [(center_x, center_y)]
            if policy == "branch":
                return branch_positions + edge_positions + [(center_x, center_y)]
            if policy == "corridor_adjacent":
                # corridor_adjacent 在没有走廊信息时退化为 branch + center
                return branch_positions + [(center_x, center_y)] + edge_positions
            return [(center_x, center_y)] + edge_positions

        for idx, node in enumerate(nodes):
            size = node.get("size") if isinstance(node.get("size"), str) else "medium"
            rw, rh = base_size.get(size, base_size["medium"])
            rw = max(3, min(rw, width - 2))
            rh = max(3, min(rh, height - 2))

            policy = node.get("placement_policy") if isinstance(node.get("placement_policy"), str) else "center"
            placed_room: Optional[Dict[str, int]] = None
            for x, y in candidate_positions(policy, rw, rh):
                candidate = {
                    "x": x,
                    "y": y,
                    "width": rw,
                    "height": rh,
                    "id": node.get("id", f"room_{idx}"),
                    "type": node.get("role", "normal"),
                }
                if x + rw >= width or y + rh >= height:
                    continue
                if intersects(candidate):
                    continue
                placed_room = candidate
                break

            if not placed_room:
                fallback_req = dict(room_requirements)
                fallback_req["min_rooms"] = 1
                fallback_req["max_rooms"] = 1
                fallback = self._generate_rooms_with_quest_context(width, height, fallback_req)
                if fallback:
                    placed_room = fallback[0]
                    placed_room["id"] = node.get("id", f"fallback_{idx}")
                    placed_room["type"] = node.get("role", "normal")
                    realization_errors.append(
                        {
                            "node_id": node.get("id", f"room_{idx}"),
                            "reason": "policy_realization_failed_fallback_used",
                            "placement_policy": policy,
                        }
                    )
                else:
                    realization_errors.append(
                        {
                            "node_id": node.get("id", f"room_{idx}"),
                            "reason": "node_realization_failed",
                            "placement_policy": policy,
                        }
                    )
                    continue

            placed_room["blueprint_intents"] = {
                "event_intents": node.get("event_intents", []),
                "monster_intents": node.get("monster_intents", {}),
                "size": size,
                "placement_policy": policy,
                "must_contain": node.get("must_contain", []),
                "room_tags": node.get("room_tags", []),
            }
            occupied.append(placed_room)
            rooms.append(placed_room)

        if not rooms:
            rooms = self._generate_rooms_with_quest_context(width, height, room_requirements)
            realization_errors.append({"node_id": "*", "reason": "all_nodes_failed_global_fallback"})

        return rooms, realization_errors

    def _connect_rooms_from_blueprint(
        self,
        game_map: GameMap,
        rooms: List[Dict[str, int]],
        blueprint: Dict[str, Any],
        requirements: Dict[str, Any],
    ) -> Dict[str, Any]:
        """将蓝图通道边映射到本地通道雕刻函数，并返回连接修复报告。"""
        edges = blueprint.get("corridor_edges", []) if isinstance(blueprint.get("corridor_edges"), list) else []
        room_by_id = {r.get("id"): r for r in rooms if r.get("id")}

        report: Dict[str, Any] = {
            "requested_edges": len(edges),
            "connected_edges": 0,
            "failed_edges": [],
            "repairs": [],
            "style_tags": {
                "risk_level": {},
                "encounter_bias": {},
                "gate_type": {},
            },
        }

        connected_pairs: set = set()
        for edge in edges:
            frm = edge.get("from")
            to = edge.get("to")
            r1 = room_by_id.get(frm)
            r2 = room_by_id.get(to)
            if not r1 or not r2:
                report["failed_edges"].append({"from": frm, "to": to, "reason": "missing_room"})
                continue

            self._connect_two_rooms(game_map, r1, r2)
            pair_key = tuple(sorted([frm, to]))
            connected_pairs.add(pair_key)
            report["connected_edges"] += 1

            risk_level = edge.get("risk_level", "medium")
            encounter_bias = edge.get("encounter_bias", "default")
            gate_type = edge.get("gate_type", "none")
            report["style_tags"]["risk_level"][risk_level] = report["style_tags"]["risk_level"].get(risk_level, 0) + 1
            report["style_tags"]["encounter_bias"][encounter_bias] = report["style_tags"]["encounter_bias"].get(encounter_bias, 0) + 1
            report["style_tags"]["gate_type"][gate_type] = report["style_tags"]["gate_type"].get(gate_type, 0) + 1

        required_min_connections = max(0, len(rooms) - 1)
        if report["connected_edges"] < required_min_connections:
            self._connect_rooms_strategically(game_map, rooms, requirements)
            report["repairs"].append("fallback_connect_rooms_strategically")

        desired = blueprint.get("corridor_ratio", {}) if isinstance(blueprint.get("corridor_ratio"), dict) else {}
        report["corridor_ratio_target"] = {
            "direct": float(desired.get("direct", 0.6) or 0.6),
            "branch": float(desired.get("branch", 0.3) or 0.3),
            "loop": float(desired.get("loop", 0.1) or 0.1),
        }
        report["path_constraints"] = {
            "critical_path_min_length": int(blueprint.get("critical_path_min_length", 0) or 0),
            "branch_complexity_max": int(blueprint.get("branch_complexity_max", 0) or 0),
        }

        return report

    def _build_monster_hints_from_blueprint(
        self,
        game_map: GameMap,
        rooms: List[Dict[str, int]],
        blueprint: Dict[str, Any],
        quest_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """根据房间/通道级怪物意图构建monster_hints，兼容现有GameEngine消费逻辑。"""
        room_by_id = {r.get("id"): r for r in rooms if r.get("id")}
        spawn_points: List[Dict[str, Any]] = []
        encounter_count = 0
        difficulty_order = {"easy": 1, "medium": 2, "hard": 3, "boss": 4}
        chosen_difficulty = "medium"

        for node in blueprint.get("room_nodes", []):
            if not isinstance(node, dict):
                continue
            room = room_by_id.get(node.get("id"))
            if not room:
                continue
            intents = node.get("monster_intents") if isinstance(node.get("monster_intents"), dict) else {}
            count = int(intents.get("count", 0)) if isinstance(intents.get("count", 0), int) else 0
            diff = intents.get("difficulty", "medium") if isinstance(intents.get("difficulty", "medium"), str) else "medium"
            if difficulty_order.get(diff, 2) > difficulty_order.get(chosen_difficulty, 2):
                chosen_difficulty = diff
            if count <= 0:
                continue
            cx = room["x"] + room["width"] // 2
            cy = room["y"] + room["height"] // 2
            tile = game_map.get_tile(cx, cy)
            if tile and tile.terrain in {TerrainType.FLOOR, TerrainType.DOOR, TerrainType.TRAP, TerrainType.TREASURE}:
                spawn_points.append(
                    {
                        "x": cx,
                        "y": cy,
                        "source": "room",
                        "room_id": room.get("id"),
                        "priority": "secondary",
                    }
                )
                encounter_count += count

        for edge in blueprint.get("corridor_edges", []):
            if not isinstance(edge, dict):
                continue
            intents = edge.get("monster_intents") if isinstance(edge.get("monster_intents"), dict) else {}
            count = int(intents.get("count", 0)) if isinstance(intents.get("count", 0), int) else 0
            if count <= 0:
                continue
            r1 = room_by_id.get(edge.get("from"))
            r2 = room_by_id.get(edge.get("to"))
            if not r1 or not r2:
                continue
            x1 = r1["x"] + r1["width"] // 2
            y1 = r1["y"] + r1["height"] // 2
            x2 = r2["x"] + r2["width"] // 2
            y2 = r2["y"] + r2["height"] // 2
            mx = (x1 + x2) // 2
            my = (y1 + y2) // 2
            tile = game_map.get_tile(mx, my)
            if tile and tile.terrain in {TerrainType.FLOOR, TerrainType.DOOR, TerrainType.TRAP, TerrainType.TREASURE}:
                spawn_points.append(
                    {
                        "x": mx,
                        "y": my,
                        "source": "corridor",
                        "edge": [edge.get("from"), edge.get("to")],
                        "priority": "secondary",
                    }
                )
                encounter_count += count

        bindings = blueprint.get("quest_monster_bindings", []) if isinstance(blueprint.get("quest_monster_bindings"), list) else []
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            binding_type = binding.get("binding_type")
            point: Optional[Dict[str, Any]] = None
            if binding_type == "node":
                room = room_by_id.get(binding.get("node_id"))
                if room:
                    point = {
                        "x": room["x"] + room["width"] // 2,
                        "y": room["y"] + room["height"] // 2,
                        "source": "quest_binding_node",
                        "room_id": room.get("id"),
                    }
            elif binding_type == "edge":
                r1 = room_by_id.get(binding.get("from"))
                r2 = room_by_id.get(binding.get("to"))
                if r1 and r2:
                    point = {
                        "x": (r1["x"] + r1["width"] // 2 + r2["x"] + r2["width"] // 2) // 2,
                        "y": (r1["y"] + r1["height"] // 2 + r2["y"] + r2["height"] // 2) // 2,
                        "source": "quest_binding_edge",
                        "edge": [binding.get("from"), binding.get("to")],
                    }

            if point:
                point["quest_monster_id"] = binding.get("quest_monster_id")
                point["priority"] = binding.get("priority", "primary")
                spawn_points.append(point)
                encounter_count += 1

        encounter_count = max(0, min(encounter_count, max(4, len(spawn_points))))

        spawn_audit = {
            "total_spawn_points": len(spawn_points),
            "quest_binding_points": len([p for p in spawn_points if str(p.get("source", "")).startswith("quest_binding")]),
            "primary_points": len([p for p in spawn_points if p.get("priority") == "primary"]),
            "secondary_points": len([p for p in spawn_points if p.get("priority") == "secondary"]),
            "binding_count": len(bindings),
        }

        return {
            "source": "llm_blueprint",
            "spawn_strategy": "llm_generate_by_positions",
            "recommended_player_level": max(1, min(30, 1 + game_map.depth * 2)),
            "encounter_difficulty": blueprint.get("difficulty", chosen_difficulty),
            "encounter_count": encounter_count,
            "boss_count": 1 if any(n.get("role") == "boss" for n in blueprint.get("room_nodes", [])) else 0,
            "spawn_points": spawn_points,
            "spawn_profile": {
                "count": encounter_count,
                "difficulty": blueprint.get("difficulty", chosen_difficulty),
                "distribution_bias": "blueprint_intent",
            },
            "spawn_audit": spawn_audit,
            "llm_context": {
                "quest_type": (quest_context or {}).get("quest_type", "exploration"),
                "map_title": game_map.name,
                "map_depth": game_map.depth,
                "floor_theme": game_map.floor_theme,
                "width": game_map.width,
                "height": game_map.height,
                "blueprint_mode": True,
            },
            "room_intents": [n for n in blueprint.get("room_nodes", []) if isinstance(n, dict)],
            "corridor_intents": [e for e in blueprint.get("corridor_edges", []) if isinstance(e, dict)],
            "quest_monster_bindings": bindings,
        }


    def _build_default_event_payload(self, event_type: str) -> Dict[str, Any]:
        """构建默认事件payload，保持与既有逻辑兼容。"""
        if event_type == "combat":
            return {
                "monster_count": random.randint(1, 3),
                "difficulty": random.choice(["easy", "medium", "hard"]),
            }
        if event_type == "treasure":
            return {
                "treasure_type": random.choice(["gold", "item", "magic_item"]),
                "value": random.randint(50, 500),
            }
        if event_type == "story":
            return {"story_type": random.choice(["discovery", "memory", "vision", "encounter"])}
        if event_type == "trap":
            from trap_schema import trap_validator

            trap_type = random.choice(["damage", "debuff", "teleport"])
            return trap_validator.validate_and_normalize(
                {
                    "trap_type": trap_type,
                    "trap_name": f"{trap_type.capitalize()} Trap",
                    "trap_description": "你发现了一个陷阱！",
                    "detect_dc": random.randint(12, 18),
                    "disarm_dc": random.randint(15, 20),
                    "save_dc": random.randint(12, 16),
                    "damage": random.randint(10, 30) if trap_type == "damage" else 0,
                }
            )
        return {"mystery_type": random.choice(["puzzle", "riddle", "choice"]) }

    def _apply_blueprint_event_intents(
        self,
        game_map: GameMap,
        rooms: List[Dict[str, int]],
        blueprint: Dict[str, Any],
        available_tiles: List[Tuple[int, int]],
    ) -> Dict[str, Any]:
        """应用蓝图中的房间/通道事件意图，并返回放置报告。"""
        report: Dict[str, Any] = {
            "mandatory_requested": 0,
            "mandatory_placed": 0,
            "optional_requested": 0,
            "optional_placed": 0,
            "forbidden_filtered": 0,
            "placements": [],
            "mandatory_reachability_ok": True,
            "difficulty_intent_report": {
                "blueprint_difficulty": str(blueprint.get("difficulty", "medium") or "medium"),
                "mandatory_count": 0,
                "optional_count": 0,
                "actual_placements": 0,
            },
        }

        room_by_id = {r.get("id"): r for r in rooms if r.get("id")}
        corridor_tiles = [
            (x, y)
            for (x, y), tile in game_map.tiles.items()
            if tile.terrain == TerrainType.FLOOR and tile.room_type == "corridor" and not tile.character_id
        ]

        event_plan = blueprint.get("event_plan") if isinstance(blueprint.get("event_plan"), dict) else {}
        mandatory = [str(v) for v in event_plan.get("mandatory", []) if isinstance(v, str)]
        optional = [str(v) for v in event_plan.get("optional", []) if isinstance(v, str)]
        forbidden = {str(v) for v in event_plan.get("forbidden", []) if isinstance(v, str)}

        report["mandatory_requested"] = len(mandatory)
        report["optional_requested"] = len(optional)
        report["difficulty_intent_report"]["mandatory_count"] = len(mandatory)
        report["difficulty_intent_report"]["optional_count"] = len(optional)

        def place_event(x: int, y: int, event_type: str, source: str) -> bool:
            tile = game_map.get_tile(x, y)
            if not tile or event_type in forbidden:
                if event_type in forbidden:
                    report["forbidden_filtered"] += 1
                return False
            tile.has_event = True
            tile.event_type = event_type
            tile.is_event_hidden = True
            tile.event_triggered = False
            tile.event_data = self._build_default_event_payload(event_type)
            report["placements"].append({"x": x, "y": y, "event_type": event_type, "source": source})
            return True

        # mandatory 先放置
        for event_type in mandatory:
            placed = False
            for node in blueprint.get("room_nodes", []):
                if not isinstance(node, dict):
                    continue
                room = room_by_id.get(node.get("id"))
                if not room:
                    continue
                room_tiles = [
                    (x, y)
                    for x in range(room["x"], room["x"] + room["width"])
                    for y in range(room["y"], room["y"] + room["height"])
                    if (x, y) in available_tiles
                ]
                if not room_tiles:
                    continue
                x, y = random.choice(room_tiles)
                if place_event(x, y, event_type, "mandatory_node"):
                    available_tiles.remove((x, y))
                    report["mandatory_placed"] += 1
                    placed = True
                    break
            if not placed:
                report["mandatory_reachability_ok"] = False

        # node/edge intents 作为 optional 处理
        for node in blueprint.get("room_nodes", []):
            if not isinstance(node, dict):
                continue
            intents = node.get("event_intents") if isinstance(node.get("event_intents"), list) else []
            if not intents:
                continue
            room = room_by_id.get(node.get("id"))
            if not room:
                continue
            room_tiles = [
                (x, y)
                for x in range(room["x"], room["x"] + room["width"])
                for y in range(room["y"], room["y"] + room["height"])
                if (x, y) in available_tiles
            ]
            if not room_tiles:
                continue
            event_type = random.choice([et for et in intents if et not in forbidden] or ["mystery"])
            x, y = random.choice(room_tiles)
            if place_event(x, y, event_type, "node_intent"):
                available_tiles.remove((x, y))
                report["optional_placed"] += 1

        for edge in blueprint.get("corridor_edges", []):
            if not isinstance(edge, dict):
                continue
            intents = edge.get("event_intents") if isinstance(edge.get("event_intents"), list) else []
            if not intents:
                continue
            candidates = [p for p in corridor_tiles if p in available_tiles]
            if not candidates:
                continue
            event_type = random.choice([et for et in intents if et not in forbidden] or ["mystery"])
            x, y = random.choice(candidates)
            if place_event(x, y, event_type, "edge_intent"):
                available_tiles.remove((x, y))
                report["optional_placed"] += 1

        # 显式 optional 事件补齐
        for event_type in optional:
            candidates = [p for p in available_tiles]
            if not candidates:
                break
            x, y = random.choice(candidates)
            if place_event(x, y, event_type, "optional_plan"):
                available_tiles.remove((x, y))
                report["optional_placed"] += 1

        report["difficulty_intent_report"]["actual_placements"] = len(report.get("placements", []))
        expected = int(report["difficulty_intent_report"].get("mandatory_count", 0) or 0) + int(report["difficulty_intent_report"].get("optional_count", 0) or 0)
        actual = int(report["difficulty_intent_report"].get("actual_placements", 0) or 0)
        report["difficulty_intent_report"]["placement_deviation"] = abs(actual - expected)
        report["difficulty_intent_report"]["placement_deviation_rate"] = round(abs(actual - expected) / float(max(1, expected)), 6)
        return report


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
        # 计算地图切换进度（n层有n-1次切换）
        map_transition_total = (max_floors - 1) * config.game.map_transition_progress
        # 计算任务目标应该占用的进度（留20%给探索和其他活动）
        objectives_progress_budget = 100.0 - map_transition_total - 20.0

        main_quest_prompt = f"""
        为等级{player_level}的玩家生成1个DnD风格的主线任务，分为{max_floors}个阶段/层级（可地上或地下），每个阶段可在不同场景中推进（如城镇/森林/遗迹/洞穴/雪地/沙漠/农田等）。

        【重要】进度分配规则：
        - 地图切换进度：共{max_floors - 1}次切换，每次{config.game.map_transition_progress}%，共{map_transition_total}%
        - 探索缓冲进度：预留20%给普通战斗、探索等活动
        - **任务目标进度预算：{objectives_progress_budget:.1f}%**（special_events + special_monsters的progress_value总和必须在{objectives_progress_budget * 0.9:.1f}% - {objectives_progress_budget:.1f}%之间）

        任务设计要求：
        1. 任务目标明确，有清晰的故事线
        2. 每层都有相应的子目标和挑战
        3. 专属事件和怪物要与任务主题紧密相关
        4. **严格控制进度值分配，确保总和不超过{objectives_progress_budget:.1f}%**
        5. Boss怪物的progress_value应该在15-25%之间
        6. 每个楼层至少有1个任务目标（事件或怪物）

        请返回JSON格式：
        {{
            "quests": [
                {{
                    "title": "任务标题（中文，简洁有力）",
                    "description": "任务描述（详细说明任务背景和目标，适合分阶段推进）",
                    "objectives": ["第1层：初步探索和准备", "第2层：深入调查", "第{max_floors}层：完成最终目标"],
                    "experience_reward": {500 + player_level * 50},
                    "story_context": "详细的故事背景，包括任务起因、目标和意义",
                    "progress_percentage": 0,
                    "quest_type": "exploration",
                    "target_floors": {list(range(1, max_floors + 1))},
                    "map_themes": ["城镇", "森林", "古老遗迹"],
                    "special_events": [
                        {{
                            "id": "event_1",
                            "event_type": "story",
                            "name": "关键线索发现",
                            "description": "发现与任务目标相关的重要线索或古老文献",
                            "trigger_condition": "探索特定区域",
                            "progress_value": 8.0,
                            "is_mandatory": true,
                            "location_hint": "第1层"
                        }},
                        {{
                            "id": "event_2",
                            "event_type": "mystery",
                            "name": "古老机关",
                            "description": "需要解开的古老机关或谜题，阻挡前进道路",
                            "trigger_condition": "接近关键区域",
                            "progress_value": 10.0,
                            "is_mandatory": true,
                            "location_hint": "第2层"
                        }}
                    ],
                    "special_monsters": [
                        {{
                            "id": "monster_1",
                            "name": "守护哨兵",
                            "description": "保护入口的古老守护者",
                            "challenge_rating": {player_level * 0.8},
                            "is_boss": false,
                            "progress_value": 8.0,
                            "spawn_condition": "进入特定区域时",
                            "location_hint": "第1层的关键通道"
                        }},
                        {{
                            "id": "monster_2",
                            "name": "中层守卫",
                            "description": "守护重要区域的强大敌人",
                            "challenge_rating": {player_level * 0.9},
                            "is_boss": false,
                            "progress_value": 6.0,
                            "spawn_condition": "探索第2层时",
                            "location_hint": "第2层的核心区域"
                        }},
                        {{
                            "id": "monster_3",
                            "name": "任务终极Boss",
                            "description": "任务的最终敌人，拥有强大力量",
                            "challenge_rating": {player_level + 1.0},
                            "is_boss": true,
                            "progress_value": 20.0,
                            "spawn_condition": "玩家接近任务目标时",
                            "location_hint": "第{max_floors}层的核心区域"
                        }}
                    ]
                }}
            ]
        }}

        **进度值检查**：
        - 示例中special_events总和：8.0 + 10.0 = 18.0%
        - 示例中special_monsters总和：8.0 + 6.0 + 20.0 = 34.0%
        - 示例总计：18.0 + 34.0 = 52.0%（符合{objectives_progress_budget:.1f}%预算）
        - 加上地图切换{map_transition_total}%和探索20% = 52.0 + {map_transition_total} + 20.0 = {52.0 + map_transition_total + 20.0}%

        重要提示：
        - **必须严格控制progress_value总和，不要超过{objectives_progress_budget:.1f}%**
        - 每个楼层都应该有相应的挑战和奖励
        - Boss的progress_value应该是最高的，但不要超过25%
        - 任务描述要生动有趣，符合DnD风格
        """

        try:
            # 导入验证器
            from quest_progress_validator import quest_progress_validator

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
                    quest.map_themes = quest_data.get("map_themes", ["城镇", "森林", "遗迹", "洞穴", "雪地", "沙漠", "农田"])

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

                    # 【新增】验证和调整任务进度分配
                    validation_result = quest_progress_validator.validate_quest(quest)

                    if not validation_result.is_valid or len(validation_result.warnings) > 0:
                        logger.warning(f"Quest '{quest.title}' progress validation issues:")
                        for issue in validation_result.issues:
                            logger.warning(f"  - ISSUE: {issue}")
                        for warning in validation_result.warnings:
                            logger.warning(f"  - WARNING: {warning}")

                        logger.info(f"Progress breakdown: {validation_result.breakdown.to_dict()}")

                        # 自动调整进度分配
                        quest, adjusted_validation = quest_progress_validator.auto_adjust_quest(quest)
                        logger.info(f"Quest '{quest.title}' progress adjusted:")
                        logger.info(f"  - Guaranteed: {adjusted_validation.breakdown.total_guaranteed:.1f}%")
                        logger.info(f"  - Possible: {adjusted_validation.breakdown.total_possible:.1f}%")
                    else:
                        logger.info(f"Quest '{quest.title}' progress allocation is valid:")
                        logger.info(f"  - Guaranteed: {validation_result.breakdown.total_guaranteed:.1f}%")
                        logger.info(f"  - Possible: {validation_result.breakdown.total_possible:.1f}%")

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

    async def _generate_map_events(
        self,
        game_map: GameMap,
        rooms: List[Dict[str, int]],
        quest_context: Optional[Dict[str, Any]] = None,
        blueprint: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """为地图生成事件（支持蓝图房间/通道级意图），并返回事件放置报告。"""
        safe_blueprint = blueprint if isinstance(blueprint, dict) else None
        floor_tiles = [(x, y) for (x, y), tile in game_map.tiles.items()
                      if tile.terrain == TerrainType.FLOOR and not tile.character_id]

        report: Dict[str, Any] = {
            "blueprint": {
                "mandatory_requested": 0,
                "mandatory_placed": 0,
                "optional_requested": 0,
                "optional_placed": 0,
                "forbidden_filtered": 0,
                "placements": [],
                "mandatory_reachability_ok": True,
            },
            "quest_events_placed": 0,
            "normal_events_placed": 0,
            "trap_overflow_replaced": 0,
            "trap_cap": 0.35,
        }

        if not floor_tiles:
            return report

        initial_floor_count = len(floor_tiles)

        # 优先放置蓝图事件意图
        quest_events_placed = 0
        if isinstance(safe_blueprint, dict):
            blueprint_report = self._apply_blueprint_event_intents(game_map, rooms, safe_blueprint, floor_tiles)
            report["blueprint"] = blueprint_report
            quest_events_placed += blueprint_report.get("mandatory_placed", 0)
            quest_events_placed += blueprint_report.get("optional_placed", 0)

        # 再放置任务专属事件
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
                        tile.is_event_hidden = True
                        tile.event_triggered = False
                        tile.event_data = {
                            'quest_event_id': event_data.get('id'),
                            'name': event_data.get('name'),
                            'description': event_data.get('description'),
                            'progress_value': event_data.get('progress_value', 0.0),
                            'is_mandatory': event_data.get('is_mandatory', True)
                        }
                        quest_events_placed += 1

        report["quest_events_placed"] = quest_events_placed

        # 计算普通事件数量（以初始可用地板为基数，避免双重扣减）
        total_tiles = len(floor_tiles)
        normal_event_count = max(2, initial_floor_count // 20) - quest_events_placed

        # 蓝图陷阱密度安全上限
        trap_cap = 0.35
        if isinstance(safe_blueprint, dict):
            cap_value = safe_blueprint.get("trap_density_cap", 0.2)
            if isinstance(cap_value, (float, int)):
                trap_cap = max(0.0, min(0.35, float(cap_value)))

        report["trap_cap"] = trap_cap

        max_trap_events = max(1, int(total_tiles * trap_cap))
        current_trap_events = sum(
            1
            for _, t in game_map.tiles.items()
            if t.has_event and t.event_type == "trap"
        )

        if current_trap_events > max_trap_events:
            overflow = current_trap_events - max_trap_events
            trap_tiles = [
                tile
                for tile in game_map.tiles.values()
                if tile.has_event and tile.event_type == "trap"
            ]
            random.shuffle(trap_tiles)
            for tile in trap_tiles[:overflow]:
                tile.event_type = "mystery"
                tile.event_data = self._build_default_event_payload("mystery")
            current_trap_events = max_trap_events
            report["trap_overflow_replaced"] = overflow

        normal_events_placed = 0
        if normal_event_count > 0 and floor_tiles:
            event_positions = random.sample(floor_tiles, min(normal_event_count, len(floor_tiles)))

            for x, y in event_positions:
                tile = game_map.get_tile(x, y)
                if not tile:
                    continue

                event_types = ["combat", "treasure", "story", "trap", "mystery"]
                if current_trap_events >= max_trap_events:
                    event_types = [et for et in event_types if et != "trap"]
                event_type = random.choice(event_types)
                if event_type == "trap":
                    current_trap_events += 1

                tile.has_event = True
                tile.event_type = event_type
                tile.is_event_hidden = random.choice([True, True, False])
                tile.event_triggered = False
                tile.event_data = self._build_default_event_payload(event_type)
                normal_events_placed += 1

        report["normal_events_placed"] = normal_events_placed
        return report

    def _reset_map_tiles_to_walls(self, game_map: GameMap) -> None:
        """将地图重置为全墙，确保失败回退路径从干净状态开始。"""
        game_map.tiles.clear()
        for x in range(game_map.width):
            for y in range(game_map.height):
                game_map.tiles[(x, y)] = MapTile(x=x, y=y, terrain=TerrainType.WALL)

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
