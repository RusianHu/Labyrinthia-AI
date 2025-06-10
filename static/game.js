// Labyrinthia AI - 游戏前端脚本

class LabyrinthiaGame {
    constructor() {
        this.gameId = null;
        this.gameState = null;
        this.isLoading = false;
        this.messageLog = [];
        
        this.init();
    }
    
    init() {
        this.setupEventListeners();
        this.loadGameList();
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
            const response = await fetch('/api/action', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    game_id: this.gameId,
                    action: action,
                    parameters: parameters
                })
            });
            
            const result = await response.json();
            
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
