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
        this.localEngine = null; // 本地游戏引擎
        this.mapZoomManager = null; // 地图缩放管理器

        this.init();
        this.initializeDebugMode();
        // loadConfig 将在 initializeDebugMode 中异步调用
    }

    init() {
        this.setupEventListeners();
        this.loadGameList();

        // 检查URL参数中是否有game_id
        this.checkUrlGameId();

        // 事件选择管理器已改为事件驱动模式，不需要初始化轮询
        // 回合制游戏只在玩家操作后检查待处理选择
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

                // 触发迷雾canvas初始化（游戏界面现在可见了）
                if (typeof window.initializeFogCanvas === 'function') {
                    setTimeout(() => window.initializeFogCanvas(), 100);
                }

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

    // 移除轮询初始化 - 改为事件驱动模式
    // 回合制游戏不需要定时轮询，只在玩家操作后检查即可

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
                this.localEngine = null; // 清理本地引擎
                this.addMessage('游戏会话已失效，请重新加载游戏', 'warning');

                // 停止EventChoiceManager轮询
                if (window.eventChoiceManager) {
                    window.eventChoiceManager.stopChoicePolling();
                }
                return;
            }

            const gameState = await response.json();

            this.gameState = gameState;

            // 初始化本地引擎（如果还没有）
            if (!this.localEngine && window.LocalGameEngine) {
                this.localEngine = new LocalGameEngine(this);
                console.log('[GameCore] LocalGameEngine initialized in refreshGameState');
            }

            // 初始化方向按钮管理器（如果还没有）
            this.initDirectionButtonManager();

            // 检查游戏是否结束（在更新UI之前）
            if (gameState.is_game_over) {
                this.handleGameOver(gameState.game_over_reason);
                return; // 游戏结束后不再处理其他逻辑
            }

            await this.updateUI(); // 等待UI更新完成

            // 检查是否有待处理的选择上下文，直接显示
            if (gameState.pending_choice_context && window.eventChoiceManager) {
                console.log('[GameCore] Found pending_choice_context in refreshed state, showing dialog');
                window.eventChoiceManager.showChoiceDialog(gameState.pending_choice_context);
            } else {
                // 回合制游戏：刷新状态后检查是否有待处理的选择
                if (window.eventChoiceManager) {
                    window.eventChoiceManager.checkAfterPlayerAction();
                }
            }
        } catch (error) {
            console.error('Failed to refresh game state:', error);

            // 如果是连接错误，提示用户
            if (error.message.includes('Failed to fetch')) {
                this.addMessage('无法连接到服务器，请检查网络连接', 'error');
            }
        }
    }

    async updateUI() {
        if (!this.gameState) return;

        // 首先检查游戏是否结束
        if (this.gameState.is_game_over) {
            this.handleGameOver(this.gameState.game_over_reason);
            return; // 游戏结束后不再更新其他UI
        }

        this.updateCharacterStats();
        await this.updateMap(); // 等待地图更新完成，确保角色精灵正确渲染
        this.updateInventory();
        this.updateQuests();
        this.updateControlPanel();
        this.processPendingEffects();

        // 【修复】更新视野，确保地图样式正确显示
        if (this.localEngine && this.gameState.player && this.gameState.player.position) {
            const [x, y] = this.gameState.player.position;
            this.localEngine.updateVisibility(x, y);
        }

        // 更新方向按钮状态
        this.updateDirectionButtons();
    }

    async updateGameState(newGameState) {
        /**
         * 更新游戏状态并刷新UI
         * 用于EventChoiceManager等组件更新游戏状态
         */
        this.gameState = newGameState;

        // 初始化本地引擎（如果还没有）
        if (!this.localEngine && window.LocalGameEngine) {
            this.localEngine = new LocalGameEngine(this);
            console.log('[updateGameState] LocalGameEngine initialized');
        }

        // 初始化方向按钮管理器（如果还没有）
        this.initDirectionButtonManager();

        // 检查游戏是否结束（在更新UI之前）
        if (newGameState.is_game_over) {
            this.handleGameOver(newGameState.game_over_reason);
            return; // 游戏结束后不再处理其他逻辑
        }

        await this.updateUI(); // 等待UI更新完成

        // 检查是否有待处理的选择上下文，直接显示
        if (newGameState.pending_choice_context && window.eventChoiceManager) {
            console.log('[GameCore] Found pending_choice_context in updated state, showing dialog');
            window.eventChoiceManager.showChoiceDialog(newGameState.pending_choice_context);
        } else {
            // 回合制游戏：加载游戏后检查是否有待处理的选择
            if (window.eventChoiceManager) {
                window.eventChoiceManager.checkAfterPlayerAction();
            }
        }
    }

    async renderGame() {
        await this.updateUI(); // 等待UI更新完成

        // 初始化本地引擎
        if (!this.localEngine && window.LocalGameEngine) {
            this.localEngine = new LocalGameEngine(this);
            console.log('[renderGame] LocalGameEngine initialized');
        }

        // 初始化方向按钮管理器
        this.initDirectionButtonManager();
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
        console.log('[handleGameOver] Game over triggered:', reason);

        // 防止重复触发
        if (this._gameOverHandled) {
            console.log('[handleGameOver] Already handled, skipping');
            return;
        }
        this._gameOverHandled = true;

        // 显示游戏结束界面
        this.addMessage(`游戏结束：${reason}`, 'error');

        // 停止EventChoiceManager轮询
        if (window.eventChoiceManager) {
            window.eventChoiceManager.stopChoicePolling();
        }

        // 禁用所有控制按钮
        const controlButtons = document.querySelectorAll('.control-btn, .dir-btn');
        controlButtons.forEach(btn => {
            btn.disabled = true;
        });

        // 禁用地图点击
        this.isLoading = true;

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
            // 地图切换前强制同步状态到后端，确保使用最新状态生成新地图
            if (this.localEngine) {
                console.log('[GameCore] Syncing state before map transition');
                await this.localEngine.syncToBackend();
            }

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

                // 更新游戏状态 - 使用updateGameState确保本地引擎正确初始化
                this.gameState = result.game_state;

                // 初始化本地引擎（如果还没有）
                if (!this.localEngine && window.LocalGameEngine) {
                    this.localEngine = new LocalGameEngine(this);
                    console.log('[transitionMap] LocalGameEngine initialized');
                }

                this.updateOverlayProgress(90, '更新界面...');

                // 重新渲染游戏界面
                await this.renderGame(); // 等待渲染完成

                // 显示事件消息
                if (result.events) {
                    result.events.forEach(event => {
                        this.addMessage(event, 'event');
                    });
                }

                this.updateOverlayProgress(100, '完成！');

                setTimeout(() => {
                    this.hidePartialOverlay();

                    // 【修复】检查是否有待处理的选择上下文（任务完成等）
                    if (result.pending_choice_context && window.eventChoiceManager) {
                        console.log('[transitionMap] Found pending_choice_context, showing dialog');
                        window.eventChoiceManager.showChoiceDialog(result.pending_choice_context);
                    }
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
            console.warn('[updateControlPanel] Control panel not found');
            return;
        }

        // 检查游戏是否结束，如果结束则不显示任何控制按钮
        if (this.gameState && this.gameState.is_game_over) {
            console.log('[updateControlPanel] Game is over, skipping control panel update');
            return;
        }

        // 检查是否有待切换的地图
        const hasPendingTransition = this.gameState && this.gameState.pending_map_transition;

        // 始终输出关键调试信息
        console.log('[updateControlPanel] Called - hasPendingTransition:', hasPendingTransition, 'value:', this.gameState?.pending_map_transition);

        let transitionButton = document.getElementById('transition-button');

        if (hasPendingTransition) {
            const transitionType = this.gameState.pending_map_transition;
            const buttonText = transitionType === 'stairs_down' ? '进入下一层' : '返回上一层';
            const iconName = transitionType === 'stairs_down' ? 'keyboard_arrow_down' : 'keyboard_arrow_up';

            if (!transitionButton) {
                // 创建新按钮
                transitionButton = document.createElement('button');
                transitionButton.id = 'transition-button';
                transitionButton.className = 'btn btn-warning control-btn transition-btn';

                // 设置按钮内容
                transitionButton.innerHTML = `
                    <i class="material-icons">${iconName}</i>
                    ${buttonText}
                `;

                // 使用addEventListener而不是onclick，确保事件绑定稳定
                transitionButton.addEventListener('click', () => {
                    console.log('[Transition Button] Clicked! Type:', this.gameState.pending_map_transition);
                    this.transitionMap(this.gameState.pending_map_transition);
                });

                controlPanel.appendChild(transitionButton);
                console.log('[updateControlPanel] Transition button created and added to DOM');
            } else {
                // 按钮已存在，只更新内容和状态（不重新绑定事件）
                // 检查是否需要更新内容（避免不必要的DOM操作）
                const currentText = transitionButton.textContent.trim();
                if (!currentText.includes(buttonText)) {
                    transitionButton.innerHTML = `
                        <i class="material-icons">${iconName}</i>
                        ${buttonText}
                    `;
                    console.log('[updateControlPanel] Transition button content updated:', buttonText);
                }
            }

            // 更新按钮禁用状态
            transitionButton.disabled = this.isLoading;

            console.log('[updateControlPanel] Transition button ready:', buttonText, 'disabled:', this.isLoading);
        } else if (transitionButton) {
            transitionButton.remove();
            console.log('[updateControlPanel] Transition button removed');
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
