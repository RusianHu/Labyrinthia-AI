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

        this.init();
        this.initializeDebugMode();
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
        
        this.setLoading(true);
        
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
                // 更新游戏状态
                await this.refreshGameState();
                
                // 添加消息
                if (result.message) {
                    this.addMessage(result.message, 'action');
                }
                
                if (result.events) {
                    result.events.forEach(event => {
                        this.addMessage(event, 'system');
                    });
                }
                
                if (result.narrative) {
                    this.addMessage(result.narrative, 'narrative');
                }
            } else {
                this.addMessage(result.message || '行动失败', 'error');
            }
        } catch (error) {
            console.error('Action error:', error);
            this.addMessage('网络错误，请重试', 'error');
        } finally {
            this.setLoading(false);
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
                });

                tile.addEventListener('mouseleave', () => {
                    this.hideTileTooltip();
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
                    this.useItem(item.id);
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
            questElement.innerHTML = `
                <h4>${quest.title}</h4>
                <p>${quest.description}</p>
                <div class="quest-objectives">
                    ${quest.objectives.map((obj, index) => 
                        `<div class="objective ${quest.completed_objectives[index] ? 'completed' : ''}">
                            ${quest.completed_objectives[index] ? '✓' : '○'} ${obj}
                        </div>`
                    ).join('')}
                </div>
            `;
            questList.appendChild(questElement);
        });
    }
    
    async attackMonster(monsterId) {
        await this.performAction('attack', { target_id: monsterId });
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
                    tooltipText += '角色: 玩家\n';
                } else {
                    const monster = this.gameState.monsters.find(m => m.id === tileData.character_id);
                    if (monster) {
                        tooltipText += `怪物: ${monster.name}\n`;
                        tooltipText += `生命值: ${monster.stats.hp}/${monster.stats.max_hp}\n`;
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

        try {
            const response = await fetch(`/api/load/${saveId}`, {
                method: 'POST'
            });

            const result = await response.json();

            if (result.success) {
                this.gameId = result.game_id;
                await this.refreshGameState();
                this.addMessage('游戏已加载', 'success');

                // 隐藏主菜单，显示游戏界面
                document.getElementById('main-menu').style.display = 'none';
                document.getElementById('game-interface').style.display = 'block';
            } else {
                this.addMessage('加载失败', 'error');
            }
        } catch (error) {
            console.error('Load error:', error);
            this.addMessage('加载时发生错误', 'error');
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
        
        try {
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
            
            const result = await response.json();
            
            if (result.success) {
                this.gameId = result.game_id;
                await this.refreshGameState();
                this.addMessage('新游戏开始！', 'success');
                
                // 隐藏模态框和主菜单，显示游戏界面
                document.getElementById('new-game-modal').style.display = 'none';
                document.getElementById('main-menu').style.display = 'none';
                document.getElementById('game-interface').style.display = 'block';
            } else {
                this.addMessage('创建游戏失败', 'error');
            }
        } catch (error) {
            console.error('Create game error:', error);
            this.addMessage('创建游戏时发生错误', 'error');
        } finally {
            this.setLoading(false);
        }
    }
}

// 初始化游戏
const game = new LabyrinthiaGame();
