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
                    saveElement.innerHTML = `
                        <h4>${save.player_name} (等级 ${save.player_level})</h4>
                        <p>${save.map_name} - 回合 ${save.turn_count}</p>
                        <p>最后保存: ${new Date(save.last_saved).toLocaleString()}</p>
                        <div class="save-item-buttons">
                            <button onclick="game.loadGame('${save.id}')">
                                <i class="material-icons">play_arrow</i>
                                加载
                            </button>
                            <button onclick="game.exportSave('${save.id}')">
                                <i class="material-icons">file_download</i>
                                导出
                            </button>
                            <button onclick="game.deleteGame('${save.id}')">
                                <i class="material-icons">delete</i>
                                删除
                            </button>
                        </div>
                    `;
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
            const response = await fetch(`/api/load/${saveId}`, {
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
                this.addMessage('游戏已加载', 'success');

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

            this.updateOverlayProgress(45, 'AI正在生成地下城...');
            const result = await response.json();

            if (result.success) {
                this.updateOverlayProgress(65, '构建游戏世界...');
                this.gameId = result.game_id;

                this.updateOverlayProgress(80, '加载角色数据...');
                await this.refreshGameState();

                this.updateOverlayProgress(90, '生成开场故事...');
                this.addMessage('新游戏开始！', 'success');

                // 显示叙述文本
                if (result.narrative) {
                    this.addMessage(result.narrative, 'narrative');
                }

                this.updateOverlayProgress(100, '准备就绪！');

                // 延迟显示完成状态
                await new Promise(resolve => setTimeout(resolve, 1000));

                // 隐藏模态框和主菜单，显示游戏界面
                document.getElementById('new-game-modal').style.display = 'none';
                document.getElementById('main-menu').style.display = 'none';
                document.getElementById('game-interface').style.display = 'block';

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
    }
});
