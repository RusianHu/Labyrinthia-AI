// Labyrinthia AI - 本地游戏引擎
// 在前端处理基础游戏逻辑，减少不必要的后端请求

class LocalGameEngine {
    constructor(game) {
        this.game = game; // 引用主游戏对象
        this.syncInterval = 10; // 每10回合同步一次到后端
        this.lastSyncTurn = 0;
    }

    // ==================== 工具方法 ====================

    /**
     * 获取游戏状态
     */
    getGameState() {
        return this.game.gameState;
    }

    /**
     * 获取地图瓦片
     */
    getTile(x, y) {
        const gameState = this.getGameState();
        if (!gameState || !gameState.current_map) return null;
        
        const tileKey = `${x},${y}`;
        return gameState.current_map.tiles[tileKey];
    }

    /**
     * 计算两点之间的切比雪夫距离
     */
    calculateDistance(pos1, pos2) {
        return Math.max(
            Math.abs(pos1[0] - pos2[0]),
            Math.abs(pos1[1] - pos2[1])
        );
    }

    /**
     * 查找怪物
     */
    findMonster(monsterId) {
        const gameState = this.getGameState();
        return gameState.monsters.find(m => m.id === monsterId);
    }

    /**
     * 获取属性调整值
     */
    getAbilityModifier(abilityScore) {
        return Math.floor((abilityScore - 10) / 2);
    }

    /**
     * 随机整数
     */
    randomInt(min, max) {
        return Math.floor(Math.random() * (max - min + 1)) + min;
    }

    /**
     * 添加消息到消息栏
     */
    addMessage(message, type = 'info') {
        this.game.addMessage(message, type);
    }

    // ==================== 位置和移动验证 ====================

    /**
     * 检查是否可以移动到指定位置
     */
    canMoveTo(x, y) {
        const gameState = this.getGameState();
        if (!gameState) return false;

        const map = gameState.current_map;

        // 检查边界
        if (x < 0 || x >= map.width || y < 0 || y >= map.height) {
            return false;
        }

        // 检查瓦片
        const tile = this.getTile(x, y);
        if (!tile) return false;

        // 检查地形
        if (tile.terrain === 'wall') {
            return false;
        }

        // 检查是否有其他角色
        if (tile.character_id && tile.character_id !== gameState.player.id) {
            return false;
        }

        return true;
    }

    /**
     * 根据方向计算新位置
     */
    calculateNewPosition(direction) {
        const gameState = this.getGameState();
        const currentPos = gameState.player.position;

        const directionMap = {
            "north": [0, -1], "south": [0, 1],
            "east": [1, 0], "west": [-1, 0],
            "northeast": [1, -1], "northwest": [-1, -1],
            "southeast": [1, 1], "southwest": [-1, 1]
        };

        const offset = directionMap[direction];
        if (!offset) return null;

        return {
            x: currentPos[0] + offset[0],
            y: currentPos[1] + offset[1]
        };
    }

    // ==================== 视野更新 ====================

    /**
     * 更新可见性
     */
    updateVisibility(centerX, centerY, radius = 2) {
        const gameState = this.getGameState();
        if (!gameState) return;

        for (let dx = -radius; dx <= radius; dx++) {
            for (let dy = -radius; dy <= radius; dy++) {
                const x = centerX + dx;
                const y = centerY + dy;
                const tile = this.getTile(x, y);
                
                if (tile) {
                    tile.is_visible = true;
                    // 相邻瓦片标记为已探索
                    if (Math.abs(dx) + Math.abs(dy) <= 1) {
                        tile.is_explored = true;
                    }
                }
            }
        }
    }

    // ==================== 伤害计算 ====================

    /**
     * 计算伤害
     */
    calculateDamage(attacker, defender) {
        const strengthMod = this.getAbilityModifier(attacker.abilities.strength);
        const baseDamage = 10 + strengthMod;

        // 添加随机性
        const damage = this.randomInt(
            Math.max(1, baseDamage - 3),
            baseDamage + 3
        );

        // 护甲减免
        const armorReduction = Math.max(0, defender.stats.ac - 10);
        return Math.max(1, damage - armorReduction);
    }

    // ==================== 经验值和升级 ====================

    /**
     * 检查升级
     */
    checkLevelUp(character) {
        const requiredExp = character.stats.level * 1000;
        if (character.stats.experience >= requiredExp) {
            character.stats.level++;
            character.stats.max_hp += 10;
            character.stats.hp = character.stats.max_hp;
            character.stats.max_mp += 5;
            character.stats.mp = character.stats.max_mp;
            return true;
        }
        return false;
    }

    // ==================== 状态同步 ====================

    /**
     * 检查是否需要同步到后端
     */
    shouldSync() {
        const gameState = this.getGameState();
        return (gameState.turn_count - this.lastSyncTurn) >= this.syncInterval;
    }

    /**
     * 同步游戏状态到后端
     */
    async syncToBackend() {
        const gameState = this.getGameState();
        if (!gameState || !this.game.gameId) return;

        try {
            await fetch('/api/sync-state', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    game_id: this.game.gameId,
                    game_state: gameState
                })
            });

            this.lastSyncTurn = gameState.turn_count;
            console.log(`[LocalGameEngine] 状态已同步到后端 (回合 ${gameState.turn_count})`);
        } catch (error) {
            console.error('[LocalGameEngine] 同步状态失败:', error);
        }
    }

    // ==================== 事件判断 ====================

    /**
     * 判断是否需要后端LLM处理
     */
    needsBackendProcessing(tile) {
        if (!tile) return false;

        // 陷阱和宝藏现在由前端本地处理，不需要后端
        // 只有未触发的事件需要LLM处理
        if (tile.has_event && !tile.event_triggered) {
            return true;
        }

        return false;
    }

    /**
     * 处理陷阱（前端计算效果，后端生成描述）
     */
    async handleTrap(tile) {
        const gameState = this.getGameState();
        const player = gameState.player;
        const eventData = tile.event_data || {};
        const trapType = eventData.trap_type || 'damage';
        const damage = eventData.damage || 15;

        // 前端先计算陷阱效果
        let trapResult = {
            type: trapType,
            damage: 0,
            teleported: false,
            newPosition: null,
            playerDied: false
        };

        if (trapType === 'damage') {
            player.stats.hp -= damage;
            trapResult.damage = damage;
            this.addMessage(`触发了陷阱！受到了 ${damage} 点伤害！`, 'combat');

            // 检查玩家是否死亡
            if (player.stats.hp <= 0) {
                this.addMessage('你被陷阱杀死了！游戏结束！', 'error');
                gameState.is_game_over = true;
                gameState.game_over_reason = '被陷阱杀死';
                trapResult.playerDied = true;
                if (this.game.handleGameOver) {
                    this.game.handleGameOver(gameState.game_over_reason);
                }
            }
        } else if (trapType === 'debuff') {
            this.addMessage('触发了减速陷阱！移动变得困难！', 'system');
            // TODO: 实现减速效果
        } else if (trapType === 'teleport') {
            // 随机传送
            const randomX = this.randomInt(0, gameState.current_map.width - 1);
            const randomY = this.randomInt(0, gameState.current_map.height - 1);
            const targetTile = this.getTile(randomX, randomY);

            if (targetTile && targetTile.terrain !== 'wall' && !targetTile.character_id) {
                this.updatePlayerPosition(randomX, randomY);
                this.updateVisibility(randomX, randomY);
                trapResult.teleported = true;
                trapResult.newPosition = [randomX, randomY];
                this.addMessage(`触发了传送陷阱！被传送到了 (${randomX}, ${randomY})！`, 'system');
            } else {
                this.addMessage('触发了传送陷阱，但传送失败了！', 'system');
            }
        }

        // 调用后端生成描述性文本（可选，增强体验）
        if (!trapResult.playerDied) {
            await this.triggerBackendEvent('trap_narrative', {
                tile: tile,
                position: [tile.x, tile.y],
                trap_result: trapResult
            });

            // 【修复】处理怪物回合（triggerBackendEvent已经更新了UI）
            await this.processMonsterTurns();

            // 【修复】检查是否需要同步
            if (this.shouldSync()) {
                await this.syncToBackend();
            }
        } else {
            // 玩家死亡，只更新UI显示游戏结束状态
            this.game.updateUI();
        }
    }

    /**
     * 处理宝藏（前端本地处理，但物品生成需要后端LLM）
     */
    async handleTreasure(tile) {
        // 宝藏物品生成需要LLM，所以还是要调用后端
        await this.triggerBackendEvent('treasure', {
            tile: tile,
            position: [tile.x, tile.y]
        });

        // 宝藏被发现后变为地板
        tile.terrain = 'floor';

        // 【修复】处理怪物回合（triggerBackendEvent已经更新了UI）
        await this.processMonsterTurns();

        // 【修复】检查是否需要同步
        if (this.shouldSync()) {
            await this.syncToBackend();
        }
    }

    /**
     * 触发后端事件
     */
    async triggerBackendEvent(eventType, eventData) {
        console.log('[LocalGameEngine] Triggering backend event:', eventType);

        // 显示LLM遮罩
        this.game.showLLMOverlay(eventType);

        try {
            const response = await fetch('/api/llm-event', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    game_id: this.game.gameId,
                    event_type: eventType,
                    event_data: eventData,
                    game_state: this.getGameState()
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const result = await response.json();

            if (result.success) {
                // 应用后端返回的更新
                this.applyBackendUpdates(result);
            } else {
                this.addMessage(result.message || '事件处理失败', 'error');
            }
        } catch (error) {
            console.error('[LocalGameEngine] 后端事件处理失败:', error);
            this.addMessage('网络错误，请重试', 'error');
        } finally {
            // 确保隐藏遮罩
            this.game.hideLLMOverlay();
        }
    }

    /**
     * 应用后端返回的更新
     */
    applyBackendUpdates(result) {
        console.log('[LocalGameEngine] Applying backend updates:', result);

        // 显示消息
        if (result.message) {
            this.addMessage(result.message, 'action');
        }

        if (result.events) {
            result.events.forEach(event => {
                this.addMessage(event, 'system');
            });
        }

        if (result.narrative) {
            this.addMessage(result.narrative, 'narrative');
        }

        // 更新游戏状态
        if (result.game_state) {
            // 使用updateGameState会自动检查pending_choice_context
            this.game.updateGameState(result.game_state);
        } else {
            // 只刷新UI
            this.game.updateUI();
        }
    }

    // ==================== 玩家移动 ====================

    /**
     * 更新玩家位置
     */
    updatePlayerPosition(newX, newY) {
        const gameState = this.getGameState();
        const player = gameState.player;
        const oldPos = player.position;

        // 清除旧位置的角色标记
        const oldTile = this.getTile(oldPos[0], oldPos[1]);
        if (oldTile) {
            oldTile.character_id = null;
        }

        // 设置新位置
        const newTile = this.getTile(newX, newY);
        if (newTile) {
            newTile.character_id = player.id;
            newTile.is_explored = true;
            newTile.is_visible = true;
        }

        // 更新玩家位置
        player.position = [newX, newY];
    }

    /**
     * 处理玩家移动
     */
    async movePlayer(direction) {
        const gameState = this.getGameState();
        if (!gameState) return;

        console.log('[LocalGameEngine] Moving player:', direction);

        // 计算新位置
        const newPos = this.calculateNewPosition(direction);
        if (!newPos) {
            this.addMessage('无效的移动方向', 'error');
            return;
        }

        // 验证移动
        if (!this.canMoveTo(newPos.x, newPos.y)) {
            const tile = this.getTile(newPos.x, newPos.y);
            if (tile && tile.terrain === 'wall') {
                this.addMessage('无法穿过墙壁', 'error');
            } else if (tile && tile.character_id) {
                const monster = this.findMonster(tile.character_id);
                if (monster) {
                    this.addMessage(`该位置有 ${monster.name}，请使用攻击命令`, 'error');
                } else {
                    this.addMessage('该位置已被占据', 'error');
                }
            } else {
                this.addMessage('无法移动到该位置', 'error');
            }
            return;
        }

        // 检查目标瓦片
        const targetTile = this.getTile(newPos.x, newPos.y);

        // 检查是否需要后端处理（在移动前检查，以便正确显示遮罩）
        const needsBackend = this.needsBackendProcessing(targetTile);

        if (needsBackend) {
            console.log('[LocalGameEngine] Tile needs backend processing, showing overlay');
        }

        // 执行移动
        this.updatePlayerPosition(newPos.x, newPos.y);
        this.updateVisibility(newPos.x, newPos.y);

        // 增加回合数
        gameState.turn_count++;
        gameState.game_time++;

        // 显示移动消息
        this.addMessage(`移动到 (${newPos.x}, ${newPos.y})`, 'action');

        // 检查特殊地形（前端本地处理）
        if (targetTile.terrain === 'trap') {
            // 陷阱由前端本地处理
            await this.handleTrap(targetTile);
            // handleTrap内部调用triggerBackendEvent，已经更新了UI
            // 不需要继续处理
            return;
        } else if (targetTile.terrain === 'treasure') {
            // 宝藏需要LLM生成物品
            await this.handleTreasure(targetTile);
            // handleTreasure内部调用triggerBackendEvent，已经更新了UI
            // 不需要继续处理
            return;
        } else if (needsBackend) {
            // 需要LLM处理的事件
            await this.triggerBackendEvent('tile_event', {
                tile: targetTile,
                position: [newPos.x, newPos.y]
            });
            // triggerBackendEvent已经更新了UI，不需要继续处理
            return;
        } else {
            // 检查楼梯（前端本地处理）
            if (targetTile.terrain === 'stairs_down') {
                gameState.pending_map_transition = 'stairs_down';
                this.addMessage('你发现了通往下一层的楼梯。你可以选择进入下一层。', 'system');
                console.log('[LocalGameEngine] Set pending_map_transition to stairs_down');
            } else if (targetTile.terrain === 'stairs_up') {
                gameState.pending_map_transition = 'stairs_up';
                this.addMessage('你发现了通往上一层的楼梯。你可以选择返回上一层。', 'system');
                console.log('[LocalGameEngine] Set pending_map_transition to stairs_up');
            } else {
                // 离开楼梯时清除待切换标志
                if (gameState.pending_map_transition) {
                    console.log('[LocalGameEngine] Clearing pending_map_transition (left stairs)');
                    gameState.pending_map_transition = null;
                }
            }

            // 本地处理怪物回合
            await this.processMonsterTurns();

            // 【修复】只在普通移动时更新UI（陷阱、宝藏、后端事件都已经在各自的处理函数中更新了UI）
            this.game.updateUI();

            // 检查是否需要同步
            if (this.shouldSync()) {
                await this.syncToBackend();
            }

            // 回合制游戏：移动后检查是否有待处理的选择
            if (window.eventChoiceManager) {
                window.eventChoiceManager.checkAfterPlayerAction();
            }
        }
    }

    // ==================== 怪物AI系统 ====================

    /**
     * 移动怪物靠近玩家
     */
    moveMonsterTowardsPlayer(monster) {
        const gameState = this.getGameState();
        const playerPos = gameState.player.position;
        const monsterPos = monster.position;

        // 简单的寻路：朝玩家方向移动一格
        const dx = playerPos[0] === monsterPos[0] ? 0 :
                   (playerPos[0] > monsterPos[0] ? 1 : -1);
        const dy = playerPos[1] === monsterPos[1] ? 0 :
                   (playerPos[1] > monsterPos[1] ? 1 : -1);

        const newX = monsterPos[0] + dx;
        const newY = monsterPos[1] + dy;

        // 检查新位置是否有效
        const targetTile = this.getTile(newX, newY);
        if (targetTile &&
            targetTile.terrain !== 'wall' &&
            !targetTile.character_id) {

            // 移动怪物
            const oldTile = this.getTile(monsterPos[0], monsterPos[1]);
            if (oldTile) {
                oldTile.character_id = null;
            }

            targetTile.character_id = monster.id;
            monster.position = [newX, newY];
        }
    }

    /**
     * 怪物攻击玩家
     */
    monsterAttackPlayer(monster) {
        const gameState = this.getGameState();
        const player = gameState.player;

        // 计算伤害
        const damage = this.calculateDamage(monster, player);
        player.stats.hp -= damage;

        this.addMessage(`${monster.name} 攻击了你，造成 ${damage} 点伤害！`, 'combat');

        // 检查玩家是否死亡
        if (player.stats.hp <= 0) {
            this.addMessage('你被击败了！游戏结束！', 'error');
            gameState.is_game_over = true;
            gameState.game_over_reason = '被怪物击败';

            // 触发游戏结束处理
            if (this.game.handleGameOver) {
                this.game.handleGameOver(gameState.game_over_reason);
            }
        }
    }

    /**
     * 处理怪物回合
     */
    async processMonsterTurns() {
        const gameState = this.getGameState();
        if (!gameState || gameState.is_game_over) return;

        const monsters = gameState.monsters.slice(); // 复制数组避免修改问题

        for (const monster of monsters) {
            // 检查怪物是否存活
            if (!monster.stats || monster.stats.hp <= 0) continue;

            // 计算与玩家的距离
            const distance = this.calculateDistance(
                monster.position,
                gameState.player.position
            );

            // 获取怪物攻击范围
            const attackRange = monster.attack_range || 1;

            if (distance <= attackRange) {
                // 在攻击范围内，攻击玩家
                this.monsterAttackPlayer(monster);

                // 如果玩家死亡，停止处理其他怪物
                if (gameState.is_game_over) {
                    break;
                }
            } else if (distance <= 5) {
                // 在视野范围内，移动靠近玩家
                this.moveMonsterTowardsPlayer(monster);
            }
        }
    }

    // ==================== 战斗系统 ====================

    /**
     * 处理怪物死亡
     */
    async handleMonsterDeath(monster, damageDealt = 0) {
        const gameState = this.getGameState();
        const player = gameState.player;

        console.log('[LocalGameEngine] Processing monster death:', monster.name);

        // 【修复】检查怪物是否已经被处理过
        const monsterIndex = gameState.monsters.findIndex(m => m.id === monster.id);
        if (monsterIndex === -1) {
            console.warn('[LocalGameEngine] Monster already removed:', monster.id);
            return; // 怪物已经被移除，直接返回
        }

        // 【重要】标记怪物为"正在处理"，防止重复处理
        if (monster._processing) {
            console.warn('[LocalGameEngine] Monster already being processed:', monster.id);
            return;
        }
        monster._processing = true;

        // 显示LLM遮罩，准备生成战斗叙述
        this.game.showLLMOverlay('combat_victory');

        try {
            // 【重要】先调用后端战斗结果管理器（此时怪物还在列表中）
            const response = await fetch(`/api/game/${gameState.id}/combat-result`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    monster_id: monster.id,
                    damage_dealt: damageDealt
                })
            });

            if (!response.ok) {
                throw new Error('Failed to process combat result');
            }

            const combatResult = await response.json();
            console.log('[LocalGameEngine] Combat result:', combatResult);

            // 应用战斗结果到本地状态
            if (combatResult.experience_gained) {
                player.stats.experience += combatResult.experience_gained;
            }

            // 添加战利品到背包
            if (combatResult.loot_items && combatResult.loot_items.length > 0) {
                for (const item of combatResult.loot_items) {
                    player.inventory.push(item);
                }
            }

            // 显示战斗事件
            if (combatResult.events && combatResult.events.length > 0) {
                for (const event of combatResult.events) {
                    this.addMessage(event, 'combat');
                }
            }

            // 显示LLM生成的战斗叙述
            if (combatResult.narrative) {
                this.addMessage(combatResult.narrative, 'narrative');
            }

            // 检查升级（前端也检查一次，确保UI更新）
            if (combatResult.level_up) {
                this.checkLevelUp(player);
            }

            // 【修复】不在这里更新UI，等到finally块中统一更新
            // this.game.updateUI(); // 移除这里的UI更新

        } catch (error) {
            console.error('[LocalGameEngine] Error processing monster death:', error);

            // 降级处理：使用本地逻辑
            this.addMessage(`${monster.name} 被击败了！`, 'combat');

            // 获得经验值
            const expGain = Math.floor(monster.challenge_rating * 100);
            player.stats.experience += expGain;
            this.addMessage(`获得了 ${expGain} 点经验`, 'system');

            // 检查升级
            if (this.checkLevelUp(player)) {
                this.addMessage('恭喜升级！', 'success');
            }
        } finally {
            // 【重要】现在才从怪物列表中移除（无论成功还是失败）
            const finalIndex = gameState.monsters.findIndex(m => m.id === monster.id);
            if (finalIndex !== -1) {
                gameState.monsters.splice(finalIndex, 1);
            }

            // 清除地图上的怪物标记
            const tile = this.getTile(monster.position[0], monster.position[1]);
            if (tile) {
                tile.character_id = null;
            }

            // 隐藏LLM遮罩
            this.game.hideLLMOverlay();

            // 【修复】只在这里更新一次UI，此时怪物已经被正确移除
            this.game.updateUI();

            // 同步状态到后端
            await this.syncToBackend();
        }
    }

    /**
     * 检查视线
     */
    hasLineOfSight(x1, y1, x2, y2) {
        // 简单实现：检查是否有墙壁阻挡
        const dx = Math.abs(x2 - x1);
        const dy = Math.abs(y2 - y1);
        const sx = x1 < x2 ? 1 : -1;
        const sy = y1 < y2 ? 1 : -1;
        let err = dx - dy;

        let x = x1;
        let y = y1;

        while (true) {
            if (x === x2 && y === y2) break;

            const tile = this.getTile(x, y);
            if (tile && tile.terrain === 'wall') {
                return false;
            }

            const e2 = 2 * err;
            if (e2 > -dy) {
                err -= dy;
                x += sx;
            }
            if (e2 < dx) {
                err += dx;
                y += sy;
            }
        }

        return true;
    }

    /**
     * 攻击怪物
     */
    async attackMonster(monsterId) {
        const gameState = this.getGameState();
        const player = gameState.player;
        const monster = this.findMonster(monsterId);

        console.log('[LocalGameEngine] Attacking monster:', monsterId);

        if (!monster) {
            this.addMessage('目标未找到', 'error');
            return;
        }

        // 检查距离
        const distance = this.calculateDistance(player.position, monster.position);
        if (distance > 1) {
            this.addMessage('目标距离太远，无法攻击', 'error');
            return;
        }

        // 检查视线
        if (!this.hasLineOfSight(
            player.position[0], player.position[1],
            monster.position[0], monster.position[1]
        )) {
            this.addMessage('视线被阻挡，无法攻击', 'error');
            return;
        }

        // 显示攻击遮罩（简短）
        this.game.showLLMOverlay('attack');

        try {
            // 计算伤害
            const damage = this.calculateDamage(player, monster);
            monster.stats.hp -= damage;

            this.addMessage(`攻击了 ${monster.name}`, 'action');
            this.addMessage(`对 ${monster.name} 造成了 ${damage} 点伤害`, 'combat');

            // 检查怪物是否死亡
            const monsterDied = monster.stats.hp <= 0;

            if (monsterDied) {
                // 传递伤害值给怪物死亡处理
                await this.handleMonsterDeath(monster, damage);
                // 怪物死亡后，handleMonsterDeath已经处理了UI更新和同步
                // 不需要继续处理怪物回合
                return;
            }

            // 增加回合数（只有怪物没死才增加）
            gameState.turn_count++;
            gameState.game_time++;

            // 处理怪物回合
            await this.processMonsterTurns();

            // 更新UI
            this.game.updateUI();

            // 检查是否需要同步
            if (this.shouldSync()) {
                await this.syncToBackend();
            }

            // 回合制游戏：攻击后检查是否有待处理的选择
            if (window.eventChoiceManager) {
                window.eventChoiceManager.checkAfterPlayerAction();
            }
        } finally {
            // 隐藏攻击遮罩
            this.game.hideLLMOverlay();
        }
    }
}

// 导出到全局作用域
window.LocalGameEngine = LocalGameEngine;

