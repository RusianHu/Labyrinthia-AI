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
        // loadConfig 将在 initializeDebugMode 中异步调用
    }
    
    init() {
        this.setupEventListeners();
        this.loadGameList();

        // 检查URL参数中是否有game_id
        this.checkUrlGameId();

        // 延迟启动事件选择管理器，确保所有脚本都已加载
        setTimeout(() => {
            this.initEventChoiceManager();
        }, 100);
    }

    checkUrlGameId() {
        // 检查URL参数中的game_id
        const urlParams = new URLSearchParams(window.location.search);
        const gameId = urlParams.get('game_id');

        if (gameId) {
            console.log('Found game_id in URL:', gameId);
            // 自动加载指定的游戏
            // 需要等待SaveManager加载完成后再调用
            setTimeout(() => {
                // 直接调用this.loadGame方法，因为SaveManager扩展了LabyrinthiaGame原型
                if (typeof this.loadGame === 'function') {
                    console.log('Auto-loading game via this.loadGame:', gameId);
                    this.loadGame(gameId);
                } else {
                    console.warn('loadGame method not available, trying alternative approach');
                    // 备用方案：直接调用API并手动处理界面切换
                    this.autoLoadGameFromUrl(gameId);
                }
            }, 1000); // 增加等待时间确保所有脚本都已加载
        }
    }

    async autoLoadGameFromUrl(gameId) {
        try {
            console.log('Auto-loading game from URL using backup method:', gameId);

            // 显示加载界面
            this.setLoading(true);
            this.showFullscreenOverlay('加载游戏', '正在读取您的冒险进度...', '连接到游戏服务器...');

            // 模拟进度更新
            this.updateOverlayProgress(15, '验证游戏存档...');
            await new Promise(resolve => setTimeout(resolve, 300));

            // 调用加载API
            this.updateOverlayProgress(30, '读取游戏数据...');
            const response = await fetch(`/api/load/${gameId}`, {
                method: 'POST'
            });

            this.updateOverlayProgress(50, '解析游戏状态...');
            const result = await response.json();

            if (result.success) {
                this.updateOverlayProgress(70, '重建游戏世界...');
                this.gameId = result.game_id;

                this.updateOverlayProgress(85, '加载角色状态...');
                await this.refreshGameState();

                this.updateOverlayProgress(95, '准备游戏界面...');

                // 显示叙述文本
                if (result.narrative) {
                    this.addMessage(result.narrative, 'narrative');
                }

                this.updateOverlayProgress(100, '加载完成！');

                // 延迟一下显示完成状态
                await new Promise(resolve => setTimeout(resolve, 800));

                // 隐藏主菜单，显示游戏界面
                document.getElementById('main-menu').style.display = 'none';
                document.getElementById('game-interface').style.display = 'block';

                this.hideFullscreenOverlay();
                this.addMessage('游戏已加载', 'success');
            } else {
                this.addMessage('加载失败: ' + (result.message || '未知错误'), 'error');
                this.hideFullscreenOverlay();
            }
        } catch (error) {
            console.error('Auto load error:', error);
            this.addMessage('自动加载游戏时发生错误', 'error');
            this.hideFullscreenOverlay();
        } finally {
            this.setLoading(false);
        }
    }

    initEventChoiceManager() {
        if (window.eventChoiceManager) {
            window.eventChoiceManager.startChoicePolling();
            console.log('EventChoiceManager polling started');
        } else {
            console.warn('EventChoiceManager not found, retrying...');
            // 如果还没有加载，再等一会儿
            setTimeout(() => {
                this.initEventChoiceManager();
            }, 500);
        }
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

            // 检查响应状态
            if (response.status === 404) {
                console.warn('Game not found on server, clearing game state');
                this.gameId = null;
                this.gameState = null;
                this.addMessage('游戏会话已失效，请重新加载游戏', 'warning');

                // 停止EventChoiceManager轮询
                if (window.eventChoiceManager) {
                    window.eventChoiceManager.stopChoicePolling();
                }
                return;
            }

            const gameState = await response.json();

            this.gameState = gameState;
            this.updateUI();

            // 触发EventChoiceManager立即检查
            if (window.eventChoiceManager) {
                window.eventChoiceManager.triggerImmediateCheck();
            }
        } catch (error) {
            console.error('Failed to refresh game state:', error);

            // 如果是连接错误，提示用户
            if (error.message.includes('Failed to fetch')) {
                this.addMessage('无法连接到服务器，请检查网络连接', 'error');
            }
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

    updateGameState(newGameState) {
        /**
         * 更新游戏状态并刷新UI
         * 用于EventChoiceManager等组件更新游戏状态
         */
        this.gameState = newGameState;
        this.updateUI();

        // 触发EventChoiceManager立即检查
        if (window.eventChoiceManager) {
            window.eventChoiceManager.triggerImmediateCheck();
        }
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

    // 调试方法占位符 - 将被DebugManager.js覆盖
    initializeDebugMode() {
        // 占位符方法，防止调用错误
        console.log('GameCore: Debug mode placeholder - will be overridden by DebugManager.js');

        // 基础调试模式初始化
        this.debugMode = false;

        // 异步加载配置并更新调试模式
        this.loadConfig().then(() => {
            // 只有在方法没有被覆盖时才调用占位符版本
            if (this.updateDebugFabVisibility.toString().includes('占位符')) {
                this.updateDebugFabVisibility();
            }
        }).catch(error => {
            console.warn('GameCore: Failed to load config for debug mode:', error);
        });
    }

    updateDebugFabVisibility() {
        // 占位符方法，防止调用错误
        console.log('GameCore: updateDebugFabVisibility placeholder called');
        const debugFab = document.getElementById('debug-fab');
        if (debugFab) {
            if (this.debugMode) {
                debugFab.classList.remove('hidden');
                console.log('GameCore: Debug FAB shown (placeholder)');
            } else {
                debugFab.classList.add('hidden');
                console.log('GameCore: Debug FAB hidden (placeholder)');
            }
        } else {
            console.warn('GameCore: Debug FAB element not found (placeholder)');
        }
    }
}
