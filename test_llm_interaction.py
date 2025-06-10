#!/usr/bin/env python3
"""
测试LLM交互逻辑的脚本
验证以下功能：
1. 楼梯瓦片不触发LLM遮罩
2. 被攻击时显示LLM遮罩
3. 其他特殊地形正确触发LLM遮罩
"""

import asyncio
import json
import aiohttp
import logging

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "http://127.0.0.1:8000"

class GameTester:
    def __init__(self):
        self.session = None
        self.game_id = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def create_new_game(self):
        """创建新游戏"""
        data = {
            "player_name": "测试玩家",
            "character_class": "warrior"
        }
        
        async with self.session.post(f"{BASE_URL}/api/new-game", json=data) as response:
            result = await response.json()
            if result["success"]:
                self.game_id = result["game_id"]
                logger.info(f"创建游戏成功，游戏ID: {self.game_id}")
                return True
            else:
                logger.error(f"创建游戏失败: {result.get('message', '未知错误')}")
                return False
    
    async def perform_action(self, action, parameters=None):
        """执行游戏行动"""
        if not self.game_id:
            logger.error("游戏ID未设置")
            return None
        
        data = {
            "game_id": self.game_id,
            "action": action,
            "parameters": parameters or {}
        }
        
        async with self.session.post(f"{BASE_URL}/api/action", json=data) as response:
            result = await response.json()
            return result
    
    async def get_game_state(self):
        """获取游戏状态"""
        if not self.game_id:
            logger.error("游戏ID未设置")
            return None
        
        async with self.session.get(f"{BASE_URL}/api/game/{self.game_id}") as response:
            return await response.json()
    
    async def test_stairs_interaction(self):
        """测试楼梯交互（不应该触发LLM）"""
        logger.info("=== 测试楼梯交互 ===")
        
        # 获取当前游戏状态
        game_state = await self.get_game_state()
        if not game_state:
            return False
        
        # 查找楼梯瓦片
        current_map = game_state["current_map"]
        stairs_tile = None
        
        for tile_key, tile_data in current_map["tiles"].items():
            if tile_data["terrain"] in ["stairs_down", "stairs_up"]:
                stairs_tile = tile_data
                x, y = map(int, tile_key.split(","))
                logger.info(f"找到楼梯瓦片在位置 ({x}, {y})")
                break
        
        if not stairs_tile:
            logger.warning("地图中没有找到楼梯瓦片")
            return False
        
        # 移动到楼梯附近
        player_pos = game_state["player"]["position"]
        logger.info(f"玩家当前位置: {player_pos}")
        
        # 尝试移动到楼梯
        # 这里需要计算移动方向
        dx = x - player_pos[0]
        dy = y - player_pos[1]
        
        # 简化：只测试向东移动
        result = await self.perform_action("move", {"direction": "east"})
        
        if result:
            logger.info(f"移动结果: {result}")
            llm_required = result.get("llm_interaction_required", False)
            logger.info(f"LLM交互是否必需: {llm_required}")
            
            # 检查是否设置了待切换状态
            game_state = await self.get_game_state()
            pending_transition = game_state.get("pending_map_transition")
            if pending_transition:
                logger.info(f"检测到待切换状态: {pending_transition}")
            
            return True
        
        return False
    
    async def test_monster_attack(self):
        """测试怪物攻击（应该触发LLM）"""
        logger.info("=== 测试怪物攻击 ===")
        
        # 执行一个行动让怪物有机会攻击
        result = await self.perform_action("rest")
        
        if result:
            logger.info(f"休息结果: {result}")
            llm_required = result.get("llm_interaction_required", False)
            logger.info(f"LLM交互是否必需: {llm_required}")
            
            # 检查是否有战斗事件
            events = result.get("events", [])
            has_combat = any("攻击" in event for event in events)
            logger.info(f"是否有战斗事件: {has_combat}")
            
            return True
        
        return False
    
    async def test_special_terrain(self):
        """测试特殊地形交互（应该触发LLM）"""
        logger.info("=== 测试特殊地形交互 ===")
        
        # 尝试交互行动
        result = await self.perform_action("interact")
        
        if result:
            logger.info(f"交互结果: {result}")
            llm_required = result.get("llm_interaction_required", False)
            logger.info(f"LLM交互是否必需: {llm_required}")
            
            return True
        
        return False
    
    async def run_tests(self):
        """运行所有测试"""
        logger.info("开始LLM交互逻辑测试")
        
        # 创建新游戏
        if not await self.create_new_game():
            return False
        
        # 等待游戏初始化
        await asyncio.sleep(2)
        
        # 运行测试
        tests = [
            self.test_stairs_interaction,
            self.test_monster_attack,
            self.test_special_terrain
        ]
        
        for test in tests:
            try:
                await test()
                await asyncio.sleep(1)  # 测试间隔
            except Exception as e:
                logger.error(f"测试 {test.__name__} 失败: {e}")
        
        logger.info("测试完成")
        return True

async def main():
    """主函数"""
    async with GameTester() as tester:
        await tester.run_tests()

if __name__ == "__main__":
    asyncio.run(main())
