// Labyrinthia AI - 地图交互模块
// 包含地图点击、悬停、瓦片交互等逻辑

// 扩展核心游戏类，添加地图交互功能
Object.assign(LabyrinthiaGame.prototype, {
    
    async handleTileClick(x, y, tileData) {
        if (this.isLoading) return;

        const player = this.gameState.player;
        const playerX = player.position[0];
        const playerY = player.position[1];

        // 【修复】从游戏状态中获取实时的瓦片数据，而不是使用闭包中的旧数据
        const tileKey = `${x},${y}`;
        const currentTileData = this.gameState.current_map.tiles[tileKey];

        if (!currentTileData) {
            console.warn(`Tile data not found for (${x}, ${y})`);
            return;
        }

        // 检查是否点击了怪物
        if (currentTileData.character_id && currentTileData.character_id !== player.id) {
            const monster = this.gameState.monsters.find(m => m.id === currentTileData.character_id);
            if (monster) {
                // 检查攻击距离（使用切比雪夫距离，允许对角线攻击）
                const distance = Math.max(Math.abs(x - playerX), Math.abs(y - playerY));
                if (distance <= 1) {  // 玩家只能近战攻击
                    // 【修复】使用await等待攻击完成，避免继续执行移动逻辑
                    await this.attackMonster(monster.id);
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
    },

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
    },

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
    },

    handleTileHover(x, y, tileData, isEntering) {
        if (!this.gameState || !this.gameState.player) return;

        const player = this.gameState.player;
        const playerX = player.position[0];
        const playerY = player.position[1];

        if (isEntering) {
            // 清除之前的高亮
            this.clearTileHighlights();

            // 【修复】从游戏状态中获取实时的瓦片数据
            const tileKey = `${x},${y}`;
            const currentTileData = this.gameState.current_map.tiles[tileKey];

            // 检查是否可以移动到该位置（不显示错误消息）
            if (this.canMoveToTile(x, y, playerX, playerY, false)) {
                this.highlightMovableTile(x, y);
                this.highlightMovementPath(playerX, playerY, x, y);
            }

            // 检查是否可以攻击该位置的怪物
            if (currentTileData && currentTileData.character_id && currentTileData.character_id !== player.id) {
                const monster = this.gameState.monsters.find(m => m.id === currentTileData.character_id);
                if (monster) {
                    const distance = Math.max(Math.abs(x - playerX), Math.abs(y - playerY));
                    if (distance <= 1) {  // 玩家只能近战攻击
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
    },

    highlightMovableTile(x, y) {
        const tile = document.querySelector(`[data-x="${x}"][data-y="${y}"]`);
        if (tile) {
            tile.classList.add('movable');
            this.highlightedTiles.push({ element: tile, type: 'movable' });
        }
    },

    highlightAttackableTile(x, y) {
        const tile = document.querySelector(`[data-x="${x}"][data-y="${y}"]`);
        if (tile) {
            tile.classList.add('attackable');
            this.highlightedTiles.push({ element: tile, type: 'attackable' });
        }
    },

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
    },

    clearTileHighlights() {
        this.highlightedTiles.forEach(({ element }) => {
            element.classList.remove('movable', 'attackable', 'path-highlight');
        });
        this.highlightedTiles = [];
    },

    requiresItemUseIntelDialog(item) {
        if (!item || item.is_equippable) {
            return false;
        }
        if (item.requires_use_confirmation) {
            return true;
        }
        const hintLevel = String(item.hint_level || 'vague').trim().toLowerCase();
        return hintLevel !== 'none';
    },

    showItemUseDialog(item) {
        const dialog = document.getElementById('item-use-dialog');
        const nameElement = document.getElementById('item-use-name');
        const descriptionElement = document.getElementById('item-use-description');
        const usageElement = document.getElementById('item-use-usage');
        const metaElement = document.getElementById('item-use-meta');
        const confirmButton = document.getElementById('confirm-use-item');
        const dropButton = document.getElementById('drop-item');
        const cancelButton = document.getElementById('cancel-use-item');

        const normalizeHintLevel = (value) => {
            const raw = String(value || 'vague').trim().toLowerCase();
            if (raw === 'none' || raw === 'clear' || raw === 'vague') {
                return raw;
            }
            return 'vague';
        };

        const pickText = (...values) => {
            for (const value of values) {
                const text = String(value || '').trim();
                if (!text || text === '无' || text === 'none' || text === 'N/A') {
                    continue;
                }
                return text;
            }
            return '';
        };

        const hintLevel = normalizeHintLevel(item.hint_level);
        const usageText = pickText(item.usage_description) || (hintLevel === 'none' ? '无额外使用步骤。' : '使用步骤未完全记录，建议谨慎尝试。');
        const triggerText = pickText(item.trigger_hint) || (hintLevel === 'clear' ? '满足条件后触发效果。' : '触发条件未明，可能受场景影响。');
        const riskText = pickText(item.risk_hint) || (hintLevel === 'none' ? '风险较低。' : '风险未知，建议在安全位置使用。');
        const consumptionText = pickText(item.consumption_hint) || '消耗方式未记录。';
        const outcomes = Array.isArray(item.expected_outcomes)
            ? item.expected_outcomes.map((entry) => String(entry || '').trim()).filter((entry) => entry.length > 0)
            : [];
        const outcomeText = outcomes.length > 0 ? outcomes.map((entry) => `- ${entry}`).join('\n') : '- 使用后可补全情报';

        nameElement.textContent = item.name;
        descriptionElement.textContent = item.description || '未记录描述';
        usageElement.textContent = [
            `使用说明: ${usageText}`,
            `触发提示: ${triggerText}`,
            `风险提示: ${riskText}`,
            `消耗提示: ${consumptionText}`,
            '可能结果:',
            `${outcomeText}`
        ].join('\n');

        if (metaElement) {
            const chips = [];
            const rarity = this._getItemRarityLabel(item.rarity || 'common');
            const type = this._getItemTypeLabel(item.item_type || 'misc');
            const hintLabelMap = { none: '无情报', vague: '模糊', clear: '清晰' };
            chips.push(`<span class="item-chip">类型: ${type}</span>`);
            chips.push(`<span class="item-chip">稀有度: ${rarity}</span>`);
            chips.push(`<span class="item-chip">情报: ${hintLabelMap[hintLevel] || '模糊'}</span>`);
            if ((item.max_charges || 0) > 0) {
                chips.push(`<span class="item-chip">充能: ${item.charges ?? 0}/${item.max_charges}</span>`);
            }
            if ((item.current_cooldown || 0) > 0) {
                chips.push(`<span class="item-chip">冷却: ${item.current_cooldown}回合</span>`);
            }
            if (item.requires_use_confirmation) {
                chips.push('<span class="item-chip">高风险确认</span>');
            }
            metaElement.innerHTML = chips.join('');
        }

        const isEquip = !!item.is_equippable;
        const confirmText = isEquip
            ? '装备/卸下'
            : (item.requires_use_confirmation ? '承担风险并使用' : '确认使用');
        confirmButton.textContent = confirmText;

        confirmButton.onclick = () => {
            this.hideItemUseDialog();
            this.useItem(item.id);
        };

        dropButton.onclick = () => {
            this.hideItemUseDialog();
            this.dropItem(item.id);
        };

        cancelButton.onclick = () => {
            this.hideItemUseDialog();
        };

        dialog.style.display = 'flex';
    },

    hideItemUseDialog() {
        const dialog = document.getElementById('item-use-dialog');
        dialog.style.display = 'none';
    },

    showTileTooltip(event, tileData, x, y) {
        const tooltip = document.getElementById('tile-tooltip');
        if (!tooltip) return;

        // 【修复】从游戏状态中获取实时的瓦片数据
        const tileKey = `${x},${y}`;
        const currentTileData = this.gameState.current_map.tiles[tileKey];

        let tooltipText = `位置: (${x}, ${y})\n`;

        if (currentTileData) {
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

            tooltipText += `地形: ${terrainNames[currentTileData.terrain] || currentTileData.terrain}\n`;

            // 房间类型信息
            if (currentTileData.room_type) {
                const roomTypeNames = {
                    'entrance': '入口房间',
                    'treasure': '宝库房间',
                    'boss': 'Boss房间',
                    'special': '特殊房间',
                    'normal': '普通房间',
                    'corridor': '走廊'
                };
                tooltipText += `房间类型: ${roomTypeNames[currentTileData.room_type] || currentTileData.room_type}\n`;
            }

            // 探索状态
            if (currentTileData.is_explored) {
                tooltipText += '状态: 已探索\n';
            } else {
                tooltipText += '状态: 未探索\n';
            }

            // 角色信息
            if (currentTileData.character_id) {
                if (currentTileData.character_id === this.gameState.player.id) {
                    const player = this.gameState.player;
                    tooltipText += `角色: ${player.name} (玩家)\n`;
                    tooltipText += `生命值: ${player.stats.hp}/${player.stats.max_hp}\n`;
                    tooltipText += `法力值: ${player.stats.mp}/${player.stats.max_mp}\n`;
                    tooltipText += `等级: ${player.stats.level}\n`;

                    // 显示玩家关键属性
                    if (player.abilities) {
                        const str = player.abilities.strength || 10;
                        const dex = player.abilities.dexterity || 10;
                        const con = player.abilities.constitution || 10;
                        tooltipText += `属性: 力${str} 敏${dex} 体${con}\n`;
                    }
                } else {
                    const monster = this.gameState.monsters.find(m => m.id === currentTileData.character_id);
                    if (monster) {
                        // 检查是否为任务怪物
                        const isQuestMonster = this.isQuestMonster(monster);

                        if (isQuestMonster) {
                            if (monster.is_boss) {
                                tooltipText += `任务Boss: ${monster.name} 👑\n`;
                            } else {
                                tooltipText += `任务怪物: ${monster.name} ⭐\n`;
                            }
                        } else {
                            tooltipText += `怪物: ${monster.name}\n`;
                        }

                        tooltipText += `生命值: ${monster.stats.hp}/${monster.stats.max_hp}\n`;
                        if (monster.challenge_rating) {
                            tooltipText += `挑战等级: ${monster.challenge_rating}\n`;
                        }

                        // 显示怪物关键属性
                        if (monster.abilities) {
                            const str = monster.abilities.strength || 10;
                            const dex = monster.abilities.dexterity || 10;
                            const con = monster.abilities.constitution || 10;
                            const strMod = Math.floor((str - 10) / 2);
                            const dexMod = Math.floor((dex - 10) / 2);
                            const conMod = Math.floor((con - 10) / 2);
                            tooltipText += `属性: 力${str}(${strMod>=0?'+':''}${strMod}) 敏${dex}(${dexMod>=0?'+':''}${dexMod}) 体${con}(${conMod>=0?'+':''}${conMod})\n`;
                        }

                        tooltipText += `护甲等级: ${monster.stats.ac || 10}\n`;

                        // 显示攻击范围信息
                        const attackRange = monster.attack_range || 1;
                        if (attackRange > 1) {
                            tooltipText += `攻击范围: ${attackRange} (远程攻击)\n`;
                        } else {
                            tooltipText += `攻击范围: ${attackRange} (近战攻击)\n`;
                        }

                        // 如果是任务怪物，显示额外信息
                        if (isQuestMonster) {
                            tooltipText += `类型: 任务相关敌人\n`;
                            if (monster.is_boss) {
                                tooltipText += `警告: 强大的Boss敌人！\n`;
                            }
                        }
                    }
                }
            }

            // 物品信息
            if (currentTileData.items && currentTileData.items.length > 0) {
                tooltipText += `物品: ${currentTileData.items.length}个\n`;
            }

            // 事件信息（如果有且不隐藏）
            if (currentTileData.has_event && !currentTileData.is_event_hidden) {
                const eventNames = {
                    'combat': '战斗',
                    'treasure': '宝藏',
                    'story': '故事',
                    'trap': '陷阱',
                    'mystery': '神秘'
                };

                // 检查是否为任务事件
                if (currentTileData.event_data && currentTileData.event_data.quest_event_id) {
                    tooltipText += `任务事件: ${currentTileData.event_data.name || '特殊事件'}\n`;
                    if (currentTileData.event_data.description) {
                        tooltipText += `描述: ${currentTileData.event_data.description}\n`;
                    }
                    if (currentTileData.event_data.is_mandatory) {
                        tooltipText += '类型: 必要任务事件\n';
                    }
                } else {
                    tooltipText += `事件: ${eventNames[currentTileData.event_type] || currentTileData.event_type}\n`;
                }

                if (currentTileData.event_triggered) {
                    tooltipText += '状态: 已触发\n';
                } else {
                    tooltipText += '状态: 未触发\n';
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
    },

    hideTileTooltip() {
        const tooltip = document.getElementById('tile-tooltip');
        if (tooltip) {
            tooltip.classList.remove('show');
        }
    }
});
