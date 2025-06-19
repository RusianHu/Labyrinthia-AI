// Labyrinthia AI - UI更新管理模块
// 包含所有UI更新逻辑（角色状态、地图、物品栏、任务等）

// 扩展核心游戏类，添加UI管理功能
Object.assign(LabyrinthiaGame.prototype, {
    
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

        // 更新楼层信息
        if (this.gameState.current_map) {
            document.getElementById('player-floor').textContent = this.gameState.current_map.depth || 1;
            document.getElementById('current-map-name').textContent = this.gameState.current_map.name || '未知区域';
        }
    },
    
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

                    // 设置房间类型样式
                    if (tileData.room_type) {
                        tile.classList.add(`room-${tileData.room_type}`);

                        // 为特殊类型的门添加额外样式
                        if (tileData.terrain === 'door') {
                            if (tileData.room_type === 'treasure') {
                                tile.classList.add('door-treasure');
                            } else if (tileData.room_type === 'boss') {
                                tile.classList.add('door-boss');
                            } else if (tileData.room_type === 'special') {
                                tile.classList.add('door-special');
                            }
                        }
                    }

                    // 设置可见性
                    if (tileData.is_explored) {
                        tile.classList.add('tile-explored');
                    } else {
                        tile.classList.add('tile-unexplored');
                    }

                    if (tileData.is_visible) {
                        tile.classList.add('tile-visible');
                    }

                    // 检查是否为任务事件
                    if (tileData.has_event && tileData.event_data && tileData.event_data.quest_event_id) {
                        tile.classList.add('quest-event');
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

                            // 检查是否为任务怪物
                            if (this.isQuestMonster(monster)) {
                                if (monster.is_boss) {
                                    monsterIcon.classList.add('quest-boss');
                                } else {
                                    monsterIcon.classList.add('quest-monster');
                                }
                            }

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
    },
    
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
    },
    
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
            const showProgress = this.config &&
                                (this.config.show_quest_progress ||
                                 (this.config.game && this.config.game.show_quest_progress));

            if (showProgress && quest.progress_percentage !== undefined) {
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
    },

    isQuestMonster(monster) {
        // 检查怪物是否为任务相关怪物
        if (!this.gameState.quests || this.gameState.quests.length === 0) {
            return false;
        }

        // 查找活跃任务
        const activeQuest = this.gameState.quests.find(q => q.is_active && !q.is_completed);
        if (!activeQuest || !activeQuest.special_monsters) {
            return false;
        }

        // 检查怪物名称是否匹配任务专属怪物
        return activeQuest.special_monsters.some(questMonster =>
            monster.name === questMonster.name ||
            monster.name.includes(questMonster.name) ||
            questMonster.name.includes(monster.name)
        );
    }
});
