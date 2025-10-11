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

        // 使用精灵图系统更新职业显示
        if (window.characterSprites) {
            window.characterSprites.updateCharacterClassDisplay(player.character_class);
        } else {
            document.getElementById('player-class').textContent = player.character_class;
        }

        // 更新生命值，确保不显示负数
        const displayHp = Math.max(0, stats.hp);
        document.getElementById('hp-current').textContent = displayHp;
        document.getElementById('hp-max').textContent = stats.max_hp;
        const hpPercent = Math.max(0, (displayHp / stats.max_hp) * 100);
        document.getElementById('hp-bar').style.width = `${hpPercent}%`;

        // HP条颜色根据生命值变化
        const hpBar = document.getElementById('hp-bar');
        if (hpPercent <= 0) {
            hpBar.style.backgroundColor = '#000000'; // 黑色表示死亡
        } else if (hpPercent <= 25) {
            hpBar.style.backgroundColor = '#e74c3c'; // 红色
        } else if (hpPercent <= 50) {
            hpBar.style.backgroundColor = '#f39c12'; // 橙色
        } else {
            hpBar.style.backgroundColor = '#2ecc71'; // 绿色
        }

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
    
    async updateMap() {
        const mapContainer = document.getElementById('map-grid');
        const gameMap = this.gameState.current_map;
        const player = this.gameState.player;

        // 动态获取瓦片大小以适应响应式设计
        const getTileSize = () => {
            const tempTile = document.createElement('div');
            tempTile.className = 'map-tile';
            tempTile.style.visibility = 'hidden';
            document.body.appendChild(tempTile);
            const size = tempTile.offsetWidth;
            document.body.removeChild(tempTile);
            return size > 0 ? size : 24; // 提供一个回退值
        };

        const tileSize = getTileSize();

        // 设置网格样式
        mapContainer.style.gridTemplateColumns = `repeat(${gameMap.width}, ${tileSize}px)`;

        // 保存地板图层（如果存在）
        const floorLayers = Array.from(mapContainer.querySelectorAll('.floor-layer, .floor-overlay'));

        // 清空地图容器
        mapContainer.innerHTML = '';

        // 重新添加地板图层（在地图瓦片之前）
        floorLayers.forEach(layer => {
            mapContainer.appendChild(layer);
        });

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
                    
                    // 添加角色 - 使用精灵图系统
                    if (tileData.character_id === player.id) {
                        // 添加玩家图标
                        if (window.characterSprites) {
                            await window.characterSprites.addCharacterToTile(tile, player, true);
                        } else {
                            // 回退到原始方式
                            const playerIcon = document.createElement('div');
                            playerIcon.className = 'character-player';
                            tile.appendChild(playerIcon);
                        }
                    } else if (tileData.character_id) {
                        // 查找怪物
                        const monster = this.gameState.monsters.find(m => m.id === tileData.character_id);
                        if (monster) {
                            // 添加怪物图标
                            if (window.characterSprites) {
                                const monsterIcon = await window.characterSprites.addMonsterToTile(tile, monster);
                                monsterIcon.addEventListener('click', (e) => {
                                    e.stopPropagation(); // 阻止事件冒泡到瓦片
                                    this.attackMonster(monster.id);
                                });
                            } else {
                                // 回退到原始方式
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
                                monsterIcon.addEventListener('click', (e) => {
                                    e.stopPropagation(); // 阻止事件冒泡到瓦片
                                    this.attackMonster(monster.id);
                                });
                                tile.appendChild(monsterIcon);
                            }
                        }
                    }
                }
                
                mapContainer.appendChild(tile);
            }
        }

        // 应用地板图层效果
        this.applyFloorTheme(gameMap.floor_theme || 'normal');

        // 初始化或重新初始化地图缩放管理器
        // 使用setTimeout确保DOM已完全更新
        setTimeout(() => {
            if (typeof MapZoomManager !== 'undefined') {
                // 保存当前缩放级别
                const currentZoom = this.mapZoomManager ? this.mapZoomManager.getZoom() : 1;
                const currentScrollLeft = this.mapZoomManager && this.mapZoomManager.mapContainer ?
                    this.mapZoomManager.mapContainer.scrollLeft : 0;
                const currentScrollTop = this.mapZoomManager && this.mapZoomManager.mapContainer ?
                    this.mapZoomManager.mapContainer.scrollTop : 0;

                // 如果已存在，先销毁旧的
                if (this.mapZoomManager) {
                    try {
                        this.mapZoomManager.destroy();
                    } catch (e) {
                        console.warn('Failed to destroy old MapZoomManager:', e);
                    }
                }

                // 创建新的MapZoomManager
                this.mapZoomManager = new MapZoomManager('map-container', 'map-grid');

                // 重新初始化以确保容器已存在
                const reinitSuccess = this.mapZoomManager.reinitialize();

                if (reinitSuccess) {
                    // 恢复之前的缩放级别和滚动位置
                    if (currentZoom !== 1) {
                        this.mapZoomManager.setZoom(currentZoom);
                        // 恢复滚动位置
                        setTimeout(() => {
                            if (this.mapZoomManager.mapContainer) {
                                this.mapZoomManager.mapContainer.scrollLeft = currentScrollLeft;
                                this.mapZoomManager.mapContainer.scrollTop = currentScrollTop;
                            }
                        }, 50);
                    }
                    console.log('MapZoomManager initialized and ready after map update (zoom:', currentZoom, ')');
                } else {
                    console.warn('MapZoomManager initialization failed');
                }
            }
        }, 100);
    },

    /**
     * 应用地板主题
     * @param {string} theme - 地板主题 (normal, magic, abandoned, cave, combat)
     */
    applyFloorTheme(theme) {
        // 检查FloorLayerManager是否可用
        if (typeof floorLayerManager === 'undefined') {
            console.warn('FloorLayerManager not available, skipping floor theme application');
            return;
        }

        const mapGridContainer = document.getElementById('map-grid');
        if (!mapGridContainer) {
            console.warn('Map grid container not found');
            return;
        }

        // 验证主题是否有效
        const validThemes = ['normal', 'magic', 'abandoned', 'cave', 'combat'];
        const floorTheme = validThemes.includes(theme) ? theme : 'normal';

        try {
            // 移除旧的地板图层
            floorLayerManager.removeFloorLayers(mapGridContainer);

            // 应用新的地板主题
            floorLayerManager.applyPreset(mapGridContainer, floorTheme);

            console.log(`Applied floor theme: ${floorTheme}`);
        } catch (error) {
            console.error('Failed to apply floor theme:', error);
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

        // 动态调整任务面板大小
        this.adjustQuestPanelSize();

        // 确保窗口大小变化时重新调整
        this.setupQuestPanelResizeListener();
    },

    adjustQuestPanelSize() {
        const questList = document.getElementById('quest-list');
        const questPanel = document.querySelector('.quest-panel');

        if (!questList || !questPanel) return;

        // 等待DOM更新完成后再调整大小
        setTimeout(() => {
            // 获取任务列表的实际内容高度
            const contentHeight = questList.scrollHeight;
            const viewportHeight = window.innerHeight;
            const maxHeight = viewportHeight * 0.6; // 60vh，为其他UI元素留出空间

            // 获取当前任务数量
            const questItems = questList.querySelectorAll('.quest-item');
            const questCount = questItems.length;

            // 根据任务数量和内容高度智能调整
            if (questCount === 0) {
                // 没有任务时，设置最小高度
                questList.style.height = '50px';
                questList.style.maxHeight = 'none';
                questList.style.overflowY = 'hidden';
            } else if (contentHeight <= maxHeight) {
                // 内容适中，让容器自适应内容高度
                questList.style.maxHeight = 'none';
                questList.style.height = 'auto';
                questList.style.overflowY = 'visible';

                // 添加调试信息（如果启用调试模式）
                if (this.config && this.config.game && this.config.game.debug_mode) {
                    console.log(`Quest panel auto-sized: ${contentHeight}px (${questCount} quests)`);
                }
            } else {
                // 内容过多，使用滚动条
                questList.style.maxHeight = `${maxHeight}px`;
                questList.style.height = `${maxHeight}px`;
                questList.style.overflowY = 'auto';

                // 添加调试信息（如果启用调试模式）
                if (this.config && this.config.game && this.config.game.debug_mode) {
                    console.log(`Quest panel with scroll: ${maxHeight}px (content: ${contentHeight}px, ${questCount} quests)`);
                }
            }

            // 确保任务面板在视觉上突出显示（如果有任务）
            if (questCount > 0) {
                questPanel.style.border = '2px solid rgba(94, 53, 177, 0.3)';
                questPanel.style.boxShadow = '0 4px 12px rgba(94, 53, 177, 0.1)';
            } else {
                questPanel.style.border = '1px solid rgba(94, 53, 177, 0.2)';
                questPanel.style.boxShadow = 'none';
            }
        }, 10);
    },

    setupQuestPanelResizeListener() {
        // 避免重复添加监听器
        if (this._questPanelResizeListenerAdded) return;

        let resizeTimeout;
        const handleResize = () => {
            // 防抖处理，避免频繁调整
            clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(() => {
                this.adjustQuestPanelSize();
            }, 250);
        };

        window.addEventListener('resize', handleResize);
        this._questPanelResizeListenerAdded = true;

        // 添加调试信息
        if (this.config && this.config.game && this.config.game.debug_mode) {
            console.log('Quest panel resize listener added');
        }
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
