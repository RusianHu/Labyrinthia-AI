// Labyrinthia AI - 游戏前端脚本

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
    }

    async checkDebugMode() {
        try {
            const response = await fetch('/api/config');
            const config = await response.json();
            this.debugMode = config.game?.show_llm_debug || false;

            const debugFab = document.getElementById('debug-fab');
            if (debugFab) {
                if (this.debugMode) {
                    debugFab.classList.remove('hidden');
                } else {
                    debugFab.classList.add('hidden');
                }
            }
        } catch (error) {
            console.error('Failed to check debug mode:', error);
        }
    }

    toggleDebugPanel() {
        const debugPanel = document.getElementById('debug-panel');
        if (debugPanel) {
            debugPanel.classList.toggle('show');
            this.updateDebugInfo();
        }
    }

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
    }
    
    setupEventListeners() {
        // 方向控制按钮
        document.querySelectorAll('.dir-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const direction = e.target.dataset.direction;
                if (direction) {
                    this.movePlayer(direction);
                }
            });
        });
        
        // 键盘控制
        document.addEventListener('keydown', (e) => {
            if (this.gameId) {
                this.handleKeyPress(e);
            }
        });
        
        // 其他控制按钮
        document.getElementById('btn-rest')?.addEventListener('click', () => {
            this.performAction('rest');
        });
        
        document.getElementById('btn-save')?.addEventListener('click', () => {
            this.saveGame();
        });
        
        document.getElementById('btn-new-game')?.addEventListener('click', () => {
            this.showNewGameModal();
        });
        
        // 模态框控制
        document.querySelectorAll('.close').forEach(closeBtn => {
            closeBtn.addEventListener('click', (e) => {
                e.target.closest('.modal').style.display = 'none';
            });
        });
        
        // 点击模态框外部关闭
        window.addEventListener('click', (e) => {
            if (e.target.classList.contains('modal')) {
                e.target.style.display = 'none';
            }
        });
    }
    
    handleKeyPress(e) {
        const keyMap = {
            'ArrowUp': 'north',
            'ArrowDown': 'south',
            'ArrowLeft': 'west',
            'ArrowRight': 'east',
            'w': 'north',
            's': 'south',
            'a': 'west',
            'd': 'east',
            'q': 'northwest',
            'e': 'northeast',
            'z': 'southwest',
            'c': 'southeast',
            'r': 'rest',
            ' ': 'rest'
        };
        
        const action = keyMap[e.key.toLowerCase()];
        if (action) {
            e.preventDefault();
            if (action === 'rest') {
                this.performAction('rest');
            } else {
                this.movePlayer(action);
            }
        }
    }
    
    async movePlayer(direction) {
        if (this.isLoading) return;
        
        await this.performAction('move', { direction });
    }
    
    async performAction(action, parameters = {}) {
        if (this.isLoading || !this.gameId) return;

        // 检查是否需要显示特定的LLM遮罩（特殊地形或事件触发时）
        const needsSpecificLLMOverlay = this.shouldShowLLMOverlay(action, parameters);

        // 如果需要特定的LLM遮罩，先显示它，然后再设置loading
        if (needsSpecificLLMOverlay) {
            this.showLLMOverlay(action);
            this.isLoading = true;
            // 禁用控制按钮但不显示通用的loading indicator
            const controlButtons = document.querySelectorAll('.control-btn, .dir-btn');
            controlButtons.forEach(btn => {
                btn.disabled = true;
            });
        } else {
            // 普通情况，使用标准的loading（会自动显示遮罩）
            this.setLoading(true);
        }

        try {
            const requestData = {
                game_id: this.gameId,
                action: action,
                parameters: parameters
            };

            // 记录调试信息
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

            // 记录响应调试信息
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
                // 检查后端是否指示需要LLM遮罩（用于怪物攻击等情况）
                const backendNeedsLLMOverlay = result.llm_interaction_required;
                let showedBackendOverlay = false;

                if (backendNeedsLLMOverlay && !needsSpecificLLMOverlay) {
                    this.showLLMOverlay('处理中');
                    showedBackendOverlay = true;
                }

                // 更新游戏状态
                await this.refreshGameState();

                // 添加消息
                if (result.message) {
                    this.addMessage(result.message, 'action');
                }

                if (result.events) {
                    result.events.forEach(event => {
                        // 战斗伤害消息使用特殊样式
                        const messageType = event.includes('造成') || event.includes('攻击') ? 'combat' : 'system';
                        this.addMessage(event, messageType);
                    });
                }

                if (result.narrative) {
                    this.addMessage(result.narrative, 'narrative');
                }

                // 检查游戏是否结束
                if (result.game_over) {
                    this.handleGameOver(result.game_over_reason);
                }

                // 如果显示了后端指示的LLM遮罩，现在隐藏它
                if (showedBackendOverlay) {
                    this.hideLLMOverlay();
                }
            } else {
                this.addMessage(result.message || '行动失败', 'error');
            }
        } catch (error) {
            console.error('Action error:', error);
            this.addMessage('网络错误，请重试', 'error');
        } finally {
            // 隐藏特定的LLM遮罩
            if (needsSpecificLLMOverlay) {
                this.hideLLMOverlay();
                // 重新启用控制按钮
                const controlButtons = document.querySelectorAll('.control-btn, .dir-btn');
                controlButtons.forEach(btn => {
                    btn.disabled = false;
                });
                this.isLoading = false;
            } else {
                // 普通情况，使用标准的setLoading(false)
                this.setLoading(false);
            }
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

    async loadConfig() {
        try {
            const response = await fetch('/api/config');
            this.config = await response.json();
        } catch (error) {
            console.error('Failed to load config:', error);
            this.config = { debug_mode: false }; // 默认配置
        }
    }
    
    updateUI() {
        if (!this.gameState) return;

        this.updateCharacterStats();
        this.updateMap();
        this.updateInventory();
        this.updateQuests();
        this.updateControlPanel();
    }

    renderGame() {
        this.updateUI();
    }
    
    updateCharacterStats() {
        const player = this.gameState.player;
        const stats = player.stats;
        
        // 更新基础信息
        document.getElementById('player-name').textContent = player.name;
        document.getElementById('player-level').textContent = stats.level;
        document.getElementById('player-class').textContent = player.character_class;
        
        // 更新生命值
        document.getElementById('hp-current').textContent = stats.hp;
        document.getElementById('hp-max').textContent = stats.max_hp;
        const hpPercent = (stats.hp / stats.max_hp) * 100;
        document.getElementById('hp-bar').style.width = `${hpPercent}%`;
        
        // 更新法力值
        document.getElementById('mp-current').textContent = stats.mp;
        document.getElementById('mp-max').textContent = stats.max_mp;
        const mpPercent = (stats.mp / stats.max_mp) * 100;
        document.getElementById('mp-bar').style.width = `${mpPercent}%`;
        
        // 更新经验值
        const expNeeded = stats.level * 1000;
        const expPercent = (stats.experience / expNeeded) * 100;
        document.getElementById('exp-bar').style.width = `${expPercent}%`;
        document.getElementById('exp-text').textContent = `${stats.experience}/${expNeeded}`;
        
        // 更新位置
        document.getElementById('player-position').textContent = 
            `(${player.position[0]}, ${player.position[1]})`;
    }
    
    updateMap() {
        const mapContainer = document.getElementById('map-grid');
        const gameMap = this.gameState.current_map;
        const player = this.gameState.player;
        
        // 设置网格样式
        mapContainer.style.gridTemplateColumns = `repeat(${gameMap.width}, 24px)`;
        mapContainer.innerHTML = '';
        
        // 创建地图瓦片
        for (let y = 0; y < gameMap.height; y++) {
            for (let x = 0; x < gameMap.width; x++) {
                const tileKey = `${x},${y}`;
                const tileData = gameMap.tiles[tileKey];
                
                const tile = document.createElement('div');
                tile.className = 'map-tile';
                tile.dataset.x = x;
                tile.dataset.y = y;

                // 添加悬停事件
                tile.addEventListener('mouseenter', (e) => {
                    this.showTileTooltip(e, tileData, x, y);
                    this.handleTileHover(x, y, tileData, true);
                });

                tile.addEventListener('mouseleave', () => {
                    this.hideTileTooltip();
                    this.handleTileHover(x, y, tileData, false);
                });

                // 添加点击移动事件
                tile.addEventListener('click', () => {
                    this.handleTileClick(x, y, tileData);
                });
                
                if (tileData) {
                    // 设置地形样式
                    tile.classList.add(`terrain-${tileData.terrain}`);
                    
                    // 设置可见性
                    if (tileData.is_explored) {
                        tile.classList.add('tile-explored');
                    } else {
                        tile.classList.add('tile-unexplored');
                    }
                    
                    if (tileData.is_visible) {
                        tile.classList.add('tile-visible');
                    }
                    
                    // 添加角色
                    if (tileData.character_id === player.id) {
                        const playerIcon = document.createElement('div');
                        playerIcon.className = 'character-player';
                        tile.appendChild(playerIcon);
                    } else if (tileData.character_id) {
                        // 查找怪物
                        const monster = this.gameState.monsters.find(m => m.id === tileData.character_id);
                        if (monster) {
                            const monsterIcon = document.createElement('div');
                            monsterIcon.className = 'character-monster';
                            monsterIcon.title = monster.name;
                            monsterIcon.addEventListener('click', () => {
                                this.attackMonster(monster.id);
                            });
                            tile.appendChild(monsterIcon);
                        }
                    }
                }
                
                mapContainer.appendChild(tile);
            }
        }
    }
    
    updateInventory() {
        const inventoryGrid = document.getElementById('inventory-grid');
        const inventory = this.gameState.player.inventory;

        inventoryGrid.innerHTML = '';

        // 创建物品栏格子（4x4）
        for (let i = 0; i < 16; i++) {
            const slot = document.createElement('div');
            slot.className = 'inventory-slot';
            slot.dataset.slot = i;

            if (i < inventory.length) {
                const item = inventory[i];
                slot.classList.add('has-item');
                slot.title = `${item.name}\n${item.description}`;
                slot.textContent = item.name.charAt(0).toUpperCase();

                slot.addEventListener('click', () => {
                    this.showItemUseDialog(item);
                });
            }

            inventoryGrid.appendChild(slot);
        }
    }
    
    updateQuests() {
        const questList = document.getElementById('quest-list');
        const quests = this.gameState.quests.filter(q => q.is_active);

        questList.innerHTML = '';

        quests.forEach(quest => {
            const questElement = document.createElement('div');
            questElement.className = 'quest-item';

            // 构建任务HTML
            let questHTML = `
                <h4>${quest.title}</h4>
                <p>${quest.description}</p>
            `;

            // 根据配置显示进度百分比
            if (this.config && this.config.show_quest_progress && quest.progress_percentage !== undefined) {
                questHTML += `
                    <div class="quest-progress">
                        <div class="progress-bar-small">
                            <div class="progress-fill-small" style="width: ${quest.progress_percentage}%"></div>
                        </div>
                        <span class="progress-text-small">进度: ${quest.progress_percentage.toFixed(1)}%</span>
                    </div>
                `;
            }

            questHTML += `
                <div class="quest-objectives">
                    ${quest.objectives.map((obj, index) =>
                        `<div class="objective ${quest.completed_objectives[index] ? 'completed' : ''}">
                            ${quest.completed_objectives[index] ? '✓' : '○'} ${obj}
                        </div>`
                    ).join('')}
                </div>
            `;

            questElement.innerHTML = questHTML;
            questList.appendChild(questElement);
        });
    }
    
    async attackMonster(monsterId) {
        await this.performAction('attack', { target_id: monsterId });
    }

    handleTileClick(x, y, tileData) {
        if (this.isLoading) return;

        const player = this.gameState.player;
        const playerX = player.position[0];
        const playerY = player.position[1];

        // 检查是否点击了怪物
        if (tileData.character_id && tileData.character_id !== player.id) {
            const monster = this.gameState.monsters.find(m => m.id === tileData.character_id);
            if (monster) {
                // 检查攻击距离
                const distance = Math.abs(x - playerX) + Math.abs(y - playerY);
                if (distance <= 1) {
                    this.attackMonster(monster.id);
                    return;
                } else {
                    this.addMessage('目标距离太远，无法攻击', 'error');
                    return;
                }
            }
        }

        // 检查是否可以移动到该位置
        if (this.canMoveToTile(x, y, playerX, playerY)) {
            this.moveToPosition(x, y);
        }
    }

    canMoveToTile(targetX, targetY, playerX, playerY, showMessages = true) {
        // 检查是否为相邻格子（包括对角线）
        const dx = Math.abs(targetX - playerX);
        const dy = Math.abs(targetY - playerY);

        if (dx > 1 || dy > 1 || (dx === 0 && dy === 0)) {
            return false;
        }

        // 检查目标瓦片
        const tileKey = `${targetX},${targetY}`;
        const tileData = this.gameState.current_map.tiles[tileKey];

        if (!tileData) {
            return false;
        }

        // 检查地形
        if (tileData.terrain === 'wall') {
            if (showMessages) {
                this.addMessage('无法穿过墙壁', 'error');
            }
            return false;
        }

        // 检查是否有其他角色
        if (tileData.character_id && tileData.character_id !== this.gameState.player.id) {
            if (showMessages) {
                this.addMessage('该位置已被占据', 'error');
            }
            return false;
        }

        return true;
    }

    async moveToPosition(x, y) {
        const playerX = this.gameState.player.position[0];
        const playerY = this.gameState.player.position[1];

        // 计算移动方向
        const dx = x - playerX;
        const dy = y - playerY;

        let direction = '';
        if (dx === 0 && dy === -1) direction = 'north';
        else if (dx === 0 && dy === 1) direction = 'south';
        else if (dx === -1 && dy === 0) direction = 'west';
        else if (dx === 1 && dy === 0) direction = 'east';
        else if (dx === -1 && dy === -1) direction = 'northwest';
        else if (dx === 1 && dy === -1) direction = 'northeast';
        else if (dx === -1 && dy === 1) direction = 'southwest';
        else if (dx === 1 && dy === 1) direction = 'southeast';

        if (direction) {
            await this.movePlayer(direction);
        }
    }
    
    showItemUseDialog(item) {
        const dialog = document.getElementById('item-use-dialog');
        const nameElement = document.getElementById('item-use-name');
        const descriptionElement = document.getElementById('item-use-description');
        const usageElement = document.getElementById('item-use-usage');
        const confirmButton = document.getElementById('confirm-use-item');
        const cancelButton = document.getElementById('cancel-use-item');

        // 填充物品信息
        nameElement.textContent = item.name;
        descriptionElement.textContent = item.description;
        usageElement.textContent = item.usage_description || '使用方法未知';

        // 设置按钮事件
        confirmButton.onclick = () => {
            this.hideItemUseDialog();
            this.useItem(item.id);
        };

        cancelButton.onclick = () => {
            this.hideItemUseDialog();
        };

        // 显示对话框
        dialog.style.display = 'flex';
    }

    hideItemUseDialog() {
        const dialog = document.getElementById('item-use-dialog');
        dialog.style.display = 'none';
    }

    async useItem(itemId) {
        await this.performAction('use_item', { item_id: itemId });
    }

    showTileTooltip(event, tileData, x, y) {
        const tooltip = document.getElementById('tile-tooltip');
        if (!tooltip) return;

        let tooltipText = `位置: (${x}, ${y})\n`;

        if (tileData) {
            // 地形信息
            const terrainNames = {
                'floor': '地板',
                'wall': '墙壁',
                'door': '门',
                'trap': '陷阱',
                'treasure': '宝藏',
                'stairs_up': '上楼梯',
                'stairs_down': '下楼梯',
                'water': '水',
                'lava': '岩浆',
                'pit': '深坑'
            };

            tooltipText += `地形: ${terrainNames[tileData.terrain] || tileData.terrain}\n`;

            // 探索状态
            if (tileData.is_explored) {
                tooltipText += '状态: 已探索\n';
            } else {
                tooltipText += '状态: 未探索\n';
            }

            // 角色信息
            if (tileData.character_id) {
                if (tileData.character_id === this.gameState.player.id) {
                    const player = this.gameState.player;
                    tooltipText += `角色: ${player.name} (玩家)\n`;
                    tooltipText += `生命值: ${player.stats.hp}/${player.stats.max_hp}\n`;
                    tooltipText += `法力值: ${player.stats.mp}/${player.stats.max_mp}\n`;
                    tooltipText += `等级: ${player.stats.level}\n`;
                } else {
                    const monster = this.gameState.monsters.find(m => m.id === tileData.character_id);
                    if (monster) {
                        tooltipText += `怪物: ${monster.name}\n`;
                        tooltipText += `生命值: ${monster.stats.hp}/${monster.stats.max_hp}\n`;
                        if (monster.challenge_rating) {
                            tooltipText += `挑战等级: ${monster.challenge_rating}\n`;
                        }
                    }
                }
            }

            // 物品信息
            if (tileData.items && tileData.items.length > 0) {
                tooltipText += `物品: ${tileData.items.length}个\n`;
            }

            // 事件信息（如果有且不隐藏）
            if (tileData.has_event && !tileData.is_event_hidden) {
                const eventNames = {
                    'combat': '战斗',
                    'treasure': '宝藏',
                    'story': '故事',
                    'trap': '陷阱',
                    'mystery': '神秘'
                };
                tooltipText += `事件: ${eventNames[tileData.event_type] || tileData.event_type}\n`;

                if (tileData.event_triggered) {
                    tooltipText += '(已触发)\n';
                }
            }
        } else {
            tooltipText += '地形: 未知\n';
        }

        tooltip.textContent = tooltipText.trim();
        tooltip.classList.add('show');

        // 定位工具提示
        const rect = event.target.getBoundingClientRect();
        tooltip.style.left = `${rect.left + rect.width / 2}px`;
        tooltip.style.top = `${rect.top - tooltip.offsetHeight - 10}px`;

        // 确保工具提示不超出屏幕边界
        const tooltipRect = tooltip.getBoundingClientRect();
        if (tooltipRect.left < 0) {
            tooltip.style.left = '10px';
        }
        if (tooltipRect.right > window.innerWidth) {
            tooltip.style.left = `${window.innerWidth - tooltipRect.width - 10}px`;
        }
        if (tooltipRect.top < 0) {
            tooltip.style.top = `${rect.bottom + 10}px`;
        }
    }

    hideTileTooltip() {
        const tooltip = document.getElementById('tile-tooltip');
        if (tooltip) {
            tooltip.classList.remove('show');
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
    }

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
        }
    }

    hideFullscreenOverlay() {
        const overlay = document.getElementById('fullscreen-overlay');
        if (overlay) {
            overlay.classList.remove('show');
        }
    }

    updateOverlayProgress(progress, status = '') {
        const progressBar = document.getElementById('overlay-progress-bar');
        const statusEl = document.getElementById('overlay-status');

        if (progressBar) {
            progressBar.style.width = `${Math.min(100, Math.max(0, progress))}%`;
        }

        if (statusEl && status) {
            statusEl.textContent = status;
        }
    }

    showLLMOverlay(action = '思考中') {
        const titles = {
            'move': 'AI 正在分析环境',
            'attack': 'AI 正在计算战斗',
            'interact': 'AI 正在处理交互',
            'rest': 'AI 正在恢复状态',
            'default': 'AI 正在思考'
        };

        const subtitles = {
            'move': '分析地形和潜在威胁...',
            'attack': '计算最佳攻击策略...',
            'interact': '理解环境中的元素...',
            'rest': '评估休息的安全性...',
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
    }

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
    }

    shouldShowLLMOverlay(action, parameters) {
        // 检查是否需要显示LLM遮罩
        // 主要在以下情况显示：
        // 1. 移动到特殊地形（但不包括楼梯，楼梯只是提示）
        // 2. 交互行动
        // 3. 攻击行动
        // 4. 休息时可能触发事件

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
            // 休息时可能触发随机事件
            return Math.random() < 0.3; // 30%概率显示遮罩
        }

        return false;
    }

    handleTileHover(x, y, tileData, isEntering) {
        if (!this.gameState || !this.gameState.player) return;

        const player = this.gameState.player;
        const playerX = player.position[0];
        const playerY = player.position[1];

        if (isEntering) {
            // 清除之前的高亮
            this.clearTileHighlights();

            // 检查是否可以移动到该位置（不显示错误消息）
            if (this.canMoveToTile(x, y, playerX, playerY, false)) {
                this.highlightMovableTile(x, y);
                this.highlightMovementPath(playerX, playerY, x, y);
            }

            // 检查是否可以攻击该位置的怪物
            if (tileData && tileData.character_id && tileData.character_id !== player.id) {
                const monster = this.gameState.monsters.find(m => m.id === tileData.character_id);
                if (monster) {
                    const distance = Math.abs(x - playerX) + Math.abs(y - playerY);
                    if (distance <= 1) {
                        this.highlightAttackableTile(x, y);
                    }
                }
            }

            this.hoveredTile = { x, y };
        } else {
            // 鼠标离开时清除高亮
            this.clearTileHighlights();
            this.hoveredTile = null;
        }
    }

    highlightMovableTile(x, y) {
        const tile = document.querySelector(`[data-x="${x}"][data-y="${y}"]`);
        if (tile) {
            tile.classList.add('movable');
            this.highlightedTiles.push({ element: tile, type: 'movable' });
        }
    }

    highlightAttackableTile(x, y) {
        const tile = document.querySelector(`[data-x="${x}"][data-y="${y}"]`);
        if (tile) {
            tile.classList.add('attackable');
            this.highlightedTiles.push({ element: tile, type: 'attackable' });
        }
    }

    highlightMovementPath(fromX, fromY, toX, toY) {
        // 简单的直线路径高亮（可以扩展为更复杂的寻路算法）
        const dx = toX - fromX;
        const dy = toY - fromY;

        // 对于相邻瓦片，不需要路径高亮
        if (Math.abs(dx) <= 1 && Math.abs(dy) <= 1) {
            return;
        }

        // 计算路径上的瓦片
        const steps = Math.max(Math.abs(dx), Math.abs(dy));
        for (let i = 1; i < steps; i++) {
            const pathX = Math.round(fromX + (dx * i / steps));
            const pathY = Math.round(fromY + (dy * i / steps));

            const pathTile = document.querySelector(`[data-x="${pathX}"][data-y="${pathY}"]`);
            if (pathTile) {
                pathTile.classList.add('path-highlight');
                this.highlightedTiles.push({ element: pathTile, type: 'path' });
            }
        }
    }

    clearTileHighlights() {
        this.highlightedTiles.forEach(({ element }) => {
            element.classList.remove('movable', 'attackable', 'path-highlight');
        });
        this.highlightedTiles = [];
    }
    
    async saveGame() {
        if (!this.gameId || this.isLoading) return;
        
        this.setLoading(true);
        
        try {
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
    }
    
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
                        <button onclick="game.loadGame('${save.id}')">加载</button>
                        <button onclick="game.deleteGame('${save.id}')">删除</button>
                    `;
                    savesList.appendChild(saveElement);
                });
            }
        } catch (error) {
            console.error('Failed to load game list:', error);
        }
    }
    
    async loadGame(saveId) {
        this.setLoading(true);
        this.showFullscreenOverlay('加载存档', '正在读取您的冒险进度...', '连接到游戏服务器...');

        try {
            this.updateOverlayProgress(20, '验证存档文件...');

            const response = await fetch(`/api/load/${saveId}`, {
                method: 'POST'
            });

            this.updateOverlayProgress(50, '解析游戏数据...');
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
    }

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
    }
    
    showNewGameModal() {
        document.getElementById('new-game-modal').style.display = 'block';
    }
    
    async createNewGame() {
        const playerName = document.getElementById('player-name-input').value.trim();
        const characterClass = document.getElementById('character-class-select').value;

        if (!playerName) {
            alert('请输入角色名称');
            return;
        }

        this.setLoading(true);
        this.showFullscreenOverlay('创建新游戏', '正在为您生成独特的冒险世界（一般等20s即可）...', '初始化AI系统...');

        try {
            this.updateOverlayProgress(15, '创建角色档案...');

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

            this.updateOverlayProgress(40, 'AI正在生成地下城...');
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
    }

    hidePartialOverlay() {
        const overlay = document.getElementById('partial-overlay');
        if (overlay) {
            overlay.style.display = 'none';
        }
    }

    updateOverlayProgress(percentage, text = null) {
        // 更新全屏遮罩进度
        const fullProgressFill = document.getElementById('progress-fill');
        const fullProgressText = document.getElementById('progress-text');

        if (fullProgressFill) {
            fullProgressFill.style.width = `${percentage}%`;
        }
        if (fullProgressText && text) {
            fullProgressText.textContent = text;
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
    }

    // 新增：地图切换方法
    async transitionMap(transitionType) {
        if (this.isLoading || !this.gameId) return;

        this.setLoading(true);
        this.showPartialOverlay('地图切换', '正在进入新区域...', '准备新的冒险...');

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

// 初始化游戏
const game = new LabyrinthiaGame();
