// Labyrinthia AI - 游戏动作模块
// 包含玩家移动、攻击、祈祷等游戏动作相关逻辑

// 扩展核心游戏类，添加游戏动作功能
Object.assign(LabyrinthiaGame.prototype, {

    async movePlayer(direction) {
        if (this.isLoading) return;

        // 使用本地引擎处理移动
        if (this.localEngine) {
            await this.localEngine.movePlayer(direction);
        } else {
            // 回退到后端处理
            await this.performAction('move', { direction });
        }
    },
    
    async performAction(action, parameters = {}) {
        if (this.isLoading || !this.gameId) return null;

        if (action === 'rest' && this.localEngine) {
            await this.localEngine.syncToBackend();
        }

        const needsSpecificLLMOverlay = this.shouldShowLLMOverlay(action, parameters);
        if (needsSpecificLLMOverlay) {
            this.showLLMOverlay(action);
            this.isLoading = true;
            const controlButtons = document.querySelectorAll('.control-btn, .dir-btn');
            controlButtons.forEach(btn => {
                btn.disabled = true;
            });
        } else {
            this.setLoading(true);
        }

        let hasPendingChoiceContext = false;

        try {
            const params = { ...(parameters || {}) };
            if ((action === 'use_item' || action === 'drop_item' || action === 'attack') && !params.idempotency_key) {
                params.idempotency_key = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
            }
            if (!params.client_trace_id) {
                params.client_trace_id = `client-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
            }

            const requestData = {
                game_id: this.gameId,
                action: action,
                parameters: params
            };

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
                const backendNeedsLLMOverlay = result.llm_interaction_required;
                let showedBackendOverlay = false;

                if (backendNeedsLLMOverlay && !needsSpecificLLMOverlay) {
                    this.showLLMOverlay('处理中');
                    showedBackendOverlay = true;
                }

                await this.refreshGameState();

                if (!hasPendingChoiceContext && this.gameState?.pending_choice_context && window.eventChoiceManager) {
                    console.log('[GameActions] Found pending_choice_context after refreshGameState');
                    this.isLoading = true;
                    hasPendingChoiceContext = true;
                }

                if (result.message) {
                    this.addMessage(result.message, 'action');
                }

                if (result.events) {
                    result.events.forEach(event => {
                        const messageType = event.includes('造成') || event.includes('攻击') ? 'combat' : 'system';
                        this.addMessage(event, messageType);
                    });
                }

                if (result.narrative) {
                    this.addMessage(result.narrative, 'narrative');
                }

                if (result.pending_choice_context && window.eventChoiceManager) {
                    console.log('[GameActions] Found pending_choice_context in action result, showing dialog immediately');
                    this.isLoading = true;
                    hasPendingChoiceContext = true;
                    window.eventChoiceManager.showChoiceDialog(result.pending_choice_context);
                } else if (window.eventChoiceManager) {
                    window.eventChoiceManager.checkAfterPlayerAction();
                }

                if (result.game_over) {
                    this.handleGameOver(result.game_over_reason);
                }

                if (showedBackendOverlay) {
                    this.hideLLMOverlay();
                }
            } else {
                this.handleActionErrorResult(result, action, params);
            }

            return result;
        } catch (error) {
            console.error('Action error:', error);
            this.addMessage('网络错误，请重试', 'error');
            return null;
        } finally {
            if (hasPendingChoiceContext) {
                console.log('[GameActions] Keeping input locked - pending choice context exists');
                if (needsSpecificLLMOverlay) {
                    this.hideLLMOverlay();
                }
                return;
            }

            const hasPendingDialog = window.eventChoiceManager?.isVisible();
            if (hasPendingDialog) {
                console.log('[GameActions] Keeping input locked - choice dialog is visible');
                if (needsSpecificLLMOverlay) {
                    this.hideLLMOverlay();
                }
                return;
            }

            if (needsSpecificLLMOverlay) {
                this.hideLLMOverlay();
                const controlButtons = document.querySelectorAll('.control-btn, .dir-btn');
                controlButtons.forEach(btn => {
                    btn.disabled = false;
                });
                this.isLoading = false;
            } else {
                this.setLoading(false);
            }
        }
    },

    async attackMonster(monsterId) {
        // 使用本地引擎处理攻击
        if (this.localEngine) {
            await this.localEngine.attackMonster(monsterId);
        } else {
            // 回退到后端处理
            await this.performAction('attack', { target_id: monsterId });
        }
    },

    async useItem(itemId) {
        // 使用物品前强制同步状态到后端，避免状态不一致
        if (this.localEngine) {
            await this.localEngine.syncToBackend();
        }
        await this.performAction('use_item', { item_id: itemId });
    },

    async dropItem(itemId) {
        if (this.localEngine) {
            await this.localEngine.syncToBackend();
        }
        const result = await this.performAction('drop_item', { item_id: itemId });

        if (result && result.success && result.undo_token) {
            const confirmed = window.confirm('已丢弃该物品，可在短时间内撤销。是否立即撤销？');
            if (confirmed) {
                await this.performAction('undo_drop_item', { undo_token: result.undo_token });
            }
        }
    },

    handleActionErrorResult(result, action, params = {}) {
        const errorCode = result?.error_code || 'ACTION_FAILED';
        const message = result?.message || '行动失败';

        if (errorCode === 'QUEST_ITEM_LOCKED') {
            const confirmMessage = `${message}\n\n该操作可能影响任务进度，是否强制丢弃？`;
            const confirmed = window.confirm(confirmMessage);
            if (confirmed) {
                const nextParams = { ...params, force: true };
                this.performAction(action, nextParams);
                return;
            }
        }

        if (errorCode === 'ITEM_ON_COOLDOWN' || errorCode === 'ITEM_NO_CHARGES') {
            this.addMessage(message, 'system');
            return;
        }

        if (result?.retryable) {
            this.addMessage(`${message}（可重试）`, 'error');
            return;
        }

        this.addMessage(message, 'error');
    },

    shouldShowLLMOverlay(action, parameters) {
        // 检查是否需要显示LLM遮罩
        // 主要在以下情况显示：
        // 1. 移动到特殊地形（但不包括楼梯，楼梯只是提示）
        // 2. 交互行动
        // 3. 攻击行动
        // 4. 祈祷时可能触发事件

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
            // 祈祷时可能触发随机事件
            return Math.random() < 0.3; // 30%概率显示遮罩
        }

        return false;
    }
});
