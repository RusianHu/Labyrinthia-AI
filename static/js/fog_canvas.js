/**
 * Canvas 迷雾效果管理器 - RTS 风格战争迷雾
 * 实现类似星际争霸、魔兽争霸等 RTS 游戏的浓密战争迷雾效果
 * 使用多层渲染和大量粒子营造真实的迷雾感
 */

class FogCanvasManager {
    constructor(canvasId, options = {}) {
        this.canvas = document.getElementById(canvasId);
        if (!this.canvas) {
            console.error('Canvas element not found:', canvasId);
            return;
        }

        this.ctx = this.canvas.getContext('2d');

        // 配置选项 - RTS 风格战争迷雾
        this.config = {
            // 基础迷雾配置
            fogDepth: 180,                      // 迷雾深度（像素）- 增加深度
            fogColor: '#0a0a0a',                // 迷雾颜色 - 深黑色
            fogBaseOpacity: 0.92,               // 基础迷雾不透明度 - 更浓密

            // 多层迷雾配置
            layerCount: 3,                      // 迷雾层数 - 多层叠加
            layerOpacities: [0.4, 0.3, 0.22],   // 各层不透明度
            layerSpeeds: [0.15, 0.25, 0.35],    // 各层移动速度

            // 粒子系统配置
            particleCount: 300,                 // 粒子数量 - 大幅增加
            particleLayers: 3,                  // 粒子层数
            particleSize: { min: 8, max: 35 },  // 粒子大小范围 - 更大的粒子
            particleOpacity: { min: 0.08, max: 0.25 }, // 粒子不透明度范围

            // 动画配置
            animationSpeed: 0.2,                // 整体动画速度 - 更慢更真实
            turbulenceScale: 0.003,             // 湍流强度
            driftSpeed: 0.1,                    // 漂移速度

            // 效果开关
            enableParticles: true,              // 启用粒子效果
            enableTurbulence: true,             // 启用湍流效果
            enableLayeredFog: true,             // 启用多层迷雾

            ...options
        };

        // 粒子数组（多层）
        this.particleLayers = [];

        // 动画状态
        this.animationFrame = null;
        this.time = 0;

        // 噪声偏移（用于湍流效果）
        this.noiseOffsetX = 0;
        this.noiseOffsetY = 0;

        // 初始化
        this.init();
    }

    /**
     * 初始化
     */
    init() {
        // 设置 Canvas 尺寸
        this.resizeCanvas();
        
        // 创建粒子
        if (this.config.enableParticles) {
            this.createParticles();
        }
        
        // 开始渲染循环
        this.startAnimation();
        
        // 监听窗口大小变化
        window.addEventListener('resize', () => this.resizeCanvas());
        
        console.log('✅ FogCanvasManager initialized');
    }

    /**
     * 调整 Canvas 尺寸
     */
    resizeCanvas() {
        const rect = this.canvas.parentElement.getBoundingClientRect();

        // 如果容器尺寸为0，延迟重试
        if (rect.width === 0 || rect.height === 0) {
            console.warn('Canvas parent has zero size, retrying in 100ms...');
            setTimeout(() => this.resizeCanvas(), 100);
            return;
        }

        // 保存显示尺寸
        this.width = rect.width;
        this.height = rect.height;

        // 设置 Canvas 实际尺寸（高DPI支持）
        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = rect.width * dpr;
        this.canvas.height = rect.height * dpr;

        // 设置 Canvas 显示尺寸
        this.canvas.style.width = rect.width + 'px';
        this.canvas.style.height = rect.height + 'px';

        // 重新获取上下文并缩放（避免累积缩放）
        this.ctx = this.canvas.getContext('2d');
        this.ctx.scale(dpr, dpr);

        // 重新创建粒子（因为尺寸改变了）
        if (this.config.enableParticles && this.width > 0 && this.height > 0) {
            this.createParticles();
        }

        console.log(`Canvas resized: ${this.width}x${this.height} (DPR: ${dpr})`);
    }

    /**
     * 创建多层迷雾粒子系统
     */
    createParticles() {
        this.particleLayers = [];

        // 确保有有效的尺寸
        if (!this.width || !this.height || this.width <= 0 || this.height <= 0) {
            console.warn('Cannot create particles: invalid canvas size');
            return;
        }

        const depth = this.config.fogDepth;
        const particlesPerLayer = Math.floor(this.config.particleCount / this.config.particleLayers);

        // 创建多层粒子
        for (let layer = 0; layer < this.config.particleLayers; layer++) {
            const particles = [];
            const layerSpeed = 0.5 + layer * 0.3; // 不同层有不同速度

            for (let i = 0; i < particlesPerLayer; i++) {
                // 随机分配到四个边界
                const edge = Math.floor(Math.random() * 4); // 0=上, 1=右, 2=下, 3=左

                let x, y, vx, vy;

                switch(edge) {
                    case 0: // 上边界
                        x = Math.random() * this.width;
                        y = Math.random() * depth;
                        vx = (Math.random() - 0.5) * this.config.animationSpeed * layerSpeed;
                        vy = Math.random() * this.config.animationSpeed * 0.3 * layerSpeed;
                        break;
                    case 1: // 右边界
                        x = this.width - Math.random() * depth;
                        y = Math.random() * this.height;
                        vx = -Math.random() * this.config.animationSpeed * 0.3 * layerSpeed;
                        vy = (Math.random() - 0.5) * this.config.animationSpeed * layerSpeed;
                        break;
                    case 2: // 下边界
                        x = Math.random() * this.width;
                        y = this.height - Math.random() * depth;
                        vx = (Math.random() - 0.5) * this.config.animationSpeed * layerSpeed;
                        vy = -Math.random() * this.config.animationSpeed * 0.3 * layerSpeed;
                        break;
                    case 3: // 左边界
                        x = Math.random() * depth;
                        y = Math.random() * this.height;
                        vx = Math.random() * this.config.animationSpeed * 0.3 * layerSpeed;
                        vy = (Math.random() - 0.5) * this.config.animationSpeed * layerSpeed;
                        break;
                }

                particles.push({
                    x, y, vx, vy,
                    edge,
                    layer,
                    size: this.config.particleSize.min +
                          Math.random() * (this.config.particleSize.max - this.config.particleSize.min),
                    opacity: this.config.particleOpacity.min +
                            Math.random() * (this.config.particleOpacity.max - this.config.particleOpacity.min),
                    phase: Math.random() * Math.PI * 2,  // 用于湍流效果
                    rotationSpeed: (Math.random() - 0.5) * 0.02  // 旋转速度
                });
            }

            this.particleLayers.push(particles);
        }

        const totalParticles = this.particleLayers.reduce((sum, layer) => sum + layer.length, 0);
        console.log(`Created ${totalParticles} fog particles in ${this.config.particleLayers} layers`);
    }

    /**
     * 更新多层粒子位置（带湍流效果）
     */
    updateParticles() {
        const depth = this.config.fogDepth;

        // 更新噪声偏移（用于湍流）
        if (this.config.enableTurbulence) {
            this.noiseOffsetX += this.config.driftSpeed * 0.1;
            this.noiseOffsetY += this.config.driftSpeed * 0.05;
        }

        this.particleLayers.forEach((particles, layerIndex) => {
            particles.forEach(particle => {
                // 基础移动
                let dx = particle.vx;
                let dy = particle.vy;

                // 添加湍流效果（使用简化的噪声函数）
                if (this.config.enableTurbulence) {
                    const turbulence = this.simplexNoise(
                        particle.x * this.config.turbulenceScale + this.noiseOffsetX,
                        particle.y * this.config.turbulenceScale + this.noiseOffsetY,
                        this.time * 0.001
                    );
                    dx += turbulence.x * 0.5;
                    dy += turbulence.y * 0.5;
                }

                // 更新位置
                particle.x += dx;
                particle.y += dy;

                // 更新相位和旋转
                particle.phase += 0.01;

                // 边界检查和重置
                switch(particle.edge) {
                    case 0: // 上边界
                        if (particle.y > depth || particle.x < -50 || particle.x > this.width + 50) {
                            particle.x = Math.random() * this.width;
                            particle.y = -particle.size;
                        }
                        break;
                    case 1: // 右边界
                        if (particle.x < this.width - depth || particle.y < -50 || particle.y > this.height + 50) {
                            particle.x = this.width + particle.size;
                            particle.y = Math.random() * this.height;
                        }
                        break;
                    case 2: // 下边界
                        if (particle.y < this.height - depth || particle.x < -50 || particle.x > this.width + 50) {
                            particle.x = Math.random() * this.width;
                            particle.y = this.height + particle.size;
                        }
                        break;
                    case 3: // 左边界
                        if (particle.x > depth || particle.y < -50 || particle.y > this.height + 50) {
                            particle.x = -particle.size;
                            particle.y = Math.random() * this.height;
                        }
                        break;
                }
            });
        });
    }

    /**
     * 简化的噪声函数（用于湍流效果）
     */
    simplexNoise(x, y, z) {
        // 使用简化的伪随机噪声
        const n = Math.sin(x * 12.9898 + y * 78.233 + z * 37.719) * 43758.5453;
        const nx = Math.sin((x + 1) * 12.9898 + y * 78.233 + z * 37.719) * 43758.5453;
        const ny = Math.sin(x * 12.9898 + (y + 1) * 78.233 + z * 37.719) * 43758.5453;

        return {
            x: (nx - n) * 2 - 1,
            y: (ny - n) * 2 - 1
        };
    }

    /**
     * 绘制多层渐变迷雾边界（RTS 风格 - 边缘黑雾）
     */
    drawFogGradients() {
        if (!this.config.enableLayeredFog) return;

        const depth = this.config.fogDepth;
        const color = this.config.fogColor;

        // 绘制多层迷雾，从外到内逐渐变淡
        for (let layer = 0; layer < this.config.layerCount; layer++) {
            const layerDepth = depth * (1 - layer * 0.2); // 每层深度递减
            const layerOpacity = this.config.layerOpacities[layer] || 0.3;
            const opacityHex = Math.floor(layerOpacity * 255).toString(16).padStart(2, '0');
            const midOpacityHex = Math.floor(layerOpacity * 0.5 * 255).toString(16).padStart(2, '0');

            // 添加轻微的层间偏移（营造深度感）
            const offset = Math.sin(this.time * 0.001 + layer * Math.PI / 3) * 3;

            // 顶部迷雾 - 从边缘黑色渐变到透明
            const topGradient = this.ctx.createLinearGradient(0, 0, 0, layerDepth);
            topGradient.addColorStop(0, `${color}${opacityHex}`);  // 边缘浓密
            topGradient.addColorStop(0.5, `${color}${midOpacityHex}`);  // 中间过渡
            topGradient.addColorStop(1, `${color}00`);  // 内侧透明
            this.ctx.fillStyle = topGradient;
            this.ctx.fillRect(0, offset, this.width, layerDepth);

            // 底部迷雾
            const bottomGradient = this.ctx.createLinearGradient(0, this.height - layerDepth, 0, this.height);
            bottomGradient.addColorStop(0, `${color}00`);
            bottomGradient.addColorStop(0.5, `${color}${midOpacityHex}`);
            bottomGradient.addColorStop(1, `${color}${opacityHex}`);
            this.ctx.fillStyle = bottomGradient;
            this.ctx.fillRect(0, this.height - layerDepth - offset, this.width, layerDepth);

            // 左侧迷雾
            const leftGradient = this.ctx.createLinearGradient(0, 0, layerDepth, 0);
            leftGradient.addColorStop(0, `${color}${opacityHex}`);
            leftGradient.addColorStop(0.5, `${color}${midOpacityHex}`);
            leftGradient.addColorStop(1, `${color}00`);
            this.ctx.fillStyle = leftGradient;
            this.ctx.fillRect(offset, 0, layerDepth, this.height);

            // 右侧迷雾
            const rightGradient = this.ctx.createLinearGradient(this.width - layerDepth, 0, this.width, 0);
            rightGradient.addColorStop(0, `${color}00`);
            rightGradient.addColorStop(0.5, `${color}${midOpacityHex}`);
            rightGradient.addColorStop(1, `${color}${opacityHex}`);
            this.ctx.fillStyle = rightGradient;
            this.ctx.fillRect(this.width - layerDepth - offset, 0, layerDepth, this.height);
        }
    }

    /**
     * 绘制多层迷雾粒子（RTS 风格 - 边缘黑雾）
     */
    drawParticles() {
        // 从后向前绘制各层粒子（营造深度感）
        for (let layerIndex = this.particleLayers.length - 1; layerIndex >= 0; layerIndex--) {
            const particles = this.particleLayers[layerIndex];
            const layerDepth = layerIndex / this.particleLayers.length; // 0-1，越小越靠前

            particles.forEach(particle => {
                try {
                    // 确保坐标和大小有效
                    const x = particle.x;
                    const y = particle.y;
                    const size = Math.max(0.1, particle.size);

                    // 检查坐标是否有效
                    if (!isFinite(x) || !isFinite(y) || !isFinite(size)) {
                        return;
                    }

                    // 根据层级调整不透明度（后层更淡）
                    const layerOpacityMultiplier = 0.7 + layerDepth * 0.3;
                    const finalOpacity = particle.opacity * layerOpacityMultiplier;

                    // 使用纯黑色（战争迷雾）
                    const fogColor = this.config.fogColor;
                    const r = parseInt(fogColor.slice(1, 3), 16);
                    const g = parseInt(fogColor.slice(3, 5), 16);
                    const b = parseInt(fogColor.slice(5, 7), 16);

                    // 创建径向渐变（中心稍亮，边缘纯黑）
                    const gradient = this.ctx.createRadialGradient(
                        x, y, 0,
                        x, y, size
                    );

                    // 黑色迷雾渐变
                    gradient.addColorStop(0, `rgba(${r + 10}, ${g + 10}, ${b + 10}, ${finalOpacity * 0.9})`);
                    gradient.addColorStop(0.5, `rgba(${r + 5}, ${g + 5}, ${b + 5}, ${finalOpacity * 0.7})`);
                    gradient.addColorStop(0.8, `rgba(${r}, ${g}, ${b}, ${finalOpacity * 0.4})`);
                    gradient.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`);

                    this.ctx.fillStyle = gradient;
                    this.ctx.beginPath();
                    this.ctx.arc(x, y, size, 0, Math.PI * 2);
                    this.ctx.fill();

                } catch (error) {
                    console.error('Error drawing particle:', error, particle);
                }
            });
        }
    }

    /**
     * 渲染一帧
     */
    render() {
        // 如果尺寸为0，跳过渲染
        if (!this.width || !this.height || this.width === 0 || this.height === 0) {
            return;
        }

        // 清空画布
        this.ctx.clearRect(0, 0, this.width, this.height);

        // 绘制渐变迷雾
        this.drawFogGradients();

        // 绘制粒子
        if (this.config.enableParticles) {
            this.updateParticles();
            this.drawParticles();
        }

        // 更新时间
        this.time++;
    }

    /**
     * 开始动画循环
     */
    startAnimation() {
        const animate = () => {
            this.render();
            this.animationFrame = requestAnimationFrame(animate);
        };
        animate();
    }

    /**
     * 停止动画
     */
    stopAnimation() {
        if (this.animationFrame) {
            cancelAnimationFrame(this.animationFrame);
            this.animationFrame = null;
        }
    }

    /**
     * 更新配置
     */
    updateConfig(newConfig) {
        this.config = { ...this.config, ...newConfig };
        
        // 如果粒子数量改变，重新创建粒子
        if (newConfig.particleCount !== undefined) {
            this.createParticles();
        }
    }

    /**
     * 销毁
     */
    destroy() {
        this.stopAnimation();
        window.removeEventListener('resize', () => this.resizeCanvas());
        this.ctx.clearRect(0, 0, this.width, this.height);
    }
}

// 创建全局实例
let fogCanvasManager = null;

// 全局方法：重新调整 Canvas 尺寸
window.resizeFogCanvas = function() {
    if (fogCanvasManager) {
        fogCanvasManager.resizeCanvas();
        console.log('🌫️ Fog canvas manually resized');
    }
};

// DOM 加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    const canvas = document.getElementById('fog-canvas');
    if (canvas) {
        // RTS 风格战争迷雾配置 - 边缘浓密黑雾，中心清晰
        fogCanvasManager = new FogCanvasManager('fog-canvas', {
            // 基础配置
            fogDepth: 150,  // 迷雾深度（只在边缘）
            fogColor: '#000000',  // 纯黑色（战争迷雾）
            fogBaseOpacity: 0.95,  // 高不透明度（边缘完全遮挡）

            // 多层迷雾
            layerCount: 3,
            layerOpacities: [0.85, 0.6, 0.35],  // 从外到内逐渐变淡

            // 粒子系统
            particleCount: 200,  // 减少粒子数量
            particleLayers: 2,  // 减少层数
            particleSize: { min: 15, max: 50 },  // 更大的粒子
            particleOpacity: { min: 0.15, max: 0.35 },  // 适中的不透明度

            // 动画效果
            animationSpeed: 0.15,  // 更慢的移动
            turbulenceScale: 0.002,
            driftSpeed: 0.08,

            // 效果开关
            enableParticles: true,
            enableTurbulence: true,
            enableLayeredFog: true
        });

        console.log('🌫️ RTS-style war fog effect initialized');

        // 延迟重新调整尺寸，确保容器已显示
        setTimeout(() => {
            if (fogCanvasManager) {
                fogCanvasManager.resizeCanvas();
            }
        }, 500);
    }
});

