// Labyrinthia AI - 遮罩和加载管理模块
// 包含所有遮罩显示、加载状态管理逻辑

// 扩展核心游戏类，添加遮罩和加载管理功能
Object.assign(LabyrinthiaGame.prototype, {
    
    setLoading(loading) {
        this.isLoading = loading;
        const loadingElements = document.querySelectorAll('.loading-indicator');
        loadingElements.forEach(el => {
            el.style.display = loading ? 'inline-block' : 'none';
        });

        // 禁用/启用控制按钮
        const controlButtons = document.querySelectorAll('.control-btn, .dir-btn');
        controlButtons.forEach(btn => {
            btn.disabled = loading;
        });

        // 当显示"处理中..."时，自动显示LLM遮罩
        if (loading) {
            // 检查是否已经有遮罩显示，避免重复显示
            const existingOverlay = document.getElementById('partial-overlay');
            if (!existingOverlay || existingOverlay.style.display === 'none') {
                this.showLLMOverlay('处理中');
            }
        } else {
            // 当loading结束时，隐藏LLM遮罩
            this.hideLLMOverlay();
        }
    },

    showFullscreenOverlay(title, subtitle, status = '') {
        const overlay = document.getElementById('fullscreen-overlay');
        const titleEl = document.getElementById('overlay-title');
        const subtitleEl = document.getElementById('overlay-subtitle');
        const statusEl = document.getElementById('overlay-status');
        const progressBar = document.getElementById('overlay-progress-bar');

        if (overlay && titleEl && subtitleEl && statusEl) {
            titleEl.textContent = title;
            subtitleEl.textContent = subtitle;
            statusEl.textContent = status;
            progressBar.style.width = '0%';
            overlay.classList.add('show');

            // 启动 动态提示系统
            this.startDynamicTips();
        }
    },

    startDynamicTips() {
        const tips = [
            '💡 提示：游戏世界由AI实时生成，每次冒险都是独一无二的',
            '🎮 提示：您可以通过点击地图瓦片来移动角色',
            '⚔️ 提示：战斗策略会影响您的生存几率',
            '🗝️ 提示：探索每个角落，寻找隐藏的宝藏和秘密',
            '📜 提示：任务系统会根据您的选择动态调整',
            '🏰 提示：每个楼层都有独特的挑战和奖励',
            '🎯 提示：合理使用物品可以在关键时刻救您一命',
            '🌟 提示：与AI的互动越多，故事就越精彩',
            '🗝️ 提示：长时间的存档注意及时导出存档'
        ];

        const tipElement = document.getElementById('overlay-tip');
        if (!tipElement) return;

        let currentTipIndex = 0;

        // 清除之前的定时器
        if (this.tipInterval) {
            clearInterval(this.tipInterval);
        }

        this.tipInterval = setInterval(() => {
            currentTipIndex = (currentTipIndex + 1) % tips.length;
            tipElement.textContent = tips[currentTipIndex];
            tipElement.style.animation = 'none';
            setTimeout(() => {
                tipElement.style.animation = 'tipFade 4s ease-in-out infinite';
            }, 50);
        }, 4000);
    },

    hideFullscreenOverlay() {
        const overlay = document.getElementById('fullscreen-overlay');
        if (overlay) {
            overlay.classList.remove('show');
        }

        // 清理动态提示定时器
        if (this.tipInterval) {
            clearInterval(this.tipInterval);
            this.tipInterval = null;
        }
    },

    updateOverlayProgress(percentage, text = null) {
        // 更新全屏遮罩进度
        const fullProgressBar = document.getElementById('overlay-progress-bar');
        const fullStatusEl = document.getElementById('overlay-status');

        if (fullProgressBar) {
            fullProgressBar.style.width = `${Math.min(100, Math.max(0, percentage))}%`;
        }

        if (fullStatusEl && text) {
            fullStatusEl.textContent = text;
        }

        // 更新部分遮罩进度
        const partialProgressFill = document.getElementById('partial-progress-fill');
        const partialProgressText = document.getElementById('partial-progress-text');

        if (partialProgressFill) {
            partialProgressFill.style.width = `${percentage}%`;
        }
        if (partialProgressText && text) {
            partialProgressText.textContent = text;
        }
    },

    showLLMOverlay(action = '思考中') {
        const titles = {
            'move': 'AI 正在分析环境',
            'attack': 'AI 正在计算战斗',
            'interact': 'AI 正在处理选择',
            'rest': 'AI 正在恢复状态',
            'choice': 'AI 正在处理选择',
            'default': 'AI 正在思考'
        };

        const subtitles = {
            'move': '分析地形和潜在威胁...',
            'attack': '计算最佳攻击策略...',
            'interact': '分析您的选择并生成结果...',
            'rest': '评估休息的安全性...',
            'choice': '分析您的选择并更新游戏状态...',
            'default': '处理您的请求...'
        };

        const title = titles[action] || titles['default'];
        const subtitle = subtitles[action] || subtitles['default'];

        // 使用新的部分遮罩而不是全屏遮罩
        this.showPartialOverlay(title, subtitle, '正在与AI通信...');

        // 模拟进度更新
        let progress = 0;
        const progressInterval = setInterval(() => {
            progress += Math.random() * 15;
            if (progress >= 90) {
                progress = 90;
                clearInterval(progressInterval);
            }
            this.updateOverlayProgress(progress);
        }, 200);

        // 存储interval以便后续清理
        this.currentProgressInterval = progressInterval;
    },

    hideLLMOverlay() {
        if (this.currentProgressInterval) {
            clearInterval(this.currentProgressInterval);
            this.currentProgressInterval = null;
        }

        // 完成进度条
        this.updateOverlayProgress(100, '完成！');

        // 延迟隐藏以显示完成状态
        setTimeout(() => {
            this.hidePartialOverlay();
        }, 500);
    },

    // 新增：部分遮罩方法（只遮住地图区域）
    showPartialOverlay(title, subtitle, description) {
        let overlay = document.getElementById('partial-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'partial-overlay';
            overlay.className = 'partial-overlay';
            overlay.innerHTML = `
                <div class="partial-overlay-content">
                    <div class="overlay-header">
                        <h3 id="partial-overlay-title">${title}</h3>
                        <p id="partial-overlay-subtitle">${subtitle}</p>
                    </div>
                    <div class="overlay-body">
                        <div class="progress-container">
                            <div class="progress-bar">
                                <div class="progress-fill" id="partial-progress-fill"></div>
                            </div>
                            <p class="progress-text" id="partial-progress-text">${description}</p>
                        </div>
                    </div>
                </div>
            `;
            document.body.appendChild(overlay);
        } else {
            document.getElementById('partial-overlay-title').textContent = title;
            document.getElementById('partial-overlay-subtitle').textContent = subtitle;
            document.getElementById('partial-progress-text').textContent = description;
            document.getElementById('partial-progress-fill').style.width = '0%';
        }

        overlay.style.display = 'flex';
    },

    hidePartialOverlay() {
        const overlay = document.getElementById('partial-overlay');
        if (overlay) {
            overlay.style.display = 'none';
        }
    },


});
