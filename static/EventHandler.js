// Labyrinthia AI - 事件处理模块
// 包含所有事件监听器和键盘/鼠标处理逻辑

// 扩展核心游戏类，添加事件处理功能
Object.assign(LabyrinthiaGame.prototype, {
    
    setupEventListeners() {
        // 注意：方向控制按钮现在由DirectionButtonManager管理
        // 不再在这里添加事件监听器

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
    },
    
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
    },

    showNewGameModal() {
        document.getElementById('new-game-modal').style.display = 'block';
    }
});
