/**
 * Labyrinthia AI - 事件选择管理器
 * 处理类似galgame的选项框机制
 */

class EventChoiceManager {
    constructor() {
        this.currentContext = null;
        this.isProcessing = false;
        this.checkInterval = null;

        // 智能轮询相关属性
        this.baseInterval = 10000; // 基础轮询间隔：10秒
        this.activeInterval = 3000; // 活跃时轮询间隔：3秒
        this.currentInterval = this.baseInterval;
        this.lastActivityTime = Date.now();
        this.consecutiveEmptyChecks = 0;
        this.maxEmptyChecks = 5; // 连续5次空检查后降低频率

        this.initializeElements();
        this.startChoicePolling();
    }

    initializeElements() {
        this.dialog = document.getElementById('event-choice-dialog');
        this.title = document.getElementById('event-choice-title');
        this.description = document.getElementById('event-choice-description');
        this.optionsContainer = document.getElementById('event-choice-options');

        if (!this.dialog || !this.title || !this.description || !this.optionsContainer) {
            console.error('[EventChoiceManager] Event choice dialog elements not found:', {
                dialog: !!this.dialog,
                title: !!this.title,
                description: !!this.description,
                optionsContainer: !!this.optionsContainer
            });

            // 延迟重试初始化
            setTimeout(() => {
                console.log('[EventChoiceManager] Retrying element initialization...');
                this.initializeElements();
            }, 1000);
            return;
        }

        // 确保对话框初始状态正确
        this.dialog.style.display = 'none';
        this.dialog.classList.remove('show');

        console.log('[EventChoiceManager] Elements initialized successfully, initial state set to hidden');

        console.log('[EventChoiceManager] Elements initialized successfully');

        // 添加点击外部关闭功能（但只在没有强制选择时）
        this.dialog.addEventListener('click', (e) => {
            if (e.target === this.dialog && this.canClose()) {
                this.hideDialog();
            }
        });

        // 添加ESC键关闭功能
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isVisible() && this.canClose()) {
                this.hideDialog();
            }
        });
    }

    startChoicePolling() {
        // 智能轮询：根据活动情况动态调整频率
        this.checkInterval = setInterval(() => {
            if (!this.isVisible() && !this.isProcessing) {
                this.checkForPendingChoice();
            }
        }, this.currentInterval);

        console.log(`EventChoiceManager polling started (${this.currentInterval/1000}s interval)`);
    }

    stopChoicePolling() {
        if (this.checkInterval) {
            clearInterval(this.checkInterval);
            this.checkInterval = null;
            console.log('EventChoiceManager polling stopped');
        }
    }

    // 立即检查待处理选择（用于游戏状态变化时）
    triggerImmediateCheck() {
        if (!this.isVisible() && !this.isProcessing) {
            this.checkForPendingChoice();
            // 记录活动时间并提升轮询频率
            this.recordActivity();
            this.boostPollingFrequency();
        }
    }

    // 记录活动时间
    recordActivity() {
        this.lastActivityTime = Date.now();
        this.consecutiveEmptyChecks = 0; // 重置空检查计数
    }

    // 临时提升轮询频率
    boostPollingFrequency() {
        if (this.currentInterval !== this.activeInterval) {
            this.currentInterval = this.activeInterval;
            this.restartPolling();

            // 30秒后恢复正常频率
            setTimeout(() => {
                this.adjustPollingInterval();
            }, 30000);
        }
    }

    // 根据活动情况调整轮询间隔
    adjustPollingInterval() {
        const timeSinceLastActivity = Date.now() - this.lastActivityTime;
        const oldInterval = this.currentInterval;

        if (this.consecutiveEmptyChecks >= this.maxEmptyChecks) {
            // 连续多次空检查，降低频率
            this.currentInterval = Math.min(this.baseInterval * 2, 20000); // 最多20秒
        } else if (timeSinceLastActivity > 120000) { // 2分钟无活动
            this.currentInterval = this.baseInterval;
        } else if (timeSinceLastActivity > 60000) { // 1分钟无活动
            this.currentInterval = Math.floor((this.baseInterval + this.activeInterval) / 2); // 中等频率
        } else {
            this.currentInterval = this.activeInterval; // 保持高频率
        }

        if (oldInterval !== this.currentInterval) {
            this.restartPolling();
        }
    }

    // 重启轮询
    restartPolling() {
        this.stopChoicePolling();
        this.startChoicePolling();
    }

    async checkForPendingChoice() {
        try {
            const gameId = window.game?.gameId;  // 修复：使用gameId而不是currentGameId
            if (!gameId) return;

            const response = await fetch(`/api/game/${gameId}/pending-choice`);

            // 检查响应状态
            if (response.status === 404 || response.status === 500) {
                // 游戏不存在，可能是服务器重启了
                console.warn('Game not found on server, clearing gameId and stopping polling');
                if (window.game) {
                    window.game.gameId = null;
                    window.game.gameState = null;
                    window.game.localEngine = null; // 清理本地引擎
                }
                this.stopChoicePolling();

                // 显示提示信息
                if (window.game) {
                    window.game.addMessage('游戏会话已失效，请重新加载游戏', 'warning');
                }
                return;
            }

            const data = await response.json();

            if (data.success && data.has_pending_choice && data.choice_context) {
                this.showChoiceDialog(data.choice_context);
                this.recordActivity(); // 记录活动
                this.consecutiveEmptyChecks = 0;
                console.log('Found pending choice:', data.choice_context.title);
            } else {
                // 增加空检查计数
                this.consecutiveEmptyChecks++;

                // 只在调试模式下输出空检查日志
                if (window.game?.debugMode && this.consecutiveEmptyChecks <= 3) {
                    console.log(`No pending choice (${this.consecutiveEmptyChecks}/${this.maxEmptyChecks})`);
                }

                // 调整轮询频率
                this.adjustPollingInterval();
            }
        } catch (error) {
            // 检查是否是网络连接错误
            if (error.message.includes('Failed to fetch') || error.message.includes('ERR_CONNECTION_REFUSED')) {
                console.warn('Server connection failed, stopping polling temporarily');
                this.consecutiveEmptyChecks += 5; // 快速减少轮询频率

                // 如果连续失败太多次，停止轮询
                if (this.consecutiveEmptyChecks > 20) {
                    console.warn('Too many connection failures, stopping polling');
                    this.stopChoicePolling();
                    if (window.game) {
                        window.game.addMessage('无法连接到服务器，请检查网络连接', 'error');
                    }
                }
            } else {
                console.error('Error checking for pending choice:', error);
                this.consecutiveEmptyChecks++;
            }
        }
    }

    showChoiceDialog(choiceContext) {
        if (!this.dialog || !this.title || !this.description || !this.optionsContainer) {
            console.error('[EventChoiceManager] Cannot show dialog - elements not initialized');
            return;
        }

        // 检查对话框当前状态
        const currentDisplay = this.dialog.style.display;
        const hasShowClass = this.dialog.classList.contains('show');
        console.log('[EventChoiceManager] Dialog state check:', {
            display: currentDisplay,
            hasShowClass: hasShowClass,
            isVisible: this.isVisible()
        });

        if (this.isVisible()) {
            console.warn('[EventChoiceManager] Dialog already visible, skipping. Current context:', this.currentContext?.title);
            return; // 已经显示了对话框
        }

        console.log('[EventChoiceManager] Showing choice dialog:', choiceContext.title);

        this.currentContext = choiceContext;

        // 设置标题和描述
        this.title.textContent = choiceContext.title || '事件选择';
        this.description.textContent = choiceContext.description || '';

        // 清空选项容器
        this.optionsContainer.innerHTML = '';

        // 创建选项
        if (choiceContext.choices && choiceContext.choices.length > 0) {
            choiceContext.choices.forEach((choice, index) => {
                const optionElement = this.createChoiceOption(choice, index);
                this.optionsContainer.appendChild(optionElement);
            });
        } else {
            console.warn('[EventChoiceManager] No choices available in context');
        }

        // 显示对话框
        console.log('[EventChoiceManager] Setting dialog display to flex');
        this.dialog.style.display = 'flex';

        // 添加显示动画
        setTimeout(() => {
            console.log('[EventChoiceManager] Adding show class');
            this.dialog.classList.add('show');

            // 验证显示状态
            const finalState = {
                display: this.dialog.style.display,
                hasShowClass: this.dialog.classList.contains('show'),
                isVisible: this.isVisible()
            };
            console.log('[EventChoiceManager] Final dialog state:', finalState);
        }, 10);

        // 播放音效（如果有）
        this.playChoiceSound();

        console.log('[EventChoiceManager] Dialog display initiated');
    }

    createChoiceOption(choice, index) {
        const optionDiv = document.createElement('div');
        optionDiv.className = 'choice-option';
        optionDiv.dataset.choiceId = choice.id;
        optionDiv.dataset.index = index;

        // 检查是否可用
        if (!choice.is_available) {
            optionDiv.classList.add('disabled');
        }

        // 创建选项内容
        const textDiv = document.createElement('div');
        textDiv.className = 'choice-text';
        textDiv.textContent = choice.text;

        const descDiv = document.createElement('div');
        descDiv.className = 'choice-description';
        descDiv.textContent = choice.description;

        const consDiv = document.createElement('div');
        consDiv.className = 'choice-consequences';
        consDiv.textContent = choice.consequences;

        optionDiv.appendChild(textDiv);
        optionDiv.appendChild(descDiv);
        optionDiv.appendChild(consDiv);

        // 添加要求标签（如果有）
        if (choice.requirements && Object.keys(choice.requirements).length > 0) {
            const reqDiv = document.createElement('div');
            reqDiv.className = 'choice-requirements';
            reqDiv.textContent = choice.is_available ? '✓' : '✗';
            optionDiv.appendChild(reqDiv);
        }

        // 添加点击事件
        if (choice.is_available) {
            optionDiv.addEventListener('click', () => {
                this.selectChoice(choice.id);
            });

            // 添加键盘支持
            optionDiv.setAttribute('tabindex', '0');
            optionDiv.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    this.selectChoice(choice.id);
                }
            });
        }

        return optionDiv;
    }

    async selectChoice(choiceId) {
        if (this.isProcessing || !this.currentContext) return;

        this.isProcessing = true;

        try {
            // 【修复】选择前强制同步状态到后端，避免状态不一致
            if (window.game && window.game.localEngine) {
                console.log('[EventChoiceManager] Syncing state before processing choice');
                await window.game.localEngine.syncToBackend();
            }

            // 添加选中效果
            const selectedOption = this.optionsContainer.querySelector(`[data-choice-id="${choiceId}"]`);
            if (selectedOption) {
                selectedOption.classList.add('selected');

                // 禁用其他选项
                const allOptions = this.optionsContainer.querySelectorAll('.choice-option');
                allOptions.forEach(option => {
                    if (option !== selectedOption) {
                        option.style.opacity = '0.5';
                        option.style.pointerEvents = 'none';
                    }
                });
            }

            // 播放选择音效
            this.playSelectSound();

            // 短暂延迟以显示选择效果
            await new Promise(resolve => setTimeout(resolve, 500));

            // 显示LLM交互遮罩
            if (window.game) {
                window.game.showLLMOverlay('interact');
            }

            // 发送选择到服务器
            const gameId = window.game?.gameId;  // 修复：使用gameId而不是currentGameId
            if (!gameId) {
                throw new Error('No active game');
            }

            const response = await fetch('/api/event-choice', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    game_id: gameId,
                    context_id: this.currentContext.id,
                    choice_id: choiceId
                })
            });

            // 检查HTTP状态码
            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(`HTTP ${response.status}: ${errorText}`);
            }

            const result = await response.json();

            // 隐藏LLM交互遮罩
            if (window.game) {
                window.game.hideLLMOverlay();
            }

            if (result.success) {
                // 隐藏对话框
                this.hideDialog();

                // 显示结果消息
                if (result.message) {
                    window.game?.addMessage(result.message, 'success');
                }

                // 显示事件
                if (result.events && result.events.length > 0) {
                    result.events.forEach(event => {
                        window.game?.addMessage(event, 'narrative');
                    });
                }

                // 更新游戏状态
                if (result.game_state && window.game) {
                    window.game.updateGameState(result.game_state);
                }

                // 记录活动并提升轮询频率
                this.recordActivity();
                this.boostPollingFrequency();

                console.log('Choice processed successfully:', result);
            } else {
                throw new Error(result.message || 'Failed to process choice');
            }

        } catch (error) {
            console.error('Error processing choice:', error);
            window.game?.addMessage(`处理选择时发生错误: ${error.message}`, 'error');

            // 隐藏LLM交互遮罩（错误情况下）
            if (window.game) {
                window.game.hideLLMOverlay();
            }

            // 恢复选项状态
            const allOptions = this.optionsContainer.querySelectorAll('.choice-option');
            allOptions.forEach(option => {
                option.style.opacity = '';
                option.style.pointerEvents = '';
                option.classList.remove('selected');
            });
        } finally {
            this.isProcessing = false;
        }
    }

    hideDialog() {
        if (!this.isVisible()) return;

        this.dialog.classList.remove('show');
        
        setTimeout(() => {
            this.dialog.style.display = 'none';
            this.currentContext = null;
            this.optionsContainer.innerHTML = '';
        }, 300);

        console.log('Event choice dialog hidden');
    }

    isVisible() {
        // 检查对话框是否真正可见（display不为none且有show类）
        return this.dialog &&
               this.dialog.style.display !== 'none' &&
               this.dialog.classList.contains('show');
    }

    canClose() {
        // 检查当前上下文是否允许关闭（某些强制选择不能关闭）
        if (!this.currentContext) return true;
        
        // 如果是任务完成或重要剧情选择，不允许关闭
        const forcedTypes = ['quest_completion', 'story_event'];
        return !forcedTypes.includes(this.currentContext.event_type);
    }

    playChoiceSound() {
        // 播放选择出现音效
        try {
            // 这里可以添加音效播放逻辑
            console.log('Playing choice sound');
        } catch (error) {
            console.warn('Could not play choice sound:', error);
        }
    }

    playSelectSound() {
        // 播放选择确认音效
        try {
            // 这里可以添加音效播放逻辑
            console.log('Playing select sound');
        } catch (error) {
            console.warn('Could not play select sound:', error);
        }
    }

    destroy() {
        this.stopChoicePolling();
        this.hideDialog();
        this.currentContext = null;
    }
}

// 创建全局实例
window.eventChoiceManager = new EventChoiceManager();
