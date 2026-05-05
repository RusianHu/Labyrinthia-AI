// Labyrinthia AI - 存档管理模块
// 包含游戏保存、加载、删除等存档管理逻辑

// 扩展核心游戏类，添加存档管理功能
Object.assign(LabyrinthiaGame.prototype, {
    
    async saveGame() {
        if (!this.gameId || this.isLoading) return;

        this.setLoading(true);

        try {
            // 保存前强制同步状态到后端，确保保存最新的游戏进度
            if (this.localEngine) {
                console.log('[SaveManager] Syncing state before save');
                await this.localEngine.syncToBackend();
            }

            const response = await fetch(`/api/save/${this.gameId}`, {
                method: 'POST'
            });

            const result = await response.json();

            if (result.success) {
                this.addMessage('游戏已保存', 'success');
            } else {
                this.addMessage('保存失败', 'error');
            }
        } catch (error) {
            console.error('Save error:', error);
            this.addMessage('保存时发生错误', 'error');
        } finally {
            this.setLoading(false);
        }
    },
    
    async loadGameList() {
        try {
            const response = await fetch('/api/saves');
            const saves = await response.json();

            const savesList = document.getElementById('saves-list');
            if (savesList) {
                savesList.innerHTML = '';

                saves.forEach(save => {
                    const saveElement = document.createElement('div');
                    saveElement.className = 'save-item';

                    const rawDescription = typeof save.map_description === 'string'
                        ? save.map_description.trim()
                        : '';
                    const displayLocation = rawDescription || save.map_name || 'Unknown';

                    const title = document.createElement('h4');
                    title.textContent = `${save.player_name || 'Unknown'} (等级 ${save.player_level || 1})`;

                    const location = document.createElement('p');
                    location.textContent = `${displayLocation} - 回合 ${save.turn_count || 0}`;

                    const lastSaved = document.createElement('p');
                    lastSaved.textContent = `最后保存: ${new Date(save.last_saved).toLocaleString()}`;

                    const buttons = document.createElement('div');
                    buttons.className = 'save-item-buttons';

                    const createButton = (iconName, label, handler) => {
                        const button = document.createElement('button');
                        const icon = document.createElement('i');
                        icon.className = 'material-icons';
                        icon.textContent = iconName;
                        button.appendChild(icon);
                        button.appendChild(document.createTextNode(label));
                        button.addEventListener('click', handler);
                        return button;
                    };

                    buttons.appendChild(createButton('play_arrow', '加载', () => game.loadGame(save.id)));
                    buttons.appendChild(createButton('file_download', '导出', () => game.exportSave(save.id)));
                    buttons.appendChild(createButton('delete', '删除', () => game.deleteGame(save.id)));

                    saveElement.appendChild(title);
                    saveElement.appendChild(location);
                    saveElement.appendChild(lastSaved);
                    saveElement.appendChild(buttons);
                    savesList.appendChild(saveElement);
                });
            }
        } catch (error) {
            console.error('Failed to load game list:', error);
        }
    },
    
    async loadGame(saveId) {
        this.setLoading(true);
        this.showFullscreenOverlay('加载存档', '正在读取您的冒险进度...', '连接到游戏服务器...');

        try {
            this.updateOverlayProgress(15, '验证存档文件...');
            await new Promise(resolve => setTimeout(resolve, 400));

            this.updateOverlayProgress(30, '读取游戏数据...');

            // 先尝试普通加载
            let response = await fetch(`/api/load/${saveId}`, {
                method: 'POST'
            });

            // 如果404且调试模式开启，尝试使用调试强制加载
            if (response.status === 404 && this.debugMode) {
                console.log('[SaveManager] Normal load failed (404), trying debug force-load...');
                this.updateOverlayProgress(35, '[调试模式] 尝试强制加载...');

                // 先获取所有存档，找到这个game_id对应的user_id
                const savesResponse = await fetch('/api/debug/list-all-saves');
                if (savesResponse.ok) {
                    const allSaves = await savesResponse.json();
                    const targetSave = allSaves.saves.find(s => s.game_id === saveId);

                    if (targetSave) {
                        console.log(`[SaveManager] Found save in user ${targetSave.user_id}, force loading...`);
                        response = await fetch('/api/debug/force-load', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                game_id: saveId,
                                user_id: targetSave.user_id
                            })
                        });
                    }
                }
            }

            this.updateOverlayProgress(50, '解析游戏状态...');
            const result = await response.json();

            if (result.success) {
                this.updateOverlayProgress(70, '重建游戏世界...');
                this.gameId = result.game_id;

                this.updateOverlayProgress(85, '加载角色状态...');
                await this.refreshGameState();

                this.updateOverlayProgress(95, '准备游戏界面...');
                this.addMessage('游戏已加载', 'success');

                // 显示叙述文本
                if (result.narrative) {
                    this.addMessage(result.narrative, 'narrative', { suppressAutoTTS: true });
                }

                this.updateOverlayProgress(100, '加载完成！');

                // 延迟一下显示完成状态
                await new Promise(resolve => setTimeout(resolve, 800));

                // 隐藏主菜单，显示游戏界面
                document.getElementById('main-menu').style.display = 'none';
                document.getElementById('game-interface').style.display = 'grid';

                // 触发迷雾canvas初始化（游戏界面现在可见了）
                if (typeof window.initializeFogCanvas === 'function') {
                    setTimeout(() => window.initializeFogCanvas(), 100);
                }

                this.hideFullscreenOverlay();
            } else {
                this.addMessage('加载失败', 'error');
                this.hideFullscreenOverlay();
            }
        } catch (error) {
            console.error('Load error:', error);
            this.addMessage('加载时发生错误', 'error');
            this.hideFullscreenOverlay();
        } finally {
            this.setLoading(false);
        }
    },

    async deleteGame(saveId) {
        // 显示确认对话框
        if (!confirm('确定要删除这个存档吗？此操作无法撤销。')) {
            return;
        }

        this.setLoading(true);

        try {
            const response = await fetch(`/api/save/${saveId}`, {
                method: 'DELETE'
            });

            const result = await response.json();

            if (result.success) {
                this.addMessage('存档已删除', 'success');
                // 刷新存档列表
                await this.loadGameList();
            } else {
                this.addMessage('删除失败', 'error');
            }
        } catch (error) {
            console.error('Delete error:', error);
            this.addMessage('删除时发生错误', 'error');
        } finally {
            this.setLoading(false);
        }
    },
    
    async createNewGame() {
        const playerName = document.getElementById('player-name-input').value.trim();
        const characterClass = document.getElementById('character-class-select').value;

        if (!playerName) {
            alert('请输入角色名称');
            return;
        }

        this.setLoading(true);
        this.showFullscreenOverlay('创建新游戏', '正在为您生成独特的冒险世界...', '初始化AI系统...');

        try {
            this.updateOverlayProgress(10, '验证角色信息...');
            await new Promise(resolve => setTimeout(resolve, 500));

            this.updateOverlayProgress(20, '创建角色档案...');
            await new Promise(resolve => setTimeout(resolve, 300));

            const response = await fetch('/api/new-game', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    player_name: playerName,
                    character_class: characterClass
                })
            });

            // 检查响应状态
            if (!response.ok) {
                // 处理验证失败（400错误）
                if (response.status === 400) {
                    const errorData = await response.json();
                    const errorMsg = errorData.detail || '输入验证失败';

                    // 根据错误类型显示不同的幽默提示
                    let funnyMessage = this.getSecurityErrorMessage(errorMsg, playerName);

                    this.hideFullscreenOverlay();
                    this.showSecurityAlert(funnyMessage, errorMsg);
                    this.setLoading(false);
                    return;
                }

                // 其他HTTP错误
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            this.updateOverlayProgress(45, 'AI正在生成地下城...');
            const result = await response.json();

            if (result.success) {
                if (this.ttsManager && Array.isArray(result.opening_speech_segments)) {
                    this.updateOverlayProgress(55, '语音GM正在准备开场旁白...');
                    // 先做合成预热（不入队播放）；真正入队播放放到 addMessage 之后，
                    // 这样按钮就能携带 .is-speaking 动效。
                    this.ttsManager.prepareOpeningSegments(result.opening_speech_segments);
                }

                this.updateOverlayProgress(65, '构建游戏世界...');
                this.gameId = result.game_id;

                this.updateOverlayProgress(80, '加载角色数据...');
                await this.refreshGameState();

                // 刷新存档列表，确保新创建的游戏出现在列表中
                await this.loadGameList();

                this.updateOverlayProgress(90, '生成开场故事...');
                this.addMessage('新游戏开始！', 'success');

                // ----- 开场叙述 -----
                // narrative：addMessage 时通过 suppressAutoTTS 跳过常规自动朗读，
                // 然后用 playOpeningSegment 触发开场专用播放（绕过白名单 + 携带按钮）
                const openingSegments = Array.isArray(result.opening_speech_segments)
                    ? result.opening_speech_segments
                    : [];
                const narrativeSegment = openingSegments.find(
                    seg => seg && seg.id === 'opening_narrative' && seg.text
                );

                if (result.narrative) {
                    const narrativeBtn = this.addMessage(result.narrative, 'narrative', {
                        suppressAutoTTS: Boolean(narrativeSegment && this.ttsManager?.isAvailable()),
                    });
                    if (narrativeSegment && this.ttsManager?.isAvailable()) {
                        this.ttsManager.playOpeningSegment(
                            narrativeSegment.text,
                            narrativeSegment.category || 'narrative',
                            {
                                button: narrativeBtn,
                                prefetchUrl: narrativeSegment.prefetch_url,
                                prefetchKey: narrativeSegment.cache_key,
                            }
                        );
                    }
                }

                // ----- 开场任务 -----
                const openingQuestSegment = openingSegments.find(
                    seg => seg && seg.id === 'opening_quest' && seg.text
                );
                if (openingQuestSegment) {
                    const questBtn = this.addMessage(openingQuestSegment.text, 'event', {
                        suppressAutoTTS: true,
                    });
                    if (this.ttsManager?.isAvailable()) {
                        this.ttsManager.playOpeningSegment(
                            openingQuestSegment.text,
                            openingQuestSegment.category || 'event',
                            {
                                button: questBtn,
                                prefetchUrl: openingQuestSegment.prefetch_url,
                                prefetchKey: openingQuestSegment.cache_key,
                            }
                        );
                    }
                }

                this.updateOverlayProgress(100, '准备就绪！');

                // 延迟显示完成状态
                await new Promise(resolve => setTimeout(resolve, 1000));

                // 隐藏模态框和主菜单，显示游戏界面
                document.getElementById('new-game-modal').style.display = 'none';
                document.getElementById('main-menu').style.display = 'none';
                document.getElementById('game-interface').style.display = 'grid';

                // 触发迷雾canvas初始化（游戏界面现在可见了）
                if (typeof window.initializeFogCanvas === 'function') {
                    setTimeout(() => window.initializeFogCanvas(), 100);
                }

                this.hideFullscreenOverlay();
            } else {
                this.addMessage('创建游戏失败', 'error');
                this.hideFullscreenOverlay();
            }
        } catch (error) {
            console.error('Create game error:', error);
            this.addMessage('创建游戏时发生错误', 'error');
            this.hideFullscreenOverlay();
        } finally {
            this.setLoading(false);
        }
    },

    /**
     * 根据错误信息生成幽默的安全提示
     */
    getSecurityErrorMessage(errorMsg, playerName) {
        const lowerError = errorMsg.toLowerCase();

        // SQL注入检测
        if (lowerError.includes('sql') || lowerError.includes('drop') || lowerError.includes('table')) {
            return [
                '🛡️ 哎呀！检测到SQL注入尝试！',
                '看来有人想当黑客呢~ 不过我们的防护可不是吃素的！',
                '提示：这里是地牢冒险游戏，不是数据库管理系统哦 😏'
            ];
        }

        // XSS攻击检测
        if (lowerError.includes('xss') || lowerError.includes('script') || lowerError.includes('<')) {
            return [
                '🛡️ 检测到XSS攻击尝试！',
                '想在我们的游戏里运行脚本？真是个大胆的想法！',
                '不过抱歉，我们只接受勇者的名字，不接受代码 😎'
            ];
        }

        // 路径遍历检测
        if (lowerError.includes('path') || lowerError.includes('traversal') || lowerError.includes('../')) {
            return [
                '🛡️ 路径遍历攻击被拦截！',
                '想去 /etc/passwd 探险？这里只有地牢可以探索哦！',
                '建议：把你的黑客技能用在游戏里打怪上吧 🗡️'
            ];
        }

        // 命令注入检测
        if (lowerError.includes('command') || lowerError.includes('injection') || lowerError.includes('rm -rf')) {
            return [
                '🛡️ 命令注入尝试已阻止！',
                'rm -rf？在这里唯一能删除的只有怪物的HP！',
                '温馨提示：请用正常的角色名称，谢谢合作 🙃'
            ];
        }

        // 长度超限
        if (lowerError.includes('20') || lowerError.includes('长度') || lowerError.includes('字符')) {
            return [
                '📏 角色名称太长啦！',
                `"${playerName}" 这个名字太长了，连地牢的告示牌都写不下！`,
                '请使用1-20个字符的名称（中文、英文、数字都可以）'
            ];
        }

        // 非法字符
        if (lowerError.includes('不允许') || lowerError.includes('非法') || lowerError.includes('字符')) {
            return [
                '⚠️ 包含非法字符！',
                '你的名字里有些奇怪的符号，连魔法师都认不出来！',
                '建议使用：中文、英文、数字、下划线、空格等常见字符'
            ];
        }

        // 空名称
        if (lowerError.includes('空') || lowerError.includes('empty')) {
            return [
                '❓ 名字不能为空！',
                '没有名字的勇者？这可不行！',
                '就算是"无名氏"也得有个名字啊 😅'
            ];
        }

        // 默认提示
        return [
            '🛡️ 输入验证失败！',
            '你的输入似乎有些问题，我们的安全系统拦截了它。',
            '请使用正常的角色名称（1-20个字符，支持中英文）'
        ];
    },

    /**
     * 显示安全警告对话框
     */
    showSecurityAlert(messages, technicalError) {
        // 创建警告对话框
        const alertDiv = document.createElement('div');
        alertDiv.className = 'security-alert-overlay';
        alertDiv.innerHTML = `
            <div class="security-alert-box">
                <div class="security-alert-icon">🛡️</div>
                <div class="security-alert-title">${messages[0]}</div>
                <div class="security-alert-message">${messages[1]}</div>
                <div class="security-alert-hint">${messages[2]}</div>
                <div class="security-alert-technical">
                    <details>
                        <summary>技术详情</summary>
                        <code>${technicalError}</code>
                    </details>
                </div>
                <button class="security-alert-button" onclick="this.closest('.security-alert-overlay').remove()">
                    我知道了
                </button>
            </div>
        `;

        document.body.appendChild(alertDiv);

        // 添加样式（如果还没有）
        if (!document.getElementById('security-alert-styles')) {
            const style = document.createElement('style');
            style.id = 'security-alert-styles';
            style.textContent = `
                .security-alert-overlay {
                    position: fixed;
                    top: 0;
                    left: 0;
                    right: 0;
                    bottom: 0;
                    background: rgba(0, 0, 0, 0.8);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    z-index: 10000;
                    animation: fadeIn 0.3s ease;
                }

                .security-alert-box {
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    border-radius: 20px;
                    padding: 40px;
                    max-width: 500px;
                    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
                    animation: slideIn 0.3s ease;
                    text-align: center;
                    color: white;
                }

                .security-alert-icon {
                    font-size: 64px;
                    margin-bottom: 20px;
                    animation: bounce 0.6s ease;
                }

                .security-alert-title {
                    font-size: 24px;
                    font-weight: bold;
                    margin-bottom: 15px;
                    text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.3);
                }

                .security-alert-message {
                    font-size: 18px;
                    margin-bottom: 15px;
                    line-height: 1.6;
                }

                .security-alert-hint {
                    font-size: 14px;
                    opacity: 0.9;
                    margin-bottom: 20px;
                    padding: 15px;
                    background: rgba(255, 255, 255, 0.1);
                    border-radius: 10px;
                    border-left: 4px solid #ffd700;
                }

                .security-alert-technical {
                    margin: 20px 0;
                    text-align: left;
                }

                .security-alert-technical details {
                    background: rgba(0, 0, 0, 0.2);
                    padding: 10px;
                    border-radius: 8px;
                    cursor: pointer;
                }

                .security-alert-technical summary {
                    font-size: 12px;
                    opacity: 0.8;
                    user-select: none;
                }

                .security-alert-technical code {
                    display: block;
                    margin-top: 10px;
                    padding: 10px;
                    background: rgba(0, 0, 0, 0.3);
                    border-radius: 5px;
                    font-family: 'Courier New', monospace;
                    font-size: 12px;
                    word-break: break-all;
                    color: #ff6b6b;
                }

                .security-alert-button {
                    background: white;
                    color: #667eea;
                    border: none;
                    padding: 15px 40px;
                    border-radius: 25px;
                    font-size: 16px;
                    font-weight: bold;
                    cursor: pointer;
                    transition: all 0.3s ease;
                    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
                }

                .security-alert-button:hover {
                    transform: translateY(-2px);
                    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.3);
                }

                @keyframes fadeIn {
                    from { opacity: 0; }
                    to { opacity: 1; }
                }

                @keyframes slideIn {
                    from {
                        transform: translateY(-50px);
                        opacity: 0;
                    }
                    to {
                        transform: translateY(0);
                        opacity: 1;
                    }
                }

                @keyframes bounce {
                    0%, 100% { transform: translateY(0); }
                    50% { transform: translateY(-10px); }
                }
            `;
            document.head.appendChild(style);
        }
    }
});
