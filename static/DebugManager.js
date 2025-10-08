// Labyrinthia AI - 调试功能模块
// 包含调试模式相关功能

// 全局调试状态检查函数
window.checkDebugStatus = function() {
    console.log('=== Debug Status Check ===');
    console.log('Game instance exists:', !!window.game);
    console.log('addDebugMethodsToGame function exists:', typeof addDebugMethodsToGame === 'function');

    if (window.game) {
        console.log('Game debug mode:', window.game.debugMode);
        console.log('Game initializeDebugMode method:', typeof window.game.initializeDebugMode);
        console.log('Game toggleDebugPanel method:', typeof window.game.toggleDebugPanel);

        const debugFab = document.getElementById('debug-fab');
        console.log('Debug FAB element exists:', !!debugFab);
        if (debugFab) {
            console.log('Debug FAB is hidden:', debugFab.classList.contains('hidden'));
        }

        const debugPanel = document.getElementById('debug-panel');
        console.log('Debug panel element exists:', !!debugPanel);
        if (debugPanel) {
            console.log('Debug panel is visible:', debugPanel.classList.contains('show'));
        }
    }
    console.log('=========================');
};

// 等待DOM加载完成后自动添加调试方法
document.addEventListener('DOMContentLoaded', function() {
    console.log('DebugManager: DOM loaded, initializing debug system...');

    // 延迟执行，确保游戏实例已创建
    setTimeout(function() {
        if (window.game && typeof addDebugMethodsToGame === 'function') {
            addDebugMethodsToGame(window.game);
            console.log('DebugManager: Debug methods automatically added to game instance');

            // 添加调试状态检查到控制台
            setTimeout(() => {
                window.checkDebugStatus();
            }, 1000);
        } else {
            console.warn('DebugManager: Game instance or addDebugMethodsToGame function not found, retrying...');
            // 如果游戏实例还没有创建，再等一会儿
            setTimeout(function() {
                if (window.game && typeof addDebugMethodsToGame === 'function') {
                    addDebugMethodsToGame(window.game);
                    console.log('DebugManager: Debug methods added to game instance (retry)');

                    // 添加调试状态检查到控制台
                    setTimeout(() => {
                        window.checkDebugStatus();
                    }, 1000);
                } else {
                    console.error('DebugManager: Failed to initialize debug system after retry');
                    window.checkDebugStatus();
                }
            }, 500);
        }
    }, 200);
});

// 定义调试功能对象，稍后添加到游戏实例中
const DebugMethods = {
    
    initializeDebugMode() {
        console.log('DebugManager: Initializing debug mode...');

        // 检查配置中是否启用调试模式
        this.checkDebugMode();

        // 设置FAB按钮事件 - 使用更安全的方式
        this.setupDebugFabButton();
    },

    setupDebugFabButton() {
        const debugFab = document.getElementById('debug-fab');
        if (debugFab) {
            // 移除可能存在的旧事件监听器
            debugFab.removeEventListener('click', this.boundToggleDebugPanel);

            // 绑定新的事件监听器
            this.boundToggleDebugPanel = () => {
                console.log('Debug FAB clicked');
                this.toggleDebugPanel();
            };
            debugFab.addEventListener('click', this.boundToggleDebugPanel);
            console.log('Debug FAB button event listener attached');
        } else {
            console.warn('Debug FAB button not found, retrying in 100ms...');
            setTimeout(() => {
                this.setupDebugFabButton();
            }, 100);
        }
    },

    async checkDebugMode() {
        try {
            console.log('DebugManager: Checking debug mode...');
            const response = await fetch('/api/config');
            const result = await response.json();
            const config = result.config || result; // 兼容新旧格式
            this.debugMode = config.game?.show_llm_debug || false;

            console.log('DebugManager: Debug mode status:', this.debugMode);
            console.log('DebugManager: Full config:', config);

            this.updateDebugFabVisibility();
        } catch (error) {
            console.error('DebugManager: Failed to check debug mode:', error);
            // 默认启用调试模式以便排查问题
            this.debugMode = true;
            this.updateDebugFabVisibility();
        }
    },

    toggleDebugPanel() {
        console.log('DebugManager: Toggling debug panel...');
        const debugPanel = document.getElementById('debug-panel');
        if (debugPanel) {
            debugPanel.classList.toggle('show');
            const isVisible = debugPanel.classList.contains('show');
            console.log('DebugManager: Debug panel is now', isVisible ? 'visible' : 'hidden');

            if (isVisible) {
                this.updateDebugInfo();
            }
        } else {
            console.error('DebugManager: Debug panel element not found!');
        }
    },

    updateDebugInfo() {
        if (!this.debugMode) return;

        // 更新LLM请求信息
        const requestElement = document.getElementById('debug-request');
        if (requestElement && this.lastLLMRequest) {
            requestElement.textContent = JSON.stringify(this.lastLLMRequest, null, 2);
        }

        // 更新LLM响应信息
        const responseElement = document.getElementById('debug-response');
        if (responseElement && this.lastLLMResponse) {
            responseElement.textContent = JSON.stringify(this.lastLLMResponse, null, 2);
        }

        // 更新游戏状态信息
        const gameStateElement = document.getElementById('debug-gamestate');
        if (gameStateElement && this.gameState) {
            const debugGameState = {
                player_position: this.gameState.player.position,
                player_hp: this.gameState.player.stats.hp,
                player_level: this.gameState.player.stats.level,
                map_name: this.gameState.current_map.name,
                turn_count: this.gameState.turn_count,
                monsters_count: this.gameState.monsters.length
            };
            gameStateElement.textContent = JSON.stringify(debugGameState, null, 2);
        }
    },

    updateDebugFabVisibility() {
        const debugFab = document.getElementById('debug-fab');
        if (debugFab) {
            if (this.debugMode) {
                debugFab.classList.remove('hidden');
                console.log('DebugManager: Debug FAB button shown');
            } else {
                debugFab.classList.add('hidden');
                console.log('DebugManager: Debug FAB button hidden');
            }
        } else {
            console.warn('DebugManager: Debug FAB button element not found');
            // 如果按钮还没有创建，稍后再试
            setTimeout(() => {
                this.updateDebugFabVisibility();
            }, 100);
        }
    },

    // ==================== 核心调试功能 ====================

    async debugTriggerRandomEvent() {
        if (!this.gameId || !this.gameState) {
            this.addMessage('❌ 请先开始游戏');
            return;
        }

        try {
            this.showLLMOverlay('interact');

            const response = await fetch(`/api/game/${this.gameId}/debug/trigger-event`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    position: this.gameState.player.position,
                    event_type: 'random'
                })
            });

            const result = await response.json();

            if (result.success) {
                this.addMessage('🎲 已触发随机事件');
                await this.refreshGameState();
            } else {
                this.addMessage(`❌ 触发事件失败: ${result.message}`);
            }
        } catch (error) {
            console.error('Debug trigger event error:', error);
            this.addMessage('❌ 触发事件时发生错误');
        } finally {
            this.hideLLMOverlay();
        }
    },

    async debugCompleteCurrentQuest() {
        if (!this.gameId || !this.gameState) {
            this.addMessage('❌ 请先开始游戏');
            return;
        }

        try {
            this.showLLMOverlay('interact');

            const response = await fetch(`/api/game/${this.gameId}/debug/complete-quest`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });

            const result = await response.json();

            if (result.success) {
                this.addMessage('✅ 当前任务已完成');
                await this.refreshGameState();
            } else {
                this.addMessage(`❌ 完成任务失败: ${result.message}`);
            }
        } catch (error) {
            console.error('Debug complete quest error:', error);
            this.addMessage('❌ 完成任务时发生错误');
        } finally {
            this.hideLLMOverlay();
        }
    },

    async debugGenerateTestItem() {
        if (!this.gameId || !this.gameState) {
            this.addMessage('❌ 请先开始游戏');
            return;
        }

        try {
            this.showLLMOverlay('interact');

            const response = await fetch(`/api/game/${this.gameId}/debug/generate-item`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    player_level: this.gameState.player.stats.level,
                    context: '调试模式生成的测试物品'
                })
            });

            const result = await response.json();

            if (result.success) {
                this.addMessage(`🎒 已生成测试物品: ${result.item_name}`);
                await this.refreshGameState();
            } else {
                this.addMessage(`❌ 生成物品失败: ${result.message}`);
            }
        } catch (error) {
            console.error('Debug generate item error:', error);
            this.addMessage('❌ 生成物品时发生错误');
        } finally {
            this.hideLLMOverlay();
        }
    },

    async debugGetRandomTreasure() {
        if (!this.gameId || !this.gameState) {
            this.addMessage('❌ 请先开始游戏');
            return;
        }

        try {
            this.showLLMOverlay('interact');

            const response = await fetch(`/api/game/${this.gameId}/debug/get-treasure`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    player_position: this.gameState.player.position,
                    player_level: this.gameState.player.stats.level,
                    quest_context: this.gameState.current_quest ? {
                        name: this.gameState.current_quest.name,
                        description: this.gameState.current_quest.description
                    } : null
                })
            });

            const result = await response.json();

            if (result.success) {
                this.addMessage(`💎 ${result.message}`);
                if (result.items && result.items.length > 0) {
                    result.items.forEach(item => {
                        this.addMessage(`  ✨ 获得: ${item}`, 'success');
                    });
                }
                await this.refreshGameState();
            } else {
                this.addMessage(`❌ 获取宝物失败: ${result.message}`);
            }
        } catch (error) {
            console.error('Debug get treasure error:', error);
            this.addMessage('❌ 获取宝物时发生错误');
        } finally {
            this.hideLLMOverlay();
        }
    },

    async debugTeleportToFloor() {
        if (!this.gameId || !this.gameState) {
            this.addMessage('❌ 请先开始游戏');
            return;
        }

        const floorInput = document.getElementById('debug-floor-input');
        const targetFloor = parseInt(floorInput.value);

        if (!targetFloor || targetFloor < 1 || targetFloor > 10) {
            this.addMessage('❌ 请输入有效的楼层数 (1-10)');
            return;
        }

        try {
            this.showLLMOverlay('interact');

            const response = await fetch(`/api/game/${this.gameId}/debug/teleport`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    target_floor: targetFloor
                })
            });

            const result = await response.json();

            if (result.success) {
                this.addMessage(`🚀 已传送到第${targetFloor}层`);
                await this.refreshGameState();
            } else {
                this.addMessage(`❌ 传送失败: ${result.message}`);
            }
        } catch (error) {
            console.error('Debug teleport error:', error);
            this.addMessage('❌ 传送时发生错误');
        } finally {
            this.hideLLMOverlay();
        }
    },

    async debugTeleportToPosition() {
        if (!this.gameId || !this.gameState) {
            this.addMessage('❌ 请先开始游戏');
            return;
        }

        const xInput = document.getElementById('debug-x-input');
        const yInput = document.getElementById('debug-y-input');
        const targetX = parseInt(xInput.value);
        const targetY = parseInt(yInput.value);

        if (isNaN(targetX) || isNaN(targetY)) {
            this.addMessage('❌ 请输入有效的坐标');
            return;
        }

        try {
            this.showLLMOverlay('interact');

            const response = await fetch(`/api/game/${this.gameId}/debug/teleport-position`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    x: targetX,
                    y: targetY
                })
            });

            const result = await response.json();

            if (result.success) {
                this.addMessage(`📍 已传送到坐标 (${targetX}, ${targetY})`);
                await this.refreshGameState();
            } else {
                this.addMessage(`❌ 传送失败: ${result.message}`);
            }
        } catch (error) {
            console.error('Debug teleport position error:', error);
            this.addMessage('❌ 传送时发生错误');
        } finally {
            this.hideLLMOverlay();
        }
    },

    // ==================== 地图与战斗调试 ====================

    async debugSpawnEnemyNearby() {
        if (!this.gameId || !this.gameState) {
            this.addMessage('❌ 请先开始游戏');
            return;
        }

        try {
            this.showLLMOverlay('interact');

            const response = await fetch(`/api/game/${this.gameId}/debug/spawn-enemy`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    player_position: this.gameState.player.position,
                    player_level: this.gameState.player.stats.level
                })
            });

            const result = await response.json();

            if (result.success) {
                this.addMessage(`👹 已在附近生成敌人: ${result.enemy_name}`);
                await this.refreshGameState();
            } else {
                this.addMessage(`❌ 生成敌人失败: ${result.message}`);
            }
        } catch (error) {
            console.error('Debug spawn enemy error:', error);
            this.addMessage('❌ 生成敌人时发生错误');
        } finally {
            this.hideLLMOverlay();
        }
    },

    async debugClearAllEnemies() {
        if (!this.gameId || !this.gameState) {
            this.addMessage('❌ 请先开始游戏');
            return;
        }

        try {
            this.showLLMOverlay('interact');

            const response = await fetch(`/api/game/${this.gameId}/debug/clear-enemies`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });

            const result = await response.json();

            if (result.success) {
                this.addMessage(`🧹 已清空 ${result.cleared_count} 个敌人`);
                await this.refreshGameState();
            } else {
                this.addMessage(`❌ 清空敌人失败: ${result.message}`);
            }
        } catch (error) {
            console.error('Debug clear enemies error:', error);
            this.addMessage('❌ 清空敌人时发生错误');
        } finally {
            this.hideLLMOverlay();
        }
    },

    async debugRegenerateCurrentMap() {
        if (!this.gameId || !this.gameState) {
            this.addMessage('❌ 请先开始游戏');
            return;
        }

        try {
            this.showLLMOverlay('interact');

            const response = await fetch(`/api/game/${this.gameId}/debug/regenerate-map`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    current_depth: this.gameState.current_map.depth
                })
            });

            const result = await response.json();

            if (result.success) {
                this.addMessage('🗺️ 当前地图已重新生成');
                await this.refreshGameState();
            } else {
                this.addMessage(`❌ 重新生成地图失败: ${result.message}`);
            }
        } catch (error) {
            console.error('Debug regenerate map error:', error);
            this.addMessage('❌ 重新生成地图时发生错误');
        } finally {
            this.hideLLMOverlay();
        }
    },

    // ==================== 状态管理调试 ====================

    async debugRestorePlayerStatus() {
        if (!this.gameId || !this.gameState) {
            this.addMessage('❌ 请先开始游戏');
            return;
        }

        try {
            this.showLLMOverlay('interact');

            const response = await fetch(`/api/game/${this.gameId}/debug/restore-player`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });

            const result = await response.json();

            if (result.success) {
                this.addMessage('💚 玩家状态已恢复到满值');
                await this.refreshGameState();
            } else {
                this.addMessage(`❌ 恢复状态失败: ${result.message}`);
            }
        } catch (error) {
            console.error('Debug restore player error:', error);
            this.addMessage('❌ 恢复状态时发生错误');
        } finally {
            this.hideLLMOverlay();
        }
    },

    debugShowFullGameState() {
        if (!this.gameState) {
            this.addMessage('❌ 请先开始游戏');
            return;
        }

        // 在调试面板中显示完整的游戏状态
        const gameStateElement = document.getElementById('debug-gamestate');
        if (gameStateElement) {
            const fullGameState = {
                game_id: this.gameId,
                player: this.gameState.player,
                current_map: {
                    name: this.gameState.current_map.name,
                    description: this.gameState.current_map.description,
                    depth: this.gameState.current_map.depth,
                    width: this.gameState.current_map.width,
                    height: this.gameState.current_map.height
                },
                quests: this.gameState.quests,
                monsters: this.gameState.monsters.map(m => ({
                    id: m.id,
                    name: m.name,
                    position: m.position,
                    stats: m.stats
                })),
                turn_count: this.gameState.turn_count,
                pending_events: this.gameState.pending_events,
                message_log: this.messageLog.slice(-10) // 最近10条消息
            };

            gameStateElement.textContent = JSON.stringify(fullGameState, null, 2);
            this.addMessage('📊 完整游戏状态已显示在调试面板中');

            // 确保调试面板是打开的
            const debugPanel = document.getElementById('debug-panel');
            if (debugPanel && !debugPanel.classList.contains('show')) {
                debugPanel.classList.add('show');
            }
        }
    },

    debugClearMessageLog() {
        // 清空消息日志
        this.messageLog = [];

        // 清空UI中的消息显示
        const messageContainer = document.getElementById('message-log');
        if (messageContainer) {
            messageContainer.innerHTML = '';
        }

        this.addMessage('🧹 消息日志已清空');
    }
};

// 添加调试方法到游戏实例的函数
function addDebugMethodsToGame(gameInstance) {
    console.log('DebugManager: Adding debug methods to game instance...');

    // 添加所有调试方法
    Object.assign(gameInstance, DebugMethods);

    // 确保关键调试方法被正确覆盖
    gameInstance.initializeDebugMode = DebugMethods.initializeDebugMode.bind(gameInstance);
    gameInstance.updateDebugFabVisibility = DebugMethods.updateDebugFabVisibility.bind(gameInstance);
    gameInstance.toggleDebugPanel = DebugMethods.toggleDebugPanel.bind(gameInstance);
    gameInstance.checkDebugMode = DebugMethods.checkDebugMode.bind(gameInstance);
    gameInstance.setupDebugFabButton = DebugMethods.setupDebugFabButton.bind(gameInstance);

    // 确保遮罩方法可用（如果OverlayManager已加载）
    if (typeof gameInstance.showLLMOverlay !== 'function') {
        console.warn('DebugManager: showLLMOverlay method not found, adding fallback');
        gameInstance.showLLMOverlay = function(action) {
            console.log('Fallback showLLMOverlay called with action:', action);
        };
    }

    if (typeof gameInstance.hideLLMOverlay !== 'function') {
        console.warn('DebugManager: hideLLMOverlay method not found, adding fallback');
        gameInstance.hideLLMOverlay = function() {
            console.log('Fallback hideLLMOverlay called');
        };
    }

    console.log('DebugManager: Debug methods successfully added to game instance');

    // 立即初始化调试模式
    if (typeof gameInstance.initializeDebugMode === 'function') {
        console.log('DebugManager: Initializing debug mode on game instance...');
        gameInstance.initializeDebugMode();
    } else {
        console.error('DebugManager: initializeDebugMode method not found on game instance');
    }
}
