// Labyrinthia AI - 游戏动作模块
// 包含玩家移动、攻击、休息等游戏动作相关逻辑

// 扩展核心游戏类，添加游戏动作功能
Object.assign(LabyrinthiaGame.prototype, {
    
    async movePlayer(direction) {
        if (this.isLoading) return;
        
        await this.performAction('move', { direction });
    },
    
    async performAction(action, parameters = {}) {
        if (this.isLoading || !this.gameId) return;

        // 检查是否需要显示特定的LLM遮罩（特殊地形或事件触发时）
        const needsSpecificLLMOverlay = this.shouldShowLLMOverlay(action, parameters);

        // 如果需要特定的LLM遮罩，先显示它，然后再设置loading
        if (needsSpecificLLMOverlay) {
            this.showLLMOverlay(action);
            this.isLoading = true;
            // 禁用控制按钮但不显示通用的loading indicator
            const controlButtons = document.querySelectorAll('.control-btn, .dir-btn');
            controlButtons.forEach(btn => {
                btn.disabled = true;
            });
        } else {
            // 普通情况，使用标准的loading（会自动显示遮罩）
            this.setLoading(true);
        }

        try {
            const requestData = {
                game_id: this.gameId,
                action: action,
                parameters: parameters
            };

            // 记录调试信息
            if (this.debugMode) {
                this.lastLLMRequest = {
                    timestamp: new Date().toISOString(),
                    action: action,
                    parameters: parameters,
                    game_id: this.gameId
                };
            }

            const response = await fetch('/api/action', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(requestData)
            });

            const result = await response.json();

            // 记录响应调试信息
            if (this.debugMode) {
                this.lastLLMResponse = {
                    timestamp: new Date().toISOString(),
                    success: result.success,
                    message: result.message,
                    events: result.events,
                    narrative: result.narrative
                };
                this.updateDebugInfo();
            }
            
            if (result.success) {
                // 检查后端是否指示需要LLM遮罩（用于怪物攻击等情况）
                const backendNeedsLLMOverlay = result.llm_interaction_required;
                let showedBackendOverlay = false;

                if (backendNeedsLLMOverlay && !needsSpecificLLMOverlay) {
                    this.showLLMOverlay('处理中');
                    showedBackendOverlay = true;
                }

                // 更新游戏状态
                await this.refreshGameState();

                // 添加消息
                if (result.message) {
                    this.addMessage(result.message, 'action');
                }

                if (result.events) {
                    result.events.forEach(event => {
                        // 战斗伤害消息使用特殊样式
                        const messageType = event.includes('造成') || event.includes('攻击') ? 'combat' : 'system';
                        this.addMessage(event, messageType);
                    });
                }

                if (result.narrative) {
                    this.addMessage(result.narrative, 'narrative');
                }

                // 检查游戏是否结束
                if (result.game_over) {
                    this.handleGameOver(result.game_over_reason);
                }

                // 如果显示了后端指示的LLM遮罩，现在隐藏它
                if (showedBackendOverlay) {
                    this.hideLLMOverlay();
                }
            } else {
                this.addMessage(result.message || '行动失败', 'error');
            }
        } catch (error) {
            console.error('Action error:', error);
            this.addMessage('网络错误，请重试', 'error');
        } finally {
            // 隐藏特定的LLM遮罩
            if (needsSpecificLLMOverlay) {
                this.hideLLMOverlay();
                // 重新启用控制按钮
                const controlButtons = document.querySelectorAll('.control-btn, .dir-btn');
                controlButtons.forEach(btn => {
                    btn.disabled = false;
                });
                this.isLoading = false;
            } else {
                // 普通情况，使用标准的setLoading(false)
                this.setLoading(false);
            }
        }
    },

    async attackMonster(monsterId) {
        await this.performAction('attack', { target_id: monsterId });
    },

    async useItem(itemId) {
        await this.performAction('use_item', { item_id: itemId });
    },

    async dropItem(itemId) {
        await this.performAction('drop_item', { item_id: itemId });
    },

    shouldShowLLMOverlay(action, parameters) {
        // 检查是否需要显示LLM遮罩
        // 主要在以下情况显示：
        // 1. 移动到特殊地形（但不包括楼梯，楼梯只是提示）
        // 2. 交互行动
        // 3. 攻击行动
        // 4. 休息时可能触发事件

        if (action === 'interact') {
            return true;
        }

        if (action === 'attack') {
            return true;
        }

        if (action === 'move') {
            // 检查目标位置是否有特殊地形
            const direction = parameters.direction;
            if (this.gameState && this.gameState.player) {
                const player = this.gameState.player;
                const currentX = player.position[0];
                const currentY = player.position[1];

                // 计算目标位置
                const directionMap = {
                    "north": [0, -1], "south": [0, 1],
                    "east": [1, 0], "west": [-1, 0],
                    "northeast": [1, -1], "northwest": [-1, -1],
                    "southeast": [1, 1], "southwest": [-1, 1]
                };

                if (direction && directionMap[direction]) {
                    const [dx, dy] = directionMap[direction];
                    const targetX = currentX + dx;
                    const targetY = currentY + dy;
                    const tileKey = `${targetX},${targetY}`;
                    const targetTile = this.gameState.current_map.tiles[tileKey];

                    if (targetTile) {
                        // 特殊地形需要LLM处理（楼梯除外，楼梯只是设置待切换状态）
                        const llmRequiredTerrains = ['trap', 'treasure', 'door'];
                        if (llmRequiredTerrains.includes(targetTile.terrain) || targetTile.has_event) {
                            return true;
                        }
                    }
                }
            }
        }

        if (action === 'rest') {
            // 休息时可能触发随机事件
            return Math.random() < 0.3; // 30%概率显示遮罩
        }

        return false;
    }
});
