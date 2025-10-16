// Labyrinthia AI - UI更新管理模块
// 包含所有UI更新逻辑（角色状态、地图、物品栏、任务等）

// 扩展核心游戏类，添加UI管理功能
Object.assign(LabyrinthiaGame.prototype, {
    
    updateCharacterStats() {
        const player = this.gameState.player;
        const stats = player.stats;
        const abilities = player.abilities || {
            strength: 10, dexterity: 10, constitution: 10,
            intelligence: 10, wisdom: 10, charisma: 10
        };

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

        // 更新DND六维属性
        this.updateAbilityScores(abilities);

        // 更新楼层信息
        if (this.gameState.current_map) {
            document.getElementById('player-floor').textContent = this.gameState.current_map.depth || 1;
            document.getElementById('current-map-name').textContent = this.gameState.current_map.name || '未知区域';
        }
    },

    /**
     * 更新DND六维属性显示
     * @param {Object} abilities - 六维属性对象
     */
    updateAbilityScores(abilities) {
        const abilityNames = ['strength', 'dexterity', 'constitution', 'intelligence', 'wisdom', 'charisma'];

        abilityNames.forEach(abilityName => {
            const value = abilities[abilityName] || 10;
            const modifier = Math.floor((value - 10) / 2);
            const modifierStr = modifier >= 0 ? `+${modifier}` : `${modifier}`;

            // 更新属性值
            const valueElement = document.getElementById(`ability-${abilityName}`);
            if (valueElement) {
                valueElement.textContent = value;

                // 根据属性值设置颜色
                if (value >= 18) {
                    valueElement.style.color = '#9c27b0'; // 紫色 - 卓越
                } else if (value >= 14) {
                    valueElement.style.color = '#5e35b1'; // 深紫 - 优秀
                } else if (value >= 12) {
                    valueElement.style.color = '#3f51b5'; // 蓝色 - 良好
                } else if (value >= 9) {
                    valueElement.style.color = '#666'; // 灰色 - 普通
                } else {
                    valueElement.style.color = '#e74c3c'; // 红色 - 较弱
                }
            }

            // 更新调整值
            const modElement = document.getElementById(`ability-${abilityName}-mod`);
            if (modElement) {
                modElement.textContent = modifierStr;
                modElement.style.color = modifier >= 0 ? '#4caf50' : '#e74c3c';
            }
        });
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

        // 【修复抖动】只在地图尺寸变化时才更新网格样式
        const expectedColumns = `repeat(${gameMap.width}, ${tileSize}px)`;
        if (mapContainer.style.gridTemplateColumns !== expectedColumns) {
            mapContainer.style.gridTemplateColumns = expectedColumns;
        }

        // 检查是否需要完全重建地图（地图尺寸变化或首次加载）
        const existingTiles = mapContainer.querySelectorAll('.map-tile');
        const expectedTileCount = gameMap.width * gameMap.height;
        const needsFullRebuild = existingTiles.length !== expectedTileCount;

        if (needsFullRebuild) {
            // 完全重建地图
            await this._rebuildMap(mapContainer, gameMap, player, tileSize);
        } else {
            // 增量更新：只更新变化的瓦片
            await this._updateMapTiles(mapContainer, gameMap, player);
        }

        // 应用地板图层效果
        this.applyFloorTheme(gameMap.floor_theme || 'normal');

        // 【修复抖动】只在完全重建时才重新初始化 MapZoomManager
        if (needsFullRebuild) {
            // 初始化或重新初始化地图缩放管理器
            // 使用setTimeout确保DOM已完全更新
            setTimeout(() => {
                this._initializeMapZoomManager();
            }, 100);
        }
    },

    /**
     * 完全重建地图（用于地图尺寸变化或首次加载）
     */
    async _rebuildMap(mapContainer, gameMap, player, tileSize) {
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
                const tile = await this._createTile(x, y, tileData, player);
                mapContainer.appendChild(tile);
            }
        }
    },

    /**
     * 增量更新地图瓦片（只更新变化的部分）
     */
    async _updateMapTiles(mapContainer, gameMap, player) {
        const tiles = mapContainer.querySelectorAll('.map-tile');

        for (const tile of tiles) {
            const x = parseInt(tile.dataset.x);
            const y = parseInt(tile.dataset.y);
            const tileKey = `${x},${y}`;
            const tileData = gameMap.tiles[tileKey];

            // 更新瓦片内容
            await this._updateTile(tile, x, y, tileData, player);
        }
    },

    /**
     * 创建单个瓦片元素
     */
    async _createTile(x, y, tileData, player) {
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

        // 更新瓦片内容
        await this._updateTileContent(tile, tileData, player);

        return tile;
    },

    /**
     * 更新现有瓦片
     */
    async _updateTile(tile, x, y, tileData, player) {
        // 清除旧的类名（保留基础类）
        tile.className = 'map-tile';

        // 更新瓦片内容
        await this._updateTileContent(tile, tileData, player);
    },

    /**
     * 更新瓦片的内容和样式
     */
    async _updateTileContent(tile, tileData, player) {
        // 清空瓦片内容（移除角色图标等）
        tile.innerHTML = '';

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
    },

    /**
     * 初始化地图缩放管理器
     */
    _initializeMapZoomManager() {
        if (typeof MapZoomManager !== 'undefined') {
            // 保存当前缩放级别和滚动位置
            const previousManager = this.mapZoomManager || null;
            const currentZoom = previousManager ? previousManager.getZoom() : 1;
            const previousScrollContainer = previousManager && previousManager.scrollContainer ?
                previousManager.scrollContainer : null;
            const hadScrollState = Boolean(previousScrollContainer);
            const currentScrollLeft = previousScrollContainer ?
                previousScrollContainer.scrollLeft : null;
            const currentScrollTop = previousScrollContainer ?
                previousScrollContainer.scrollTop : null;

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
                const scrollContainer = this.mapZoomManager.scrollContainer;
                if (scrollContainer) {
                    // 【修复抖动】暂时禁用过渡动画，避免缩放时的抖动
                    const mapGrid = document.getElementById('map-grid');
                    if (mapGrid) {
                        const originalTransition = mapGrid.style.transition;
                        mapGrid.style.transition = 'none';

                        // 【修复】确保 getScrollPadding 方法存在
                        const padding = typeof this.mapZoomManager.getScrollPadding === 'function' ?
                            this.mapZoomManager.getScrollPadding() :
                            { left: 0, top: 0, right: 0, bottom: 0 };

                        let targetLeft, targetTop;

                        // 【修复】如果是新地图(没有之前的滚动状态),居中到玩家位置
                        if (!hadScrollState && this.gameState && this.gameState.player && this.gameState.player.position) {
                            const [playerX, playerY] = this.gameState.player.position;
                            const tileSize = 24; // 默认瓦片大小
                            const containerWidth = scrollContainer.clientWidth;
                            const containerHeight = scrollContainer.clientHeight;

                            // 计算玩家在地图中的像素位置
                            const playerPixelX = playerX * tileSize;
                            const playerPixelY = playerY * tileSize;

                            // 居中到玩家位置
                            targetLeft = padding.left + playerPixelX - containerWidth / 2;
                            targetTop = padding.top + playerPixelY - containerHeight / 2;
                        } else {
                            // 保持之前的滚动位置
                            targetLeft = hadScrollState && currentScrollLeft !== null ?
                                currentScrollLeft : padding.left;
                            targetTop = hadScrollState && currentScrollTop !== null ?
                                currentScrollTop : padding.top;
                        }

                        // 恢复之前的缩放级别（先应用缩放，再设置滚动位置）
                        if (currentZoom !== 1) {
                            this.mapZoomManager.scale = currentZoom;
                            this.mapZoomManager.applyScale();
                        }

                        // 【修复抖动】设置滚动位置
                        if (typeof targetLeft === 'number') {
                            scrollContainer.scrollLeft = targetLeft;
                        }
                        if (typeof targetTop === 'number') {
                            scrollContainer.scrollTop = targetTop;
                        }

                        // 恢复过渡动画（在下一帧）
                        requestAnimationFrame(() => {
                            if (mapGrid) {
                                mapGrid.style.transition = originalTransition;
                            }
                        });
                    }
                }

                console.log('MapZoomManager initialized and ready after map update (zoom:', currentZoom, ')');
            } else {
                console.warn('MapZoomManager initialization failed');
            }
        }
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
        const validThemes = ['normal', 'magic', 'abandoned', 'cave', 'combat', 'grassland', 'desert', 'farmland', 'snowfield', 'town'];
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
