// Labyrinthia AI - 调试功能模块
// 包含调试模式相关功能

// 扩展核心游戏类，添加调试功能
Object.assign(LabyrinthiaGame.prototype, {
    
    initializeDebugMode() {
        // 检查配置中是否启用调试模式
        this.checkDebugMode();

        // 设置FAB按钮事件
        const debugFab = document.getElementById('debug-fab');
        if (debugFab) {
            debugFab.addEventListener('click', () => {
                this.toggleDebugPanel();
            });
        }
    },

    async checkDebugMode() {
        try {
            const response = await fetch('/api/config');
            const result = await response.json();
            const config = result.config || result; // 兼容新旧格式
            this.debugMode = config.game?.show_llm_debug || false;

            this.updateDebugFabVisibility();
        } catch (error) {
            console.error('Failed to check debug mode:', error);
        }
    },

    toggleDebugPanel() {
        const debugPanel = document.getElementById('debug-panel');
        if (debugPanel) {
            debugPanel.classList.toggle('show');
            this.updateDebugInfo();
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
            } else {
                debugFab.classList.add('hidden');
            }
        }
    }
});
