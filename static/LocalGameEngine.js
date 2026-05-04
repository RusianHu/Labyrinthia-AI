// Labyrinthia AI - 本地游戏引擎
// 在前端处理基础游戏逻辑，减少不必要的后端请求

class LocalGameEngine {
    constructor(game) {
        this.game = game; // 引用主游戏对象
        this.syncInterval = 10; // 每10回合同步一次到后端
        this.lastSyncTurn = 0;
    }

    getCombatAuthorityMode() {
        const mode = this.game?.config?.game?.combat_authority_mode;
        if (typeof mode === 'string' && ['local', 'hybrid', 'server'].includes(mode)) {
            return mode;
        }
        return 'local';
    }

    isServerAuthoritativeCombat() {
        const mode = this.getCombatAuthorityMode();
        return mode === 'hybrid' || mode === 'server';
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

                    // 【修复】同步更新DOM元素的CSS类
                    const tileElement = document.querySelector(`[data-x="${x}"][data-y="${y}"]`);
                    if (tileElement) {
                        if (tile.is_explored) {
                            tileElement.classList.remove('tile-unexplored');
                            tileElement.classList.add('tile-explored');
                        }
                        if (tile.is_visible) {
                            tileElement.classList.add('tile-visible');
                        }
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
     *
     * 【重要】此方法会将前端的"计算型"数据同步到后端，
     * 并从后端获取最新的"生成型"数据（如任务进度、经验值等）
     */
    async syncToBackend() {
        const gameState = this.getGameState();
        if (!gameState || !this.game.gameId) return;

        try {
            const response = await fetch('/api/sync-state', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    game_id: this.game.gameId,
                    game_state: gameState
                })
            });

            const result = await response.json();

            if (result.success && result.game_state) {
                // 【关键】更新前端游戏状态，获取后端的最新数据
                // 特别是任务进度、经验值、等级等"生成型"数据
                this.game.gameState.quests = result.game_state.quests;
                this.game.gameState.player.stats.experience = result.game_state.player.stats.experience;
                this.game.gameState.player.stats.level = result.game_state.player.stats.level;
                this.game.gameState.player.inventory = result.game_state.player.inventory;

                console.log(`[LocalGameEngine] 状态已同步到后端并更新 (回合 ${gameState.turn_count})`);
            }

            this.lastSyncTurn = gameState.turn_count;
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

    getTrapData(tile) {
        if (!tile) return {};

        if (tile.has_event && tile.event_type === 'trap') {
            return tile.event_data || {};
        }

        if (tile.terrain === 'trap') {
            return {
                trap_type: 'damage',
                damage: 15,
                damage_type: 'physical',
                detect_dc: 15,
                disarm_dc: 18,
                save_dc: 14,
                save_half_damage: true
            };
        }

        return {};
    }

    getAbilityModifierFromScore(score) {
        const value = Number(score);
        if (!Number.isFinite(value)) return 0;
        return Math.floor((value - 10) / 2);
    }

    getPlayerProficiencyBonus(player) {
        const explicitBonus = Number(player?.proficiency_bonus);
        if (Number.isFinite(explicitBonus) && explicitBonus > 0) {
            return explicitBonus;
        }

        const level = Number(player?.stats?.level || 1);
        if (level <= 4) return 2;
        if (level <= 8) return 3;
        if (level <= 12) return 4;
        if (level <= 16) return 5;
        return 6;
    }

    getPassivePerception(player) {
        const explicitPassive = Number(player?.passive_perception);
        if (Number.isFinite(explicitPassive)) {
            return explicitPassive;
        }

        const wisdom = player?.abilities?.wisdom;
        const wisdomModifier = this.getAbilityModifierFromScore(wisdom);
        const skillProficiencies = Array.isArray(player?.skill_proficiencies)
            ? player.skill_proficiencies
            : [];
        const proficiency = skillProficiencies.includes('perception')
            ? this.getPlayerProficiencyBonus(player)
            : 0;

        return 10 + wisdomModifier + proficiency;
    }

    evaluateTrapPassiveDetection(tile) {
        const gameState = this.getGameState();
        const trapData = this.getTrapData(tile);
        const explicitDC = Number(trapData.detect_dc);
        const detectDC = Number.isFinite(explicitDC) ? explicitDC : 15;
        const passivePerception = this.getPassivePerception(gameState?.player);

        return {
            detected: passivePerception >= detectDC,
            trapData,
            detectDC,
            passivePerception
        };
    }

    /**
     * 检查陷阱侦测（被动感知）
     */
    async checkTrapDetection(tile, position) {
        const gameState = this.getGameState();

        // 优先检查陷阱是否已经触发（触发后trap_detected也会是true，所以要先检查）
        if (tile.event_triggered) {
            console.log('[LocalGameEngine] Trap already triggered');
            // 已触发陷阱：不弹对话框、不再次触发，只进行常规回合与UI刷新
            try {
                await this.processMonsterTurns();
                if (this.game && this.game.updateUI) {
                    await this.game.updateUI();
                }
                if (this.shouldSync()) {
                    await this.syncToBackend();
                }
            } catch (e) {
                console.warn('[LocalGameEngine] Post-move pipeline after triggered trap failed:', e);
            }
            return;
        }

        // 如果陷阱已经被发现（但未触发），直接显示选项框
        if (tile.trap_detected) {
            console.log('[LocalGameEngine] Trap already detected, showing choices');
            await this.showTrapChoices(tile, position);
            return;
        }

        // 【修复】设置加载状态以阻止键盘输入
        this.game.isLoading = true;

        try {
            const result = this.evaluateTrapPassiveDetection(tile);

            if (result.detected) {
                // 被动侦测成功！
                console.log('[LocalGameEngine] Trap detected by passive perception');

                // 更新瓦片状态
                tile.trap_detected = true;
                if (tile.has_event && tile.event_type === 'trap') {
                    tile.event_data.is_detected = true;
                }

                // 显示发现陷阱的消息
                this.addMessage(
                    `你的敏锐感知发现了陷阱！（被动感知 ${result.passivePerception} vs DC ${result.detectDC}）`,
                    'warning'
                );

                // 播放发现陷阱特效
                this.showTrapDetectedEffect([position.x, position.y]);

                // 显示选项框（若陷阱尚未被触发）
                if (tile.event_triggered || (tile.event_data && (tile.event_data.is_triggered || tile.event_data.trap_triggered))) {
                    console.log('[LocalGameEngine] Trap already triggered, skip showing choices');
                    // 【修复】重置加载状态
                    this.game.isLoading = false;
                    // 可选提示：
                    // this.addMessage('该陷阱已被触发。', 'info');
                } else {
                    await this.showTrapChoices(tile, position);
                }
            } else {
                // 未能发现陷阱，直接触发
                console.log('[LocalGameEngine] Trap not detected, triggering...');

                this.addMessage(
                    `你踩到了什么东西... 🎲 被动感知 ${result.passivePerception} vs DC ${result.detectDC} - 失败`,
                    'warning'
                );

                // handleTrap内部会管理isLoading状态
                await this.handleTrap(tile);
            }
        } catch (error) {
            console.error('[LocalGameEngine] Failed to evaluate trap detection:', error);
            // 【修复】重置加载状态
            this.game.isLoading = false;
            // 出错时直接触发陷阱
            await this.handleTrap(tile);
        }
    }

    /**
     * 显示陷阱选项框
     */
    async showTrapChoices(tile, position) {
        const gameState = this.getGameState();
        const trapData = tile.event_data || {};
        const player = gameState.player;

        // 【修复】设置加载状态以阻止键盘输入，直到选项框显示完成
        this.game.isLoading = true;

        // 构建选项列表
        const choices = [];

        // 选项1：解除陷阱
        const hasTools = player.tool_proficiencies && player.tool_proficiencies.includes('thieves_tools');
        const disarmDC = trapData.disarm_dc || 18;
        choices.push({
            id: "disarm",
            text: "🔧 解除陷阱",
            description: `使用${hasTools ? '盗贼工具' : '徒手'}尝试解除陷阱`,
            requirements: hasTools ? "✓ 有盗贼工具" : "✗ 无工具（劣势）",
            consequences: `成功则陷阱消失并获得经验，失败则触发陷阱（DC ${disarmDC}）`
        });

        // 选项2：小心规避
        const saveDC = trapData.save_dc || 14;
        const dexMod = player.abilities?.dexterity ? Math.floor((player.abilities.dexterity - 10) / 2) : 0;
        choices.push({
            id: "avoid",
            text: "🏃 小心规避",
            description: `尝试避开陷阱触发机制`,
            requirements: `敏捷调整值 ${dexMod >= 0 ? '+' : ''}${dexMod}`,
            consequences: `成功则安全通过，失败则触发陷阱（敏捷豁免 DC ${saveDC}）`
        });

        // 选项3：故意触发
        choices.push({
            id: "trigger",
            text: "💥 故意触发",
            description: "从当前位置触发陷阱，清除威胁",
            requirements: "无",
            consequences: "陷阱将被触发"
        });

        // 选项4：后退
        choices.push({
            id: "retreat",
            text: "↩️ 后退",
            description: "返回上一个位置",
            requirements: "无",
            consequences: "陷阱仍然存在"
        });

        // 创建陷阱事件上下文
        const trapName = trapData.trap_name || "未知陷阱";
        const trapDesc = trapData.trap_description || "你发现了一个陷阱！";

        // 使用UUID作为上下文ID，满足后端校验要求
        const contextId = (window.crypto && window.crypto.randomUUID)
            ? window.crypto.randomUUID()
            : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
                  const r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
                  return v.toString(16);
              });

        // 先调用后端注册context
        try {
            const response = await fetch('/api/trap-choice/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    game_id: gameState.id,
                    context_id: contextId,
                    trap_name: trapName,
                    trap_description: trapDesc,
                    trap_data: trapData,
                    position: [position.x, position.y],
                    choices: choices
                })
            });

            const result = await response.json();

            if (result.success) {
                // 显示选项对话框
                // 【重要】不在此处重置 isLoading，保持锁定直到玩家完成选择
                // EventChoiceManager.selectChoice 的 finally 块会负责解锁
                if (this.game && this.game.showEventChoiceDialog) {
                    this.game.showEventChoiceDialog({
                        success: true,
                        context_id: contextId,
                        title: `⚠️ 发现陷阱：${trapName}`,
                        description: trapDesc,
                        choices: choices
                    });
                } else {
                    // 当前页面未集成选项对话框组件时，需要解锁
                    this.game.isLoading = false;
                    console.warn('[LocalGameEngine] showEventChoiceDialog not available');
                }
            } else {
                // 【修复】重置加载状态
                this.game.isLoading = false;
                console.error('[LocalGameEngine] Failed to register trap context:', result);
                this.addMessage('无法注册陷阱事件', 'error');
            }
        } catch (error) {
            // 【修复】重置加载状态
            this.game.isLoading = false;
            console.error('[LocalGameEngine] Failed to register trap context:', error);
            this.addMessage('陷阱事件注册失败', 'error');
        }
    }

    /**
     * 显示陷阱发现特效
     */
    showTrapDetectedEffect(position) {
        // 调用游戏核心的特效管理器
        if (this.game && this.game.enhancedEffects) {
            this.game.enhancedEffects.playTrapDetectedEffect(position[0], position[1]);
        }

        // 更新UI以显示陷阱高亮
        if (this.game && this.game.updateUI) {
            this.game.updateUI();
        }
    }

    /**
     * 处理陷阱（统一调用后端接口，包含敏捷豁免判定）
     * 注意：此方法用于未被发现的陷阱直接触发
     * 后端会自动进行敏捷豁免判定，并根据结果计算伤害（可能减半）
     */
    async handleTrap(tile) {
        const gameState = this.getGameState();
        const position = [tile.x, tile.y];

        console.log('[LocalGameEngine] Triggering trap at', position);

        // 【修复】设置加载状态以阻止键盘输入
        this.game.isLoading = true;

        // 显示LLM遮罩（因为需要后端处理和LLM生成叙述）
        this.game.showLLMOverlay('trap_trigger');

        try {
            // 调用后端统一陷阱触发接口
            const response = await fetch('/api/trap/trigger', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    game_id: gameState.id,
                    position: position,
                    game_state: gameState
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const result = await response.json();

            if (result.success) {
                // 【修复】触发陷阱后，陷阱位置暴露
                tile.event_triggered = true;
                tile.trap_detected = true;  // 触发后玩家知道这里有陷阱
                if (tile.has_event && tile.event_type === 'trap') {
                    if (!tile.event_data) tile.event_data = {};
                    tile.event_data.is_detected = true;
                    tile.event_data.is_triggered = true;
                }

                // 显示豁免判定信息（如果有）
                if (result.save_attempted && result.save_message) {
                    this.addMessage(result.save_message, 'system');
                }

                const triggerResult = result.trigger_result;
                const hasNarrative = !!(result.narrative && String(result.narrative).trim());

                // 有 narrative 时优先展示 narrative，避免与 description 重复刷屏
                if (!hasNarrative) {
                    if (triggerResult.description) {
                        this.addMessage(triggerResult.description, 'combat');
                    } else if (triggerResult.damage > 0) {
                        this.addMessage(`触发了陷阱！受到了 ${triggerResult.damage} 点伤害！`, 'combat');
                    }
                }

                if (hasNarrative) {
                    this.addMessage(result.narrative, 'narrative');
                }

                // 更新玩家HP
                gameState.player.stats.hp = result.player_hp;

                // 处理传送效果（如果有）
                if (triggerResult.teleported && triggerResult.new_position) {
                    const newPos = triggerResult.new_position;
                    this.updatePlayerPosition(newPos[0], newPos[1]);
                    this.updateVisibility(newPos[0], newPos[1]);
                    this.addMessage(
                        `触发了传送陷阱！被传送到了 (${newPos[0]}, ${newPos[1]})！`,
                        'system'
                    );
                }

                // 检查玩家是否死亡
                if (result.player_died) {
                    this.addMessage('你被陷阱杀死了！游戏结束！', 'error');
                    gameState.is_game_over = true;
                    gameState.game_over_reason = '被陷阱杀死';

                    // 更新UI显示游戏结束状态
                    this.game.updateUI();

                    // 触发游戏结束处理
                    if (this.game.handleGameOver) {
                        this.game.handleGameOver(gameState.game_over_reason);
                    }
                } else {
                    // 玩家存活，继续游戏流程

                    // 处理怪物回合
                    await this.processMonsterTurns();

                    // 更新UI
                    await this.game.updateUI();

                    // 检查是否需要同步
                    if (this.shouldSync()) {
                        await this.syncToBackend();
                    }
                }
            } else {
                this.addMessage(result.message || '陷阱触发失败', 'error');
            }

        } catch (error) {
            console.error('[LocalGameEngine] Failed to trigger trap:', error);
            this.addMessage('陷阱触发失败，请重试', 'error');
        } finally {
            // 【修复】重置加载状态
            this.game.isLoading = false;
            // 确保隐藏遮罩
            this.game.hideLLMOverlay();
        }
    }

    /**
     * 处理宝藏（前端本地处理，但物品生成需要后端LLM）
     */
    async handleTreasure(tile) {
        // 【修复】设置加载状态以阻止键盘输入
        this.game.isLoading = true;

        try {
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
        } finally {
            // 【修复】重置加载状态
            this.game.isLoading = false;
        }
    }

    /**
     * 触发后端事件
     */
    async triggerBackendEvent(eventType, eventData) {
        console.log('[LocalGameEngine] Triggering backend event:', eventType);

        // 【修复】确保加载状态已设置（调用者应该已经设置，但这里做双重保险）
        const wasLoading = this.game.isLoading;
        if (!wasLoading) {
            this.game.isLoading = true;
        }

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

                // 【优化】只在后端明确返回 has_pending_choice 时才检查
                // 避免不必要的 GET 请求
                if (result.has_pending_choice && window.eventChoiceManager) {
                    console.log('[LocalGameEngine] Backend event created pending choice, checking...');
                    window.eventChoiceManager.checkAfterPlayerAction();
                }
            } else {
                this.addMessage(result.message || '事件处理失败', 'error');
            }
        } catch (error) {
            console.error('[LocalGameEngine] 后端事件处理失败:', error);
            this.addMessage('网络错误，请重试', 'error');
        } finally {
            // 【修复】只有在调用前未设置加载状态时才重置
            if (!wasLoading) {
                this.game.isLoading = false;
            }
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

        // 【修复】检查游戏是否正在加载中，如果是则忽略移动请求
        if (this.game.isLoading) {
            console.log('[LocalGameEngine] Move blocked - game is loading');
            return;
        }

        console.log('[LocalGameEngine] Moving player:', direction);

        if (this.isServerAuthoritativeCombat()) {
            await this.game.performAction('move', { direction });
            return;
        }

        // 计算新位置
        const newPos = this.calculateNewPosition(direction);
        if (!newPos) {
            this.addMessage('无效的移动方向', 'error');
            return;
        }

        // 读取目标瓦片信息
        const targetTile = this.getTile(newPos.x, newPos.y);
        if (!targetTile) {
            this.addMessage('无法移动到该位置', 'error');
            return;
        }

        // 键盘移动遇到敌人时自动发起攻击
        if (targetTile.character_id && targetTile.character_id !== gameState.player.id) {
            const monster = this.findMonster(targetTile.character_id);
            if (monster) {
                const distance = this.calculateDistance(gameState.player.position, monster.position);
                if (distance <= 1) {
                    await this.attackMonster(monster.id);
                } else {
                    this.addMessage('目标距离太远，无法攻击', 'error');
                }
            } else {
                this.addMessage('该位置已被占据', 'error');
            }
            return;
        }

        // 验证移动
        if (!this.canMoveTo(newPos.x, newPos.y)) {
            if (targetTile.terrain === 'wall') {
                this.addMessage('无法穿过墙壁', 'error');
            } else {
                this.addMessage('无法移动到该位置', 'error');
            }
            return;
        }

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

        // 检查玩家是否已经死亡（例如通过调试功能设置HP为0）
        if (gameState.player.stats.hp <= 0) {
            this.addMessage('你已经死亡！游戏结束！', 'error');
            gameState.is_game_over = true;
            gameState.game_over_reason = '生命值耗尽';

            // 触发游戏结束处理
            if (this.game.handleGameOver) {
                this.game.handleGameOver(gameState.game_over_reason);
            }
            return;
        }

        // 检查特殊地形（前端本地处理）
        if (targetTile.terrain === 'trap' || (targetTile.has_event && targetTile.event_type === 'trap')) {
            // 检查陷阱侦测
            await this.checkTrapDetection(targetTile, newPos);
            // checkTrapDetection会处理后续逻辑（显示选项框或直接触发）
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
            await this.game.updateUI(); // 等待UI更新完成

            // 检查是否需要同步
            if (this.shouldSync()) {
                await this.syncToBackend();
            }

            // 【优化】移除普通移动后的自动检查
            // 普通移动不会产生 pending-choice，不需要每次都发起 GET 请求
            // 只在后端事件（陷阱、宝藏、特殊事件）完成后才检查
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
        if (this.isServerAuthoritativeCombat()) {
            return;
        }

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
        if (this.isServerAuthoritativeCombat()) {
            return;
        }

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

        // 【修复】设置加载状态以阻止键盘输入
        this.game.isLoading = true;

        // 显示LLM遮罩，准备生成战斗叙述
        this.game.showLLMOverlay('combat_victory');

        try {
            // 【重要】先调用后端战斗结果管理器（此时怪物还在列表中）
            const idempotencyKey = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
            const clientTraceId = `client-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
            const response = await fetch(`/api/game/${gameState.id}/combat-result`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    monster_id: monster.id,
                    damage_dealt: damageDealt,
                    idempotency_key: idempotencyKey,
                    client_trace_id: clientTraceId
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

            // 【新增】检查是否有任务完成需要处理选择
            // 后端在处理任务怪物时会触发任务进度更新，如果任务完成会设置 pending_quest_completion
            if (combatResult.has_pending_choice && window.eventChoiceManager) {
                console.log('[LocalGameEngine] Quest completion detected after monster defeat, will check pending choice');
                // 标记需要检查 pending-choice，在 finally 块中执行
                this._needCheckPendingChoice = true;
            }

            // 【修复】不在这里更新UI，等到finally块中统一更新
            // this.game.updateUI(); // 移除这里的UI更新

        } catch (error) {
            console.error('[LocalGameEngine] Error processing monster death:', error);

            if (this.isServerAuthoritativeCombat()) {
                this.addMessage('战斗结算失败，请稍后重试', 'error');
            } else {
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
            }
        } finally {
            // 【关键修复】在移除怪物之前触发特效（此时怪物图标还在DOM中）
            const tileElement = document.querySelector(`[data-x="${monster.position[0]}"][data-y="${monster.position[1]}"]`);
            console.log('[LocalGameEngine] Checking monster defeat effect:', {
                tileElement: !!tileElement,
                enhancedEffects: !!this.game.enhancedEffects,
                monsterPosition: monster.position,
                monsterName: monster.name,
                hasMonsterIcon: !!tileElement?.querySelector('.character-monster')
            });

            let effectDuration = 0;
            if (tileElement && this.game.enhancedEffects) {
                console.log('[LocalGameEngine] Triggering monster defeat effect for:', monster.name);
                this.game.enhancedEffects.showMonsterDefeatEffect(monster, tileElement);
                // 特效持续时间：怪物淡出(300ms) + 碎片爆炸(800ms) = 1100ms
                effectDuration = 1100;
            } else {
                console.warn('[LocalGameEngine] Cannot show monster defeat effect:', {
                    tileElement: !!tileElement,
                    enhancedEffects: !!this.game.enhancedEffects
                });
            }

            // 【重要】从怪物列表中移除（在特效触发之后）
            const finalIndex = gameState.monsters.findIndex(m => m.id === monster.id);
            if (finalIndex !== -1) {
                gameState.monsters.splice(finalIndex, 1);
            }

            // 清除地图上的怪物标记
            const tile = this.getTile(monster.position[0], monster.position[1]);
            if (tile) {
                tile.character_id = null;
            }

            // 【修复】延迟更新UI，等待特效完成
            setTimeout(() => {
                this.game.updateUI();
            }, effectDuration);

            // 隐藏LLM遮罩
            this.game.hideLLMOverlay();

            // 同步状态到后端
            await this.syncToBackend();

            // 【新增】检查是否需要处理任务完成选择
            if (this._needCheckPendingChoice && window.eventChoiceManager) {
                console.log('[LocalGameEngine] Checking for pending choice after monster defeat');
                window.eventChoiceManager.checkAfterPlayerAction();
                this._needCheckPendingChoice = false;
            }

            // 【修复】重置加载状态
            this.game.isLoading = false;
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

        if (this.isServerAuthoritativeCombat()) {
            const idempotencyKey = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
            const clientTraceId = `client-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
            const predictedDamage = this.calculateDamage(player, monster);
            await this.game.performAction('attack', {
                target_id: monsterId,
                idempotency_key: idempotencyKey,
                client_trace_id: clientTraceId,
                client_prediction: {
                    hit: true,
                    damage: Math.max(0, predictedDamage),
                    death: monster.stats.hp - predictedDamage <= 0,
                    exp: 0,
                },
            });
            return;
        }

        // 【修复】检查游戏是否正在加载中
        if (this.game.isLoading) {
            console.log('[LocalGameEngine] Attack blocked - game is loading');
            return;
        }

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

        // 【修复】设置加载状态
        this.game.isLoading = true;

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
            await this.game.updateUI(); // 等待UI更新完成

            // 检查是否需要同步
            if (this.shouldSync()) {
                await this.syncToBackend();
            }

            // 【优化】移除攻击后的自动检查
            // 任务完成检查已经在 handleMonsterDeath 中根据后端响应的 has_pending_choice 标志处理
            // 普通攻击不会产生 pending-choice，不需要每次都发起 GET 请求
        } finally {
            // 【修复】重置加载状态（怪物死亡的情况已在 handleMonsterDeath 中处理）
            if (monster.stats.hp > 0) {
                this.game.isLoading = false;
            }
            // 隐藏攻击遮罩
            this.game.hideLLMOverlay();
        }
    }
}

// 导出到全局作用域
window.LocalGameEngine = LocalGameEngine;

