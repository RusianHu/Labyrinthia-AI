// Labyrinthia AI - 核心游戏类模块
// 包含基础初始化、配置管理和游戏状态管理功能

class LabyrinthiaGame {
    constructor() {
        this.gameId = null;
        this.gameState = null;
        this.isLoading = false;
        this.messageLog = [];
        this.debugMode = false;
        this.lastLLMRequest = null;
        this.lastLLMResponse = null;
        this.hoveredTile = null;
        this.highlightedTiles = [];
        this.currentProgressInterval = null;
        this.config = null;

        this.init();
        this.initializeDebugMode();
        this.loadConfig();
    }
    
    init() {
        this.setupEventListeners();
        this.loadGameList();
    }

    async loadConfig() {
        try {
            const response = await fetch('/api/config');
            const result = await response.json();
            this.config = result.config || result; // 兼容新旧格式

            // 更新调试模式状态
            this.debugMode = this.config.game?.show_llm_debug || false;
            this.updateDebugFabVisibility();
        } catch (error) {
            console.error('Failed to load config:', error);
            this.config = {
                game: {
                    debug_mode: false,
                    show_llm_debug: false
                }
            }; // 默认配置
        }
    }

    async refreshGameState() {
        if (!this.gameId) return;

        try {
            const response = await fetch(`/api/game/${this.gameId}`);
            const gameState = await response.json();

            this.gameState = gameState;
            this.updateUI();
        } catch (error) {
            console.error('Failed to refresh game state:', error);
        }
    }

    updateUI() {
        if (!this.gameState) return;

        this.updateCharacterStats();
        this.updateMap();
        this.updateInventory();
        this.updateQuests();
        this.updateControlPanel();
        this.processPendingEffects();
    }

    renderGame() {
        this.updateUI();
    }

    processPendingEffects() {
        if (!this.gameState || !this.gameState.pending_effects) return;

        // 处理所有待显示的特效
        this.gameState.pending_effects.forEach(effect => {
            this.triggerEffect(effect);
        });

        // 清空已处理的特效
        this.gameState.pending_effects = [];
    }

    triggerEffect(effect) {
        switch (effect.type) {
            case 'quest_completion':
                this.showQuestCompletionEffect(effect);
                break;
            default:
                console.log('Unknown effect type:', effect.type);
        }
    }

    addMessage(text, type = 'system') {
        const messageLog = document.getElementById('message-log');
        const message = document.createElement('div');
        message.className = `message message-${type}`;
        message.textContent = text;
        
        messageLog.appendChild(message);
        messageLog.scrollTop = messageLog.scrollHeight;
        
        // 限制消息数量
        while (messageLog.children.length > 50) {
            messageLog.removeChild(messageLog.firstChild);
        }
    }

    handleGameOver(reason) {
        // 显示游戏结束界面
        this.addMessage(`游戏结束：${reason}`, 'error');

        // 禁用所有控制按钮
        const controlButtons = document.querySelectorAll('.control-btn, .dir-btn');
        controlButtons.forEach(btn => {
            btn.disabled = true;
        });

        // 显示游戏结束模态框
        setTimeout(() => {
            const gameOverModal = this.createGameOverModal(reason);
            document.body.appendChild(gameOverModal);
        }, 1000);
    }

    createGameOverModal(reason) {
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.display = 'block';
        modal.innerHTML = `
            <div class="modal-content" style="text-align: center; max-width: 400px;">
                <h2 style="color: #e74c3c; margin-bottom: 20px;">
                    <i class="material-icons" style="font-size: 48px; display: block; margin-bottom: 10px;">sentiment_very_dissatisfied</i>
                    游戏结束
                </h2>
                <p style="font-size: 18px; margin-bottom: 20px;">${reason}</p>
                <div style="margin-bottom: 20px;">
                    <p>你的冒险到此结束...</p>
                    <p>但是不要放弃，新的冒险等待着你！</p>
                </div>
                <div style="display: flex; gap: 10px; justify-content: center;">
                    <button class="btn btn-primary" onclick="location.reload()">
                        <i class="material-icons">refresh</i>
                        重新开始
                    </button>
                    <button class="btn btn-secondary" onclick="this.closest('.modal').remove(); document.getElementById('main-menu').style.display = 'block'; document.getElementById('game-interface').style.display = 'none';">
                        <i class="material-icons">home</i>
                        返回主菜单
                    </button>
                </div>
            </div>
        `;
        return modal;
    }

    // 新增：地图切换方法
    async transitionMap(transitionType) {
        if (this.isLoading || !this.gameId) return;

        this.setLoading(true);
        this.showPartialOverlay('地图切换', '正在进入新区域...', '准备继续你的冒险...');

        try {
            const response = await fetch(`/api/game/${this.gameId}/transition`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    type: transitionType
                })
            });

            const result = await response.json();

            if (result.success) {
                this.updateOverlayProgress(70, '加载新地图...');

                // 更新游戏状态
                this.gameState = result.game_state;

                this.updateOverlayProgress(90, '更新界面...');

                // 重新渲染游戏界面
                this.renderGame();

                // 显示事件消息
                if (result.events) {
                    result.events.forEach(event => {
                        this.addMessage(event, 'event');
                    });
                }

                this.updateOverlayProgress(100, '完成！');

                setTimeout(() => {
                    this.hidePartialOverlay();
                }, 500);
            } else {
                this.addMessage(result.message || '地图切换失败', 'error');
                this.hidePartialOverlay();
            }
        } catch (error) {
            console.error('Map transition error:', error);
            this.addMessage('地图切换时发生错误', 'error');
            this.hidePartialOverlay();
        } finally {
            this.setLoading(false);
        }
    }

    // 更新控制面板以显示地图切换按钮
    updateControlPanel() {
        const controlPanel = document.querySelector('.controls');
        if (!controlPanel) {
            console.warn('Control panel not found');
            return;
        }

        // 检查是否有待切换的地图
        const hasPendingTransition = this.gameState && this.gameState.pending_map_transition;

        // 调试信息
        if (this.config && this.config.debug_mode) {
            console.log('updateControlPanel called');
            console.log('gameState:', this.gameState);
            console.log('pending_map_transition:', this.gameState?.pending_map_transition);
            console.log('hasPendingTransition:', hasPendingTransition);
        }

        let transitionButton = document.getElementById('transition-button');

        if (hasPendingTransition) {
            if (!transitionButton) {
                transitionButton = document.createElement('button');
                transitionButton.id = 'transition-button';
                transitionButton.className = 'btn btn-warning control-btn transition-btn';
                controlPanel.appendChild(transitionButton);

                if (this.config && this.config.debug_mode) {
                    console.log('Transition button created and added to DOM');
                    console.log('Control panel:', controlPanel);
                    console.log('Button element:', transitionButton);
                }
            }

            const transitionType = this.gameState.pending_map_transition;
            const buttonText = transitionType === 'stairs_down' ? '进入下一层' : '返回上一层';
            const iconName = transitionType === 'stairs_down' ? 'keyboard_arrow_down' : 'keyboard_arrow_up';

            transitionButton.innerHTML = `
                <i class="material-icons">${iconName}</i>
                ${buttonText}
            `;

            transitionButton.onclick = () => this.transitionMap(transitionType);
            transitionButton.disabled = this.isLoading;

            if (this.config && this.config.debug_mode) {
                console.log('Transition button created/updated:', buttonText);
            }
        } else if (transitionButton) {
            transitionButton.remove();
            if (this.config && this.config.debug_mode) {
                console.log('Transition button removed');
            }
        }

        // 调试模式下添加测试按钮
        if (this.config && this.config.debug_mode && this.gameId) {
            let testButton = document.getElementById('test-transition-button');
            if (!testButton) {
                testButton = document.createElement('button');
                testButton.id = 'test-transition-button';
                testButton.className = 'btn btn-info control-btn';
                testButton.innerHTML = '<i class="material-icons">bug_report</i>测试楼梯';
                testButton.onclick = () => {
                    // 手动设置待切换状态进行测试
                    if (this.gameState) {
                        this.gameState.pending_map_transition = 'stairs_down';
                        this.updateControlPanel();
                    }
                };
                controlPanel.appendChild(testButton);
            }
        }
    }
}
