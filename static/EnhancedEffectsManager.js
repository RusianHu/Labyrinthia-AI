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
     */
    createEnvironmentParticles(mapElement, floorTheme) {
        if (typeof anime === 'undefined') return;

        // 移除旧的粒子系统
        this.clearEnvironmentParticles();

        const config = this.getParticleConfig(floorTheme);
        if (!config) return;

        const container = document.createElement('div');
        container.className = 'environment-particles';
        container.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            z-index: 1;
            overflow: hidden;
        `;

        // 创建粒子
        const particles = [];
        for (let i = 0; i < config.count; i++) {
            const particle = document.createElement('div');
            particle.className = `particle-${config.type}`;
            particle.style.cssText = `
                position: absolute;
                width: ${config.size}px;
                height: ${config.size}px;
                background: ${config.color};
                border-radius: ${config.shape === 'circle' ? '50%' : '0'};
                opacity: ${config.opacity};
                left: ${Math.random() * 100}%;
                top: ${Math.random() * 100}%;
            `;
            container.appendChild(particle);
            particles.push(particle);
        }

        mapElement.appendChild(container);

        // 创建粒子动画
        this.animateParticles(particles, config);

        // 存储粒子系统
        this.particleSystems.set(floorTheme, { container, particles, config });
    }

    /**
     * 获取粒子配置
     */
    getParticleConfig(floorTheme) {
        const configs = {
            // 地牢主题 - 落灰效果
            'normal': {
                type: 'dust',
                count: 20,
                size: 2,
                color: 'rgba(200, 200, 200, 0.3)',
                shape: 'circle',
                opacity: 0.3,
                speed: 'slow'
            },
            'abandoned': {
                type: 'dust',
                count: 30,
                size: 3,
                color: 'rgba(150, 150, 150, 0.4)',
                shape: 'circle',
                opacity: 0.4,
                speed: 'slow'
            },
            'cave': {
                type: 'dust',
                count: 25,
                size: 2,
                color: 'rgba(100, 100, 100, 0.3)',
                shape: 'circle',
                opacity: 0.3,
                speed: 'slow'
            },
            // 地上主题 - 自然效果
            'grassland': {
                type: 'leaves',
                count: 15,
                size: 4,
                color: 'rgba(76, 175, 80, 0.6)',
                shape: 'square',
                opacity: 0.6,
                speed: 'medium'
            },
            'town': {
                type: 'sunlight',
                count: 10,
                size: 3,
                color: 'rgba(255, 235, 59, 0.4)',
                shape: 'circle',
                opacity: 0.4,
                speed: 'very-slow'
            }
        };

        return configs[floorTheme] || null;
    }

    /**
     * 动画化粒子
     */
    animateParticles(particles, config) {
        const speedMap = {
            'very-slow': 8000,
            'slow': 5000,
            'medium': 3000,
            'fast': 1500
        };

        const duration = speedMap[config.speed] || 5000;

        particles.forEach((particle, index) => {
            anime({
                targets: particle,
                translateY: config.type === 'dust' || config.type === 'leaves' 
                    ? ['-100%', '100vh'] 
                    : ['0', '20px'],
                translateX: config.type === 'leaves'
                    ? () => [0, anime.random(-50, 50)]
                    : 0,
                opacity: [config.opacity, 0],
                duration: duration,
                delay: index * (duration / particles.length),
                easing: 'linear',
                loop: true
            });
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

