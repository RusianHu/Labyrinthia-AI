// Labyrinthia AI - 智能方向按钮管理器
// 动态管理方向按钮的状态，根据周围环境显示不同的按钮样式

class DirectionButtonManager {
    constructor(game) {
        this.game = game;
        this.directionMap = {
            "northwest": [-1, -1],
            "north": [0, -1],
            "northeast": [1, -1],
            "west": [-1, 0],
            "east": [1, 0],
            "southwest": [-1, 1],
            "south": [0, 1],
            "southeast": [1, 1]
        };
        
        // 方向按钮的选择器映射
        this.buttonSelectors = {
            "northwest": ".dir-nw",
            "north": ".dir-n",
            "northeast": ".dir-ne",
            "west": ".dir-w",
            "east": ".dir-e",
            "southwest": ".dir-sw",
            "south": ".dir-s",
            "southeast": ".dir-se"
        };
    }

    /**
     * 更新所有方向按钮的状态
     */
    updateAllButtons() {
        if (!this.game.gameState || !this.game.gameState.player) {
            return;
        }

        const player = this.game.gameState.player;
        const playerX = player.position[0];
        const playerY = player.position[1];

        // 遍历所有方向，更新按钮状态
        for (const [direction, offset] of Object.entries(this.directionMap)) {
            const targetX = playerX + offset[0];
            const targetY = playerY + offset[1];
            const buttonState = this.analyzeDirection(targetX, targetY, direction);
            this.updateButton(direction, buttonState);
        }
    }

    /**
     * 分析指定方向的状态
     * @returns {Object} 包含状态信息的对象
     */
    analyzeDirection(x, y, direction) {
        const gameState = this.game.gameState;
        const map = gameState.current_map;

        // 默认状态
        const state = {
            type: 'disabled',  // disabled, move, attack, blocked
            canInteract: false,
            monster: null,
            terrain: null,
            icon: this.getDirectionArrow(direction),
            tooltip: ''
        };

        // 检查边界
        if (x < 0 || x >= map.width || y < 0 || y >= map.height) {
            state.type = 'disabled';
            state.tooltip = '边界外';
            return state;
        }

        // 获取瓦片信息
        const tileKey = `${x},${y}`;
        const tile = map.tiles[tileKey];
        
        if (!tile) {
            state.type = 'disabled';
            state.tooltip = '无效位置';
            return state;
        }

        state.terrain = tile.terrain;

        // 检查是否有怪物
        if (tile.character_id && tile.character_id !== gameState.player.id) {
            const monster = gameState.monsters.find(m => m.id === tile.character_id);
            if (monster) {
                state.type = 'attack';
                state.canInteract = true;
                state.monster = monster;
                state.icon = 'gavel';  // Material Icons 攻击图标
                state.tooltip = `攻击 ${monster.name}`;
                return state;
            }
        }

        // 检查地形
        if (tile.terrain === 'wall') {
            state.type = 'blocked';
            state.tooltip = '墙壁';
            return state;
        }

        // 可以移动
        if (this.game.localEngine && this.game.localEngine.canMoveTo(x, y)) {
            state.type = 'move';
            state.canInteract = true;
            state.tooltip = this.getTerrainName(tile.terrain);
            return state;
        }

        // 其他阻挡情况
        state.type = 'blocked';
        state.tooltip = '无法通过';
        return state;
    }

    /**
     * 更新单个按钮的显示
     */
    updateButton(direction, state) {
        const selector = this.buttonSelectors[direction];
        const button = document.querySelector(selector);
        
        if (!button) return;

        // 移除所有状态类
        button.classList.remove('dir-move', 'dir-attack', 'dir-blocked', 'dir-disabled');
        
        // 添加新状态类
        button.classList.add(`dir-${state.type}`);

        // 更新按钮内容
        const isAttack = state.type === 'attack';

        if (isAttack) {
            // 攻击按钮：显示攻击图标
            button.innerHTML = `<i class="material-icons">gavel</i>`;
            button.disabled = false;
        } else if (state.type === 'move') {
            // 移动按钮：显示方向箭头
            button.innerHTML = this.getDirectionArrow(direction);
            button.disabled = false;
        } else {
            // 禁用或阻挡的按钮
            button.innerHTML = this.getDirectionArrow(direction);
            button.disabled = true;
        }

        // 设置提示文本
        button.title = state.tooltip;

        // 存储状态数据到按钮
        button.dataset.buttonState = state.type;
        if (state.monster) {
            button.dataset.monsterId = state.monster.id;
        } else {
            delete button.dataset.monsterId;
        }
    }

    /**
     * 获取方向箭头符号
     */
    getDirectionArrow(direction) {
        const arrows = {
            "northwest": "↖",
            "north": "↑",
            "northeast": "↗",
            "west": "←",
            "east": "→",
            "southwest": "↙",
            "south": "↓",
            "southeast": "↘"
        };
        return arrows[direction] || "?";
    }

    /**
     * 获取地形名称
     */
    getTerrainName(terrain) {
        const names = {
            'floor': '地板',
            'wall': '墙壁',
            'door': '门',
            'stairs_up': '上楼梯',
            'stairs_down': '下楼梯',
            'chest': '宝箱',
            'trap': '陷阱'
        };
        return names[terrain] || terrain;
    }

    /**
     * 处理方向按钮点击
     */
    handleButtonClick(direction) {
        const selector = this.buttonSelectors[direction];
        const button = document.querySelector(selector);

        if (!button || button.disabled) return;

        const buttonState = button.dataset.buttonState;

        // 触发触觉反馈
        this.triggerHapticFeedback(buttonState);

        if (buttonState === 'attack') {
            // 攻击怪物
            const monsterId = button.dataset.monsterId;
            if (monsterId) {
                this.game.attackMonster(monsterId);
            }
        } else if (buttonState === 'move') {
            // 移动
            this.game.movePlayer(direction);
        }
    }

    /**
     * 触发触觉反馈（振动）
     */
    triggerHapticFeedback(buttonState) {
        // 检查是否支持振动API
        if (!navigator.vibrate) return;

        try {
            if (buttonState === 'attack') {
                // 攻击：强烈的双重振动
                navigator.vibrate([50, 30, 50]);
            } else if (buttonState === 'move') {
                // 移动：轻微的单次振动
                navigator.vibrate(20);
            }
        } catch (error) {
            // 忽略振动错误
            console.debug('Vibration not supported or failed:', error);
        }
    }

    /**
     * 绑定所有方向按钮的事件
     */
    bindEvents() {
        for (const direction of Object.keys(this.directionMap)) {
            const selector = this.buttonSelectors[direction];
            const button = document.querySelector(selector);
            
            if (button) {
                // 移除旧的事件监听器（如果有）
                const newButton = button.cloneNode(true);
                button.parentNode.replaceChild(newButton, button);
                
                // 添加新的事件监听器
                newButton.addEventListener('click', (e) => {
                    e.preventDefault();
                    this.handleButtonClick(direction);
                });

                // 添加触摸反馈
                newButton.addEventListener('touchstart', (e) => {
                    newButton.classList.add('touch-active');
                });

                newButton.addEventListener('touchend', (e) => {
                    newButton.classList.remove('touch-active');
                });
            }
        }
    }

    /**
     * 初始化方向按钮管理器
     */
    initialize() {
        this.bindEvents();
        this.updateAllButtons();
    }
}

// 扩展核心游戏类，添加方向按钮管理器
Object.assign(LabyrinthiaGame.prototype, {
    
    initDirectionButtonManager() {
        if (!this.directionButtonManager) {
            this.directionButtonManager = new DirectionButtonManager(this);
            this.directionButtonManager.initialize();
        }
    },

    updateDirectionButtons() {
        if (this.directionButtonManager) {
            this.directionButtonManager.updateAllButtons();
        }
    }
});

