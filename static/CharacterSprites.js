// Labyrinthia AI - 角色精灵图管理模块
// 管理职业头像、怪物图标的显示

class CharacterSprites {
    constructor() {
        this.config = null;
        this.spriteSheet = null;
        this.isLoaded = false;
        this.loadPromise = this.loadConfig();
    }

    async loadConfig() {
        try {
            const response = await fetch('/static/assets/characters/sprite_config.json');
            this.config = await response.json();
            
            // 预加载精灵图
            await this.preloadSpriteSheet();
            
            this.isLoaded = true;
            console.log('Character sprites loaded successfully');
        } catch (error) {
            console.warn('Failed to load character sprites, using fallback colors:', error);
            this.isLoaded = false;
        }
    }

    async preloadSpriteSheet() {
        return new Promise((resolve, reject) => {
            if (!this.config || !this.config.spriteSheet) {
                reject(new Error('No sprite sheet configured'));
                return;
            }

            const img = new Image();
            img.onload = () => {
                this.spriteSheet = img;
                resolve();
            };
            img.onerror = () => {
                console.warn('Sprite sheet not found, will use fallback rendering');
                reject(new Error('Failed to load sprite sheet'));
            };
            img.src = this.config.spriteSheet;
        });
    }

    async ensureLoaded() {
        if (!this.isLoaded) {
            await this.loadPromise;
        }
    }

    /**
     * 获取职业配置
     */
    getClassConfig(characterClass) {
        if (!this.config || !this.config.classes) {
            return null;
        }
        
        const classKey = characterClass.toLowerCase();
        return this.config.classes[classKey] || null;
    }

    /**
     * 获取怪物配置
     */
    getMonsterConfig(monsterType = 'default') {
        if (!this.config || !this.config.monsters) {
            return null;
        }
        
        return this.config.monsters[monsterType] || this.config.monsters.default;
    }

    /**
     * 创建角色图标元素（使用精灵图或颜色回退）
     */
    createCharacterIcon(characterClass, isPlayer = true) {
        const icon = document.createElement('div');
        icon.className = isPlayer ? 'character-player' : 'character-monster';
        
        const classConfig = this.getClassConfig(characterClass);
        
        if (this.isLoaded && this.spriteSheet && classConfig) {
            // 使用精灵图
            this.applySpriteStyle(icon, classConfig);
        } else if (classConfig && classConfig.color) {
            // 使用颜色回退
            icon.style.backgroundColor = classConfig.color;
        }
        // 否则使用CSS默认样式
        
        return icon;
    }

    /**
     * 创建怪物图标元素
     */
    createMonsterIcon(monsterType = 'default', isQuestMonster = false, isBoss = false) {
        const icon = document.createElement('div');
        icon.className = 'character-monster';

        if (isQuestMonster) {
            if (isBoss) {
                icon.classList.add('quest-boss');
            } else {
                icon.classList.add('quest-monster');
            }
        }

        const monsterConfig = this.getMonsterConfig(monsterType);

        // 优先使用独立的怪物图片
        if (monsterConfig && monsterConfig.image) {
            icon.style.backgroundImage = `url(${monsterConfig.image})`;
            icon.style.backgroundSize = 'cover';
            icon.style.backgroundPosition = 'center';
            icon.style.backgroundRepeat = 'no-repeat';
            icon.style.imageRendering = 'pixelated'; // 保持像素艺术风格
            icon.style.backgroundColor = 'transparent';
        } else if (this.isLoaded && this.spriteSheet && monsterConfig) {
            // 使用精灵图
            this.applySpriteStyle(icon, monsterConfig);
        } else if (monsterConfig && monsterConfig.color) {
            // 使用颜色回退
            icon.style.backgroundColor = monsterConfig.color;
        }

        return icon;
    }

    /**
     * 应用精灵图样式
     */
    applySpriteStyle(element, config, targetSize = null) {
        if (!this.config || !this.config.spriteSize) {
            return;
        }

        const { width, height } = this.config.spriteSize;
        const { x, y } = config;

        // 获取元素的实际尺寸
        const elementWidth = targetSize || parseInt(getComputedStyle(element).width) || 20;
        const elementHeight = targetSize || parseInt(getComputedStyle(element).height) || 20;

        // 计算缩放比例
        const scale = elementWidth / width;

        // 获取精灵图的实际尺寸（假设是正方形或已知尺寸）
        const spriteSheetWidth = this.spriteSheet ? this.spriteSheet.naturalWidth : 409;
        const spriteSheetHeight = this.spriteSheet ? this.spriteSheet.naturalHeight : 409;

        // 设置背景图片和位置
        element.style.backgroundImage = `url(${this.config.spriteSheet})`;
        element.style.backgroundSize = `${spriteSheetWidth * scale}px ${spriteSheetHeight * scale}px`;
        element.style.backgroundPosition = `-${x * scale}px -${y * scale}px`;
        element.style.imageRendering = 'pixelated'; // 保持像素艺术风格

        // 移除纯色背景
        element.style.backgroundColor = 'transparent';
    }

    /**
     * 获取职业颜色（用于UI显示）
     */
    getClassColor(characterClass) {
        const classConfig = this.getClassConfig(characterClass);
        return classConfig ? classConfig.color : '#2ecc71';
    }

    /**
     * 获取职业中文名称
     */
    getClassName(characterClass) {
        const classConfig = this.getClassConfig(characterClass);
        return classConfig ? classConfig.name : characterClass;
    }

    /**
     * 获取职业描述
     */
    getClassDescription(characterClass) {
        const classConfig = this.getClassConfig(characterClass);
        return classConfig ? classConfig.description : '';
    }

    /**
     * 创建职业选择卡片（用于角色创建界面）
     */
    createClassCard(characterClass) {
        const classConfig = this.getClassConfig(characterClass);
        if (!classConfig) return null;

        const card = document.createElement('div');
        card.className = 'class-card';
        card.dataset.class = characterClass;

        // 创建图标容器
        const iconContainer = document.createElement('div');
        iconContainer.className = 'class-icon-container';
        
        const icon = this.createCharacterIcon(characterClass, true);
        icon.style.width = '48px';
        icon.style.height = '48px';
        icon.style.position = 'relative';
        icon.style.top = '0';
        icon.style.left = '0';
        
        iconContainer.appendChild(icon);

        // 创建信息容器
        const info = document.createElement('div');
        info.className = 'class-info';
        info.innerHTML = `
            <h3>${classConfig.name}</h3>
            <p>${classConfig.description}</p>
        `;

        card.appendChild(iconContainer);
        card.appendChild(info);

        return card;
    }

    /**
     * 更新角色状态面板的职业显示
     */
    updateCharacterClassDisplay(characterClass) {
        const classElement = document.getElementById('player-class');
        if (!classElement) return;

        const classConfig = this.getClassConfig(characterClass);
        if (classConfig) {
            classElement.textContent = classConfig.name;
            classElement.style.color = classConfig.color;
        } else {
            classElement.textContent = characterClass;
        }
    }

    /**
     * 为地图瓦片添加角色图标
     */
    async addCharacterToTile(tile, character, isPlayer = false) {
        // 确保精灵图已加载
        await this.ensureLoaded();

        const characterClass = character.character_class || 'fighter';
        const icon = this.createCharacterIcon(characterClass, isPlayer);

        if (!isPlayer && character.name) {
            icon.title = character.name;
        }

        // 【修复】设置 pointer-events: none，让鼠标事件穿透到瓦片
        // 这样悬停提示工具栏才能正常工作
        icon.style.pointerEvents = 'none';

        tile.appendChild(icon);
        return icon;
    }

    /**
     * 为地图瓦片添加怪物图标
     */
    async addMonsterToTile(tile, monster) {
        // 确保精灵图已加载
        await this.ensureLoaded();

        // 根据怪物类型选择图标
        let monsterType = 'default';
        if (monster.creature_type) {
            const creatureType = monster.creature_type.toLowerCase();
            if (this.config && this.config.monsters && this.config.monsters[creatureType]) {
                monsterType = creatureType;
            }
        }

        const isQuestMonster = monster.quest_monster_id != null;
        const isBoss = monster.is_boss || false;

        const icon = this.createMonsterIcon(monsterType, isQuestMonster, isBoss);
        icon.title = monster.name || '怪物';

        // 【修复】设置 pointer-events: none，让鼠标事件穿透到瓦片
        // 这样悬停提示工具栏才能正常工作
        icon.style.pointerEvents = 'none';

        tile.appendChild(icon);
        return icon;
    }
}

// 创建全局实例
const characterSprites = new CharacterSprites();

// 导出到全局作用域
window.CharacterSprites = CharacterSprites;
window.characterSprites = characterSprites;

