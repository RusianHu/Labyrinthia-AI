// Labyrinthia AI - 增强版特效管理器
// 使用 anime.js 实现更精确和丰富的动画效果

/**
 * 增强版特效管理器类
 * 使用 anime.js timeline 替代 setTimeout，提供更精确的动画控制
 */
class EnhancedEffectsManager {
    constructor(game) {
        this.game = game;
        this.activeAnimations = new Map(); // 存储活跃的动画
        this.particleSystems = new Map(); // 存储粒子系统

        // 【新增】粒子层同步相关
        this.scrollContainer = null;  // .dungeon-content 滚动容器
        this.lastScrollLeft = 0;
        this.lastScrollTop = 0;
        this.scrollSyncRAF = null;  // requestAnimationFrame ID
        this._boundSyncParticlePosition = null;  // 绑定的同步函数

        // 【新增】粒子层缩放相关
        this.mapContainer = null;  // #map-container 容器
        this.currentScale = 1;  // 当前缩放比例
        this._boundSyncParticleScale = null;  // 绑定的缩放同步函数

        // 确保 anime.js 已加载
        if (typeof anime === 'undefined') {
            console.warn('Anime.js not loaded, effects will be limited');
        }
    }

    /**
     * 显示任务完成特效（使用 anime.js timeline）
     */
    showQuestCompletionEffect(effect) {
        const effectContainer = document.createElement('div');
        effectContainer.className = 'quest-completion-effect';
        effectContainer.innerHTML = `
            <div class="quest-completion-content">
                <div class="quest-completion-icon">🎉</div>
                <div class="quest-completion-title">任务完成！</div>
                <div class="quest-completion-quest-name">${effect.quest_title}</div>
                <div class="quest-completion-reward">获得 ${effect.experience_reward} 经验值</div>
                <div class="quest-completion-particles">
                    ${Array(12).fill(0).map(() => '<div class="particle"></div>').join('')}
                </div>
            </div>
        `;

        document.body.appendChild(effectContainer);

        // 使用 anime.js timeline 创建复杂动画序列
        const timeline = anime.timeline({
            easing: 'easeOutExpo',
            complete: () => {
                // 动画完成后移除元素
                if (effectContainer.parentNode) {
                    effectContainer.parentNode.removeChild(effectContainer);
                }
            }
        });

        // 阶段1: 图标和标题出现
        timeline.add({
            targets: effectContainer.querySelector('.quest-completion-icon'),
            scale: [0, 1.5, 1],
            rotate: [0, 360],
            duration: 800,
            easing: 'easeOutElastic(1, .6)'
        }).add({
            targets: effectContainer.querySelector('.quest-completion-title'),
            opacity: [0, 1],
            translateY: [-20, 0],
            duration: 500
        }, '-=400') // 提前400ms开始
        .add({
            targets: effectContainer.querySelector('.quest-completion-quest-name'),
            opacity: [0, 1],
            translateY: [-20, 0],
            duration: 500
        }, '-=300')
        .add({
            targets: effectContainer.querySelector('.quest-completion-reward'),
            opacity: [0, 1],
            scale: [0.8, 1],
            duration: 500
        }, '-=300');

        // 阶段2: 粒子动画
        const particles = effectContainer.querySelectorAll('.particle');
        timeline.add({
            targets: particles,
            translateX: () => anime.random(-200, 200),
            translateY: () => anime.random(-200, 200),
            scale: [0, anime.random(0.5, 1.5)],
            opacity: [1, 0],
            duration: 2000,
            delay: anime.stagger(50),
            easing: 'easeOutQuad'
        }, '-=500');

        // 阶段3: 淡出
        timeline.add({
            targets: effectContainer,
            opacity: [1, 0],
            duration: 1000,
            delay: 2000
        });

        // 播放音效
        this.playQuestCompletionSound();

        // 添加消息到日志
        this.game.addMessage(effect.message, 'success');

        // 存储动画引用
        this.activeAnimations.set('quest-completion', timeline);
    }

    /**
     * 显示怪物击败粉碎特效
     */
    showMonsterDefeatEffect(monster, tileElement) {
        console.log('[EnhancedEffectsManager] showMonsterDefeatEffect called:', {
            monster: monster,
            tileElement: !!tileElement,
            animeAvailable: typeof anime !== 'undefined'
        });

        if (!tileElement || typeof anime === 'undefined') {
            console.warn('Cannot show defeat effect: missing element or anime.js');
            return;
        }

        // 【修复】获取怪物图标元素 - 使用正确的类名 .character-monster
        const monsterIcon = tileElement.querySelector('.character-monster');
        console.log('[EnhancedEffectsManager] Monster icon found:', !!monsterIcon);
        if (!monsterIcon) {
            console.warn('[EnhancedEffectsManager] No monster icon found in tile element');
            console.log('[EnhancedEffectsManager] Tile element HTML:', tileElement.innerHTML);
            return;
        }

        // 创建粉碎碎片
        const fragmentCount = 8;
        const fragments = [];
        const tileRect = tileElement.getBoundingClientRect();

        for (let i = 0; i < fragmentCount; i++) {
            const fragment = document.createElement('div');
            fragment.className = 'monster-fragment';
            fragment.style.cssText = `
                position: fixed;
                left: ${tileRect.left + tileRect.width / 2}px;
                top: ${tileRect.top + tileRect.height / 2}px;
                width: 10px;
                height: 10px;
                background: ${monster.is_boss ? '#ff4444' : '#666'};
                border-radius: 2px;
                pointer-events: none;
                z-index: 9999;
            `;
            document.body.appendChild(fragment);
            fragments.push(fragment);
        }

        // 创建粉碎动画
        const timeline = anime.timeline({
            complete: () => {
                // 清理碎片
                fragments.forEach(f => {
                    if (f.parentNode) f.parentNode.removeChild(f);
                });
                // 移除怪物图标（已经淡出到透明）
                if (monsterIcon && monsterIcon.parentNode) {
                    monsterIcon.parentNode.removeChild(monsterIcon);
                }
            }
        });

        // 怪物图标闪烁和缩小
        timeline.add({
            targets: monsterIcon,
            opacity: [1, 0],
            scale: [1, 0],
            duration: 300,
            easing: 'easeInQuad'
        });

        // 碎片爆炸效果
        timeline.add({
            targets: fragments,
            translateX: (el, i) => {
                const angle = (i / fragmentCount) * Math.PI * 2;
                return Math.cos(angle) * anime.random(50, 150);
            },
            translateY: (el, i) => {
                const angle = (i / fragmentCount) * Math.PI * 2;
                return Math.sin(angle) * anime.random(50, 150);
            },
            rotate: () => anime.random(-720, 720),
            opacity: [1, 0],
            scale: [1, 0],
            duration: 800,
            easing: 'easeOutQuad'
        }, '-=200');

        // Boss 额外特效
        if (monster.is_boss) {
            this.showBossDefeatEffect(tileRect);
        }

        // 存储动画引用
        this.activeAnimations.set(`monster-defeat-${monster.id}`, timeline);
    }

    /**
     * Boss 击败额外特效
     */
    showBossDefeatEffect(tileRect) {
        const shockwave = document.createElement('div');
        shockwave.style.cssText = `
            position: fixed;
            left: ${tileRect.left + tileRect.width / 2}px;
            top: ${tileRect.top + tileRect.height / 2}px;
            width: 20px;
            height: 20px;
            border: 3px solid #ff4444;
            border-radius: 50%;
            pointer-events: none;
            z-index: 9998;
            transform: translate(-50%, -50%);
        `;
        document.body.appendChild(shockwave);

        anime({
            targets: shockwave,
            width: 300,
            height: 300,
            opacity: [1, 0],
            duration: 1000,
            easing: 'easeOutQuad',
            complete: () => {
                if (shockwave.parentNode) {
                    shockwave.parentNode.removeChild(shockwave);
                }
            }
        });
    }

    /**
     * 创建环境粒子系统
     * @param {HTMLElement} mapElement - 地图元素（map-grid），用于获取尺寸
     * @param {string} floorTheme - 地板主题
     */
    createEnvironmentParticles(mapElement, floorTheme) {
        console.log('[EnhancedEffectsManager] createEnvironmentParticles called:', {
            mapElement: !!mapElement,
            floorTheme: floorTheme,
            animeAvailable: typeof anime !== 'undefined'
        });

        if (typeof anime === 'undefined') {
            console.warn('[EnhancedEffectsManager] anime.js not available');
            return;
        }

        // 【重要】获取 map-container 作为粒子层的父容器
        // 这样粒子层不会被 map-grid 的 innerHTML 清除
        // 如果没有 map-container（测试页面），则使用 mapElement 本身
        const mapContainer = document.getElementById('map-container') || mapElement;
        if (!mapContainer) {
            console.warn('[EnhancedEffectsManager] No valid container found');
            return;
        }

        // 【优化】检查是否已有相同主题的粒子系统
        // 如果已存在且DOM元素仍然有效，则不需要重建
        const existingSystem = this.particleSystems.get(floorTheme);
        const existingContainer = mapContainer.querySelector('.environment-particles');

        if (existingSystem && existingContainer && existingSystem.container === existingContainer) {
            console.log('[EnhancedEffectsManager] Particle system already exists for theme:', floorTheme, '- skipping rebuild');
            // 确保同步机制仍然有效
            if (!this._boundSyncParticlePosition || !this._boundSyncParticleScale) {
                console.log('[EnhancedEffectsManager] Re-initializing particle sync mechanisms');
                this.destroyParticlePositionSync();
                this.destroyParticleScaleSync();
                this.initParticlePositionSync();
                this.initParticleScaleSync();
            }
            return;
        }

        // 移除旧的粒子系统（如果存在且主题不同）
        if (existingContainer) {
            existingContainer.remove();
            console.log('[EnhancedEffectsManager] Removed old particle container');
        }

        const config = this.getParticleConfig(floorTheme);
        console.log('[EnhancedEffectsManager] Particle config:', config);

        if (!config) {
            console.warn('[EnhancedEffectsManager] No config found for theme:', floorTheme);
            return;
        }

        // 【重要】创建独立的粒子容器层
        // 使用绝对定位覆盖在 map-grid 上方，但在 fog-canvas 下方
        const container = document.createElement('div');
        container.className = 'environment-particles';
        container.id = 'particle-layer';

        // 【修复】保存粒子容器引用，供同步方法使用
        this.particleContainer = container;

        // 【修复】使用 100% 宽高自动匹配 map-container
        // 不依赖 map-grid 的尺寸（可能还未渲染）
        // z-index 150 确保粒子在迷雾层（z-index 100）之上可见
        // 【新增】transform-origin: top left 与 map-grid 保持一致
        container.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            z-index: 150;
            overflow: hidden;
            transform-origin: top left;
        `;

        console.log('[EnhancedEffectsManager] Particle container created with 100% size, z-index: 150');

        // 创建粒子/光线
        const particles = [];

        // 特殊处理：阳光光线
        if (config.type === 'sunlight' && config.shape === 'ray') {
            for (let i = 0; i < config.count; i++) {
                const ray = document.createElement('div');
                ray.className = 'light-ray';

                // 光线参数
                const rayWidth = config.size + anime.random(-20, 20);
                const rayHeight = (typeof config.rayHeight === 'number' ? config.rayHeight : 300); // 光线长度
                const angleMin = Array.isArray(config.angleRange) ? config.angleRange[0] : -15;
                const angleMax = Array.isArray(config.angleRange) ? config.angleRange[1] : 15;
                const rayAngle = anime.random(angleMin, angleMax); // 倾斜角度
                const rayLeft = anime.random(0, 100); // 水平位置

                ray.style.cssText = `
                    position: absolute;
                    width: ${rayWidth}px;
                    height: ${rayHeight}px;
                    left: ${rayLeft}%;
                    top: -50px;
                    transform: rotate(${rayAngle}deg);
                    background: linear-gradient(to bottom,
                        rgba(255, 245, 200, 0) 0%,
                        rgba(255, 235, 150, ${config.opacity * 0.8}) 20%,
                        rgba(255, 235, 100, ${config.opacity}) 50%,
                        rgba(255, 235, 150, ${config.opacity * 0.8}) 80%,
                        rgba(255, 245, 200, 0) 100%
                    );
                    filter: blur(${typeof config.blur === 'number' ? config.blur : 8}px);
                    pointer-events: none;
                    z-index: 1;
                    opacity: 0;
                    ${config.blend ? `mix-blend-mode: ${config.blend};` : ''}
                    ${config.glow ? `box-shadow: 0 0 ${config.glowSize || 10}px ${config.glowColor || 'rgba(255, 238, 150, 0.25)'};` : ''}
                `;

                // 存储光线参数
                ray.dataset.rayAngle = rayAngle;
                ray.dataset.rayLeft = rayLeft;

                container.appendChild(ray);
                particles.push(ray);
            }
        } else {
            // 普通粒子系统 - 多层系统（背景、中景、前景）
            for (let i = 0; i < config.count; i++) {
                // 随机层次（模拟远近）
                const layer = Math.random();
                let sizeMultiplier, opacityMultiplier, zIndex, blur;

                if (layer < 0.3) {
                    // 背景层 - 远处（大、慢、模糊）
                    sizeMultiplier = 1.5;
                    opacityMultiplier = 0.4;
                    zIndex = 1;
                    blur = 2;
                } else if (layer < 0.7) {
                    // 中景层 - 中等
                    sizeMultiplier = 1.0;
                    opacityMultiplier = 0.7;
                    zIndex = 2;
                    blur = 1;
                } else {
                    // 前景层 - 近处（小、快、清晰）
                    sizeMultiplier = 0.7;
                    opacityMultiplier = 1.0;
                    zIndex = 3;
                    blur = 0;
                }

                const actualSize = config.size * sizeMultiplier;
                const actualOpacity = config.opacity * opacityMultiplier;
                const left = Math.random() * 100;
                const top = Math.random() * 100;

                let particle;
                if (config.useEmoji && config.emoji) {
                    // 使用 Emoji 渲染
                    particle = document.createElement('span');
                    particle.className = `emoji-particle particle-${config.type}`;
                    let styleText = `
                        position: absolute;
                        left: ${left}%;
                        top: ${top}%;
                        z-index: ${zIndex};
                        opacity: ${actualOpacity};
                        pointer-events: none;
                        line-height: 1;
                        font-size: ${Math.max(10, Math.round(actualSize * 2))}px;
                    `;
                    if (blur > 0) {
                        styleText += `filter: blur(${blur}px);`;
                    }
                    particle.style.cssText = styleText;
                    particle.textContent = config.emoji;
                } else {
                    // 使用普通彩色粒子渲染
                    particle = document.createElement('div');
                    particle.className = `particle-${config.type}`;

                    let styleText = `
                        position: absolute;
                        width: ${actualSize}px;
                        height: ${actualSize}px;
                        background: ${config.color};
                        border-radius: ${config.shape === 'circle' ? '50%' : '0'};
                        opacity: ${actualOpacity};
                        left: ${left}%;
                        top: ${top}%;
                        z-index: ${zIndex};
                        pointer-events: none;
                    `;

                    // 【优化】添加光晕效果
                    if (config.glow) {
                        const glowSize = config.glowSize || 3;
                        const glowColor = config.glowColor || config.color;
                        styleText += `
                            box-shadow: 0 0 ${glowSize}px ${glowColor}, 0 0 ${glowSize * 1.5}px ${glowColor};
                        `;
                    }

                    if (blur > 0) {
                        styleText += `filter: blur(${blur}px);`;
                    }

                    particle.style.cssText = styleText;
                }

                // 存储层次信息用于动画速度调整
                particle.dataset.layer = layer < 0.3 ? 'back' : (layer < 0.7 ? 'mid' : 'front');
                particle.dataset.speedMultiplier = layer < 0.3 ? '0.7' : (layer < 0.7 ? '1.0' : '1.3');

                container.appendChild(particle);
                particles.push(particle);
            }
        }

        // 【重要】将粒子容器添加到 map-container，而不是 map-grid
        // 这样粒子层不会被 map-grid 的 innerHTML 清除
        mapContainer.appendChild(container);
        console.log('[EnhancedEffectsManager] Particle container appended to map-container, particles created:', particles.length);

        // 创建粒子动画
        this.animateParticles(particles, config);

        // 存储粒子系统
        this.particleSystems.set(floorTheme, { container, particles, config });
        console.log('[EnhancedEffectsManager] Particle system created successfully for theme:', floorTheme);

        // 【新增】初始化粒子层位置同步
        // 先销毁旧的同步（如果有）
        this.destroyParticlePositionSync();
        this.destroyParticleScaleSync();

        // 初始化新的同步
        this.initParticlePositionSync();
        this.initParticleScaleSync();
    }

    /**
     * 获取粒子配置
     */
    getParticleConfig(floorTheme) {
        const configs = {
            // ========== 地牢主题 - 落灰效果 ==========
            'normal': {
                type: 'dust',
                count: 20,
                size: 7,  // 增大尺寸：4 → 7
                color: 'rgba(200, 200, 200, 0.85)',  // 提高不透明度：0.6 → 0.85
                shape: 'circle',
                opacity: 0.85,
                speed: 'slow',
                glow: true,  // 添加光晕
                glowColor: 'rgba(220, 220, 220, 0.6)',
                glowSize: 3
            },
            'abandoned': {
                type: 'dust',
                count: 30,
                size: 8,  // 增大尺寸：5 → 8
                color: 'rgba(150, 150, 150, 0.9)',  // 提高不透明度：0.7 → 0.9
                shape: 'circle',
                opacity: 0.9,
                speed: 'slow',
                glow: true,
                glowColor: 'rgba(170, 170, 170, 0.7)',
                glowSize: 4
            },
            'cave': {
                type: 'dust',
                count: 25,
                size: 7,  // 增大尺寸：4 → 7
                color: 'rgba(100, 100, 100, 0.85)',  // 提高不透明度：0.6 → 0.85
                shape: 'circle',
                opacity: 0.85,
                speed: 'slow',
                glow: true,
                glowColor: 'rgba(120, 120, 120, 0.6)',
                glowSize: 3
            },
            'magic': {
                type: 'dust',
                count: 25,
                size: 8,  // 增大尺寸：5 → 8
                color: 'rgba(138, 43, 226, 0.9)',  // 提高不透明度：0.7 → 0.9
                shape: 'circle',
                opacity: 0.9,
                speed: 'slow',
                glow: true,
                glowColor: 'rgba(138, 43, 226, 0.8)',  // 紫色光晕更强
                glowSize: 6  // 更大的光晕
            },
            'combat': {
                type: 'dust',
                count: 20,
                size: 7,  // 增大尺寸：4 → 7
                color: 'rgba(200, 50, 50, 0.85)',  // 提高不透明度：0.6 → 0.85
                shape: 'circle',
                opacity: 0.85,
                speed: 'medium',
                glow: true,
                glowColor: 'rgba(255, 80, 80, 0.7)',  // 红色光晕
                glowSize: 5
            },

            // ========== 地上主题 - 自然效果 ==========
            'grassland': {
                type: 'leaves',
                count: 20,
                size: 9,
                color: 'rgba(76, 175, 80, 0.95)',
                shape: 'square',
                opacity: 0.95,
                speed: 'medium',
                glow: true,
                glowColor: 'rgba(76, 175, 80, 0.6)',
                glowSize: 3,
                // Emoji 粒子默认启用：🍂
                useEmoji: true,
                emoji: '🍂'
            },
            'town': {
                type: 'sunlight',
                count: 7,
                size: 140,
                color: 'rgba(255, 235, 59, 0.35)',
                shape: 'ray',
                opacity: 0.42,
                speed: 'very-slow',
                rayHeight: 420,
                angleRange: [-16, 16],
                blur: 6,
                blend: 'screen',
                glow: true,
                glowColor: 'rgba(255, 238, 150, 0.25)',
                glowSize: 10,
                swing: 3.2,
                sway: 2.2,
                opacityCurve: [0.38, 0.9, 0.6, 0.38]
            },
            'desert': {
                type: 'sand',
                count: 35,
                size: 6,  // 增大尺寸：3 → 6
                color: 'rgba(244, 164, 96, 0.9)',  // 提高不透明度：0.7 → 0.9
                shape: 'circle',
                opacity: 0.9,
                speed: 'fast',
                glow: true,
                glowColor: 'rgba(244, 164, 96, 0.7)',  // 橙色光晕
                glowSize: 4
            },
            'snowfield': {
                type: 'snow',
                count: 40,
                size: 8,  // 增大尺寸：5 → 8
                color: 'rgba(255, 255, 255, 1.0)',  // 完全不透明：0.9 → 1.0
                shape: 'circle',
                opacity: 1.0,
                speed: 'medium',
                glow: true,
                glowColor: 'rgba(255, 255, 255, 0.9)',  // 白色光晕更强
                glowSize: 5,
                // Emoji 粒子默认启用：❄️
                useEmoji: true,
                emoji: '❄️'
            },
            'farmland': {
                type: 'leaves',
                count: 15,
                size: 8,  // 增大尺寸：5 → 8
                color: 'rgba(139, 195, 74, 0.9)',  // 提高不透明度：0.7 → 0.9
                shape: 'square',
                opacity: 0.9,
                speed: 'slow',
                glow: true,
                glowColor: 'rgba(139, 195, 74, 0.6)',  // 绿色光晕
                glowSize: 3
            },

            // ========== 特殊天气效果（可选） ==========
            'rainy': {
                type: 'rain',
                count: 50,  // 雨水需要更多粒子
                size: 2,
                color: 'rgba(173, 216, 230, 0.6)',
                shape: 'circle',
                opacity: 0.6,
                speed: 'fast'
            }
        };

        return configs[floorTheme] || null;
    }

    /**
     * 【新增】初始化粒子层位置同步
     * 监听滚动容器的滚动事件，同步更新粒子层位置
     */
    initParticlePositionSync() {
        // 获取滚动容器
        const mapContainer = document.getElementById('map-container');
        if (!mapContainer) {
            console.warn('[EnhancedEffectsManager] map-container not found, cannot sync particle position');
            return;
        }

        this.scrollContainer = mapContainer.querySelector('.dungeon-content');
        if (!this.scrollContainer) {
            console.warn('[EnhancedEffectsManager] .dungeon-content not found, cannot sync particle position');
            return;
        }

        // 绑定同步函数
        this._boundSyncParticlePosition = this.syncParticlePosition.bind(this);

        // 监听滚动事件（使用 passive 优化性能）
        this.scrollContainer.addEventListener('scroll', this._boundSyncParticlePosition, { passive: true });

        // 初始化滚动位置
        this.lastScrollLeft = this.scrollContainer.scrollLeft;
        this.lastScrollTop = this.scrollContainer.scrollTop;

        console.log('[EnhancedEffectsManager] Particle position sync initialized');
    }

    /**
     * 【新增】同步粒子层位置
     * 根据滚动容器的滚动位置，更新粒子层的 transform
     */
    syncParticlePosition() {
        // 使用 requestAnimationFrame 优化性能
        if (this.scrollSyncRAF) {
            return;  // 已经有待处理的同步任务
        }

        this.scrollSyncRAF = requestAnimationFrame(() => {
            this.scrollSyncRAF = null;

            if (!this.scrollContainer || !this.particleContainer) {
                return;
            }

            const scrollLeft = this.scrollContainer.scrollLeft;
            const scrollTop = this.scrollContainer.scrollTop;

            // 只在滚动位置变化时更新
            if (scrollLeft !== this.lastScrollLeft || scrollTop !== this.lastScrollTop) {
                // 【修改】同时应用 translate（滚动同步）和 scale（缩放同步）
                // 注意：translate 是负值，因为要反向移动
                this.particleContainer.style.transform = `translate(${-scrollLeft}px, ${-scrollTop}px) scale(${this.currentScale})`;

                this.lastScrollLeft = scrollLeft;
                this.lastScrollTop = scrollTop;
            }
        });
    }

    /**
     * 【新增】销毁粒子层位置同步
     * 移除滚动事件监听器
     */
    destroyParticlePositionSync() {
        if (this.scrollContainer && this._boundSyncParticlePosition) {
            this.scrollContainer.removeEventListener('scroll', this._boundSyncParticlePosition);
            this._boundSyncParticlePosition = null;
            console.log('[EnhancedEffectsManager] Particle position sync destroyed');
        }

        if (this.scrollSyncRAF) {
            cancelAnimationFrame(this.scrollSyncRAF);
            this.scrollSyncRAF = null;
        }

        this.scrollContainer = null;
        this.lastScrollLeft = 0;
        this.lastScrollTop = 0;
    }

    /**
     * 【新增】初始化粒子层缩放同步
     * 监听地图缩放事件，同步更新粒子层缩放
     */
    initParticleScaleSync() {
        // 获取 map-container
        this.mapContainer = document.getElementById('map-container');
        if (!this.mapContainer) {
            console.warn('[EnhancedEffectsManager] map-container not found, cannot sync particle scale');
            return;
        }

        // 绑定缩放同步函数
        this._boundSyncParticleScale = this.syncParticleScale.bind(this);

        // 监听 mapZoomChanged 自定义事件
        this.mapContainer.addEventListener('mapZoomChanged', this._boundSyncParticleScale);

        // 初始化缩放比例（从 MapZoomManager 获取）
        const mapZoomManager = window.game?.mapZoomManager;
        if (mapZoomManager) {
            this.currentScale = mapZoomManager.getZoom();
        } else {
            this.currentScale = 1;
        }

        console.log('[EnhancedEffectsManager] Particle scale sync initialized, initial scale:', this.currentScale);
    }

    /**
     * 【新增】同步粒子层缩放
     * 根据地图缩放比例，更新粒子层的 scale transform
     */
    syncParticleScale(event) {
        if (!this.particleContainer) {
            return;
        }

        // 从事件中获取新的缩放比例
        const newScale = event.detail.scale;

        if (newScale !== this.currentScale) {
            this.currentScale = newScale;

            // 更新粒子层的 transform
            // 需要同时保持 translate（滚动同步）和 scale（缩放同步）
            const scrollLeft = this.lastScrollLeft || 0;
            const scrollTop = this.lastScrollTop || 0;

            this.particleContainer.style.transform = `translate(${-scrollLeft}px, ${-scrollTop}px) scale(${newScale})`;

            console.log('[EnhancedEffectsManager] Particle scale synced:', newScale);
        }
    }

    /**
     * 【新增】销毁粒子层缩放同步
     * 移除缩放事件监听器
     */
    destroyParticleScaleSync() {
        if (this.mapContainer && this._boundSyncParticleScale) {
            this.mapContainer.removeEventListener('mapZoomChanged', this._boundSyncParticleScale);
            this._boundSyncParticleScale = null;
            console.log('[EnhancedEffectsManager] Particle scale sync destroyed');
        }

        this.mapContainer = null;
        this.currentScale = 1;
    }

    /**
     * 动画化粒子 - 游戏级别的真实效果
     */
    animateParticles(particles, config) {
        const speedMap = {
            'very-slow': 12000,
            'slow': 8000,
            'medium': 5000,
            'fast': 2000
        };

        const baseDuration = speedMap[config.speed] || 5000;

        particles.forEach((particle, index) => {
            // 为每个粒子生成随机参数，模拟真实的不规则性
            const speedMultiplier = parseFloat(particle.dataset.speedMultiplier || 1.0);
            const randomDuration = (baseDuration / speedMultiplier) + anime.random(-1000, 1000);
            const randomDelay = index * (baseDuration / particles.length) + anime.random(0, 500);

            // 根据粒子类型应用不同的动画
            switch(config.type) {
                case 'dust':
                    this.animateDust(particle, randomDuration, randomDelay, config);
                    break;
                case 'leaves':
                    this.animateLeaves(particle, randomDuration, randomDelay, config);
                    break;
                case 'sunlight':
                    this.animateSunlight(particle, randomDuration, randomDelay, config);
                    break;
                case 'rain':
                    this.animateRain(particle, randomDuration, randomDelay, config);
                    break;
                case 'snow':
                    this.animateSnow(particle, randomDuration, randomDelay, config);
                    break;
                case 'sand':
                    this.animateSand(particle, randomDuration, randomDelay, config);
                    break;
                default:
                    this.animateDefault(particle, randomDuration, randomDelay, config);
            }
        });
    }

    /**
     * 落灰动画 - 轻微飘动 + 不规则下落
     */
    animateDust(particle, duration, delay, config) {
        const timeline = anime.timeline({
            loop: true,
            delay: delay
        });

        // 主下落动画
        timeline.add({
            targets: particle,
            translateY: ['-20%', '120%'],
            translateX: [
                { value: () => anime.random(-15, 15), duration: duration * 0.3 },
                { value: () => anime.random(-15, 15), duration: duration * 0.4 },
                { value: () => anime.random(-15, 15), duration: duration * 0.3 }
            ],
            opacity: [
                { value: config.opacity * 0.7, duration: duration * 0.2 },
                { value: config.opacity, duration: duration * 0.6 },
                { value: config.opacity * 0.3, duration: duration * 0.2 }
            ],
            rotate: () => anime.random(-30, 30),
            duration: duration,
            easing: 'linear'
        });
    }

    /**
     * 落叶动画 - 摇摆飘落 + 自然旋转
     */
    animateLeaves(particle, duration, delay, config) {
        const swingAmplitude = anime.random(30, 60);

        const timeline = anime.timeline({
            loop: true,
            delay: delay
        });

        timeline.add({
            targets: particle,
            translateY: ['-20%', '120%'],
            translateX: [
                { value: -swingAmplitude, duration: duration * 0.25, easing: 'easeInOutSine' },
                { value: swingAmplitude, duration: duration * 0.25, easing: 'easeInOutSine' },
                { value: -swingAmplitude, duration: duration * 0.25, easing: 'easeInOutSine' },
                { value: 0, duration: duration * 0.25, easing: 'easeInOutSine' }
            ],
            rotate: [
                { value: () => anime.random(-180, 180), duration: duration * 0.5 },
                { value: () => anime.random(-360, 360), duration: duration * 0.5 }
            ],
            opacity: config.opacity,
            duration: duration,
            easing: 'linear'
        });
    }

    /**
     * 阳光光线动画 - 缓慢摇曳 + 透明度变化
     */
    animateSunlight(particle, duration, delay, config) {
        // 检查是否是光线（而不是光斑）
        if (particle.className === 'light-ray') {
            const baseAngle = parseFloat(particle.dataset.rayAngle || 0);
            const baseLeft = parseFloat(particle.dataset.rayLeft || 50);

            const timeline = anime.timeline({
                loop: true,
                delay: delay
            });

            const swing = (typeof config.swing === 'number') ? config.swing : 3;
            const sway = (typeof config.sway === 'number') ? config.sway : 2;
            const curve = Array.isArray(config.opacityCurve) ? config.opacityCurve : [0.3, 0.8, 0.5, 0.3];

            timeline.add({
                targets: particle,
                // 光线摇曳（角度变化）
                rotate: [
                    { value: baseAngle - swing, duration: duration * 0.5, easing: 'easeInOutSine' },
                    { value: baseAngle + swing, duration: duration * 0.5, easing: 'easeInOutSine' }
                ],
                // 水平位置微调
                left: [
                    { value: `${baseLeft - sway}%`, duration: duration * 0.5, easing: 'easeInOutSine' },
                    { value: `${baseLeft + sway}%`, duration: duration * 0.5, easing: 'easeInOutSine' }
                ],
                // 透明度呼吸（可配置）
                opacity: [
                    { value: curve[0], duration: duration * 0.25, easing: 'easeInOutQuad' },
                    { value: curve[1], duration: duration * 0.25, easing: 'easeInOutQuad' },
                    { value: curve[2], duration: duration * 0.25, easing: 'easeInOutQuad' },
                    { value: curve[3], duration: duration * 0.25, easing: 'easeInOutQuad' }
                ],
                duration: duration
            });
        } else {
            // 旧版光斑动画（备用）
            const timeline = anime.timeline({
                loop: true,
                delay: delay
            });

            timeline.add({
                targets: particle,
                scale: [
                    { value: 0.8, duration: duration * 0.5, easing: 'easeInOutQuad' },
                    { value: 1.2, duration: duration * 0.5, easing: 'easeInOutQuad' }
                ],
                opacity: [
                    { value: config.opacity * 0.3, duration: duration * 0.5, easing: 'easeInOutQuad' },
                    { value: config.opacity * 0.8, duration: duration * 0.5, easing: 'easeInOutQuad' }
                ],
                duration: duration
            });
        }
    }

    /**
     * 雨水动画 - 快速斜向下落
     */
    animateRain(particle, duration, delay, config) {
        anime({
            targets: particle,
            translateY: ['-10%', '110%'],
            translateX: [0, anime.random(20, 40)], // 斜向
            opacity: [config.opacity, config.opacity * 0.5],
            duration: duration * 0.4, // 雨水更快
            delay: delay,
            easing: 'linear',
            loop: true
        });
    }

    /**
     * 雪花动画 - 轻盈飘摇
     */
    animateSnow(particle, duration, delay, config) {
        const swingAmplitude = anime.random(20, 40);

        const timeline = anime.timeline({
            loop: true,
            delay: delay
        });

        timeline.add({
            targets: particle,
            translateY: ['-20%', '120%'],
            translateX: [
                { value: -swingAmplitude, duration: duration * 0.33, easing: 'easeInOutSine' },
                { value: swingAmplitude, duration: duration * 0.34, easing: 'easeInOutSine' },
                { value: 0, duration: duration * 0.33, easing: 'easeInOutSine' }
            ],
            rotate: [
                { value: () => anime.random(-90, 90), duration: duration * 0.5 },
                { value: () => anime.random(-180, 180), duration: duration * 0.5 }
            ],
            opacity: [
                { value: config.opacity, duration: duration * 0.8 },
                { value: config.opacity * 0.5, duration: duration * 0.2 }
            ],
            duration: duration,
            easing: 'linear'
        });
    }

    /**
     * 沙尘动画 - 快速飘动 + 随机方向
     */
    animateSand(particle, duration, delay, config) {
        const timeline = anime.timeline({
            loop: true,
            delay: delay
        });

        timeline.add({
            targets: particle,
            translateY: ['-20%', '120%'],
            translateX: [
                { value: () => anime.random(-50, 50), duration: duration * 0.25 },
                { value: () => anime.random(-50, 50), duration: duration * 0.25 },
                { value: () => anime.random(-50, 50), duration: duration * 0.25 },
                { value: () => anime.random(-50, 50), duration: duration * 0.25 }
            ],
            opacity: [
                { value: config.opacity * 0.5, duration: duration * 0.3 },
                { value: config.opacity, duration: duration * 0.4 },
                { value: config.opacity * 0.3, duration: duration * 0.3 }
            ],
            rotate: () => anime.random(-180, 180),
            duration: duration,
            easing: 'linear'
        });
    }

    /**
     * 默认动画
     */
    animateDefault(particle, duration, delay, config) {
        anime({
            targets: particle,
            translateY: ['-20%', '120%'],
            opacity: config.opacity,
            duration: duration,
            delay: delay,
            easing: 'linear',
            loop: true
        });
    }

    /**
     * 清除环境粒子
     */
    clearEnvironmentParticles() {
        this.particleSystems.forEach(system => {
            if (system.container && system.container.parentNode) {
                system.container.parentNode.removeChild(system.container);
            }
        });
        this.particleSystems.clear();
    }

    /**
     * 播放任务完成音效
     */
    playQuestCompletionSound() {
        try {
            if (typeof AudioContext !== 'undefined') {
                const audioContext = new AudioContext();
                const oscillator = audioContext.createOscillator();
                const gainNode = audioContext.createGain();

                oscillator.connect(gainNode);
                gainNode.connect(audioContext.destination);

                oscillator.frequency.setValueAtTime(523.25, audioContext.currentTime);
                oscillator.frequency.setValueAtTime(659.25, audioContext.currentTime + 0.1);
                oscillator.frequency.setValueAtTime(783.99, audioContext.currentTime + 0.2);

                gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
                gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.5);

                oscillator.start(audioContext.currentTime);
                oscillator.stop(audioContext.currentTime + 0.5);
            }
        } catch (error) {
            console.log('Audio playback not supported or failed');
        }
    }

    /**
     * 停止所有动画
     */
    stopAllAnimations() {
        this.activeAnimations.forEach(animation => {
            if (animation && animation.pause) {
                animation.pause();
            }
        });
        this.activeAnimations.clear();
    }

    /**
     * 清理资源
     */
    cleanup() {
        this.stopAllAnimations();
        this.clearEnvironmentParticles();
    }
}

// 导出到全局
window.EnhancedEffectsManager = EnhancedEffectsManager;

