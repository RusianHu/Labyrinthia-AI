/**
 * 地板图层管理器
 * 用于动态管理和控制地牢地板的视觉效果
 */

class FloorLayerManager {
    constructor() {
        this.layers = new Map();
        this.presets = {
            // 地下城系列主题
            normal: {
                base: 'floor-stone-basic',
                overlay: 'floor-overlay-cracks',
                baseOpacity: 0.8,
                overlayOpacity: 0.4
            },
            magic: {
                base: 'floor-marble-ancient',
                overlay: 'floor-overlay-magic',
                baseOpacity: 0.85,
                overlayOpacity: 0.5
            },
            abandoned: {
                base: 'floor-wood-planks',
                overlay: 'floor-overlay-moss',
                baseOpacity: 0.75,
                overlayOpacity: 0.5
            },
            cave: {
                base: 'floor-dirt-cave',
                overlay: 'floor-overlay-water',
                baseOpacity: 0.7,
                overlayOpacity: 0.4
            },
            combat: {
                base: 'floor-stone-basic',
                overlay: 'floor-overlay-blood',
                baseOpacity: 0.8,
                overlayOpacity: 0.6
            },
            // 地上自然系列主题
            grassland: {
                base: 'floor-grass-field',
                overlay: 'floor-overlay-flowers',
                baseOpacity: 0.85,
                overlayOpacity: 0.6
            },
            desert: {
                base: 'floor-sand-desert',
                overlay: 'floor-overlay-footprints',
                baseOpacity: 0.8,
                overlayOpacity: 0.4
            },
            farmland: {
                base: 'floor-farmland-soil',
                overlay: 'floor-overlay-crops',
                baseOpacity: 0.8,
                overlayOpacity: 0.7
            },
            snowfield: {
                base: 'floor-snow-field',
                overlay: 'floor-overlay-ice',
                baseOpacity: 0.9,
                overlayOpacity: 0.5
            },
            town: {
                base: 'floor-cobblestone-street',
                overlay: 'floor-overlay-cracks',
                baseOpacity: 0.85,
                overlayOpacity: 0.3
            }
        };
    }

    /**
     * 为容器添加地板图层
     * @param {string|HTMLElement} container - 容器元素或选择器
     * @param {Object} options - 配置选项
     * @returns {Object} 创建的图层元素
     */
    addFloorLayers(container, options = {}) {
        const element = typeof container === 'string' ? 
            document.querySelector(container) : container;
        
        if (!element) {
            console.error('容器元素不存在:', container);
            return null;
        }

        // 默认配置（支持 base 别名传入）
        const normalized = { ...options };
        if (!('baseFloor' in normalized) && ('base' in normalized)) {
            normalized.baseFloor = normalized.base;
        }

        const config = {
            baseFloor: 'floor-stone-basic',
            overlay: null,
            baseOpacity: 0.8,
            overlayOpacity: 0.5,
            tileSize: 64,
            overlayTileSize: 128,
            zIndexBase: 0,
            zIndexOverlay: 1,
            ...normalized
        };

        // 确保容器有正确的定位
        if (getComputedStyle(element).position === 'static') {
            element.style.position = 'relative';
        }

        const layers = {
            base: null,
            overlay: null
        };

        // 创建基础地板层
        if (config.baseFloor) {
            const baseLayer = document.createElement('div');
            baseLayer.className = `floor-layer ${config.baseFloor}`;
            baseLayer.style.opacity = config.baseOpacity;
            baseLayer.style.backgroundSize = `${config.tileSize}px ${config.tileSize}px`;
            baseLayer.style.zIndex = config.zIndexBase;
            element.insertBefore(baseLayer, element.firstChild);
            layers.base = baseLayer;
        }

        // 创建叠加层
        if (config.overlay) {
            const overlayLayer = document.createElement('div');
            overlayLayer.className = `floor-overlay ${config.overlay}`;
            overlayLayer.style.opacity = config.overlayOpacity;
            overlayLayer.style.backgroundSize = `${config.overlayTileSize}px ${config.overlayTileSize}px`;
            overlayLayer.style.zIndex = config.zIndexOverlay;
            element.insertBefore(overlayLayer, element.firstChild);
            layers.overlay = overlayLayer;
        }

        // 保存图层引用
        this.layers.set(element, layers);

        return layers;
    }

    /**
     * 应用预设场景
     * @param {string|HTMLElement} container - 容器元素或选择器
     * @param {string} presetName - 预设名称 (normal, magic, abandoned, cave, combat)
     */
    applyPreset(container, presetName) {
        const preset = this.presets[presetName];
        if (!preset) {
            console.error('预设不存在:', presetName);
            return null;
        }

        // 兼容旧预设键名（base -> baseFloor），仅在存在时映射，避免用 undefined 覆盖默认值
        const mappedOptions = {};
        if (Object.prototype.hasOwnProperty.call(preset, 'baseFloor') || Object.prototype.hasOwnProperty.call(preset, 'base')) {
            mappedOptions.baseFloor = preset.baseFloor || preset.base;
        }
        if (Object.prototype.hasOwnProperty.call(preset, 'overlay')) {
            mappedOptions.overlay = preset.overlay;
        }
        if (Object.prototype.hasOwnProperty.call(preset, 'baseOpacity')) {
            mappedOptions.baseOpacity = preset.baseOpacity;
        }
        if (Object.prototype.hasOwnProperty.call(preset, 'overlayOpacity')) {
            mappedOptions.overlayOpacity = preset.overlayOpacity;
        }

        return this.addFloorLayers(container, mappedOptions);
    }

    /**
     * 移除地板图层
     * @param {string|HTMLElement} container - 容器元素或选择器
     */
    removeFloorLayers(container) {
        const element = typeof container === 'string' ? 
            document.querySelector(container) : container;
        
        if (!element) {
            console.error('容器元素不存在:', container);
            return;
        }

        const layers = this.layers.get(element);
        if (!layers) {
            console.warn('该元素没有地板图层');
            return;
        }

        // 移除图层元素
        if (layers.base && layers.base.parentNode) {
            layers.base.parentNode.removeChild(layers.base);
        }
        if (layers.overlay && layers.overlay.parentNode) {
            layers.overlay.parentNode.removeChild(layers.overlay);
        }

        // 清除引用
        this.layers.delete(element);
    }

    /**
     * 更新基础地板
     * @param {string|HTMLElement} container - 容器元素或选择器
     * @param {string} floorClass - 地板类名
     * @param {number} opacity - 透明度 (0-1)
     */
    updateBaseFloor(container, floorClass, opacity = null) {
        const element = typeof container === 'string' ? 
            document.querySelector(container) : container;
        
        const layers = this.layers.get(element);
        if (!layers || !layers.base) {
            console.warn('基础地板层不存在');
            return;
        }

        // 移除旧的地板类
        layers.base.className = layers.base.className
            .split(' ')
            .filter(c => !c.startsWith('floor-') || c === 'floor-layer')
            .join(' ');

        // 添加新的地板类
        layers.base.classList.add(floorClass);

        // 更新透明度
        if (opacity !== null) {
            layers.base.style.opacity = opacity;
        }
    }

    /**
     * 更新叠加层
     * @param {string|HTMLElement} container - 容器元素或选择器
     * @param {string} overlayClass - 叠加层类名
     * @param {number} opacity - 透明度 (0-1)
     */
    updateOverlay(container, overlayClass, opacity = null) {
        const element = typeof container === 'string' ? 
            document.querySelector(container) : container;
        
        const layers = this.layers.get(element);
        if (!layers) {
            console.warn('图层不存在');
            return;
        }

        // 如果没有叠加层，创建一个
        if (!layers.overlay) {
            const overlayLayer = document.createElement('div');
            overlayLayer.className = 'floor-overlay';
            overlayLayer.style.zIndex = 1;
            element.insertBefore(overlayLayer, element.firstChild);
            layers.overlay = overlayLayer;
        }

        // 移除旧的叠加类
        layers.overlay.className = layers.overlay.className
            .split(' ')
            .filter(c => !c.startsWith('floor-overlay-') || c === 'floor-overlay')
            .join(' ');

        // 添加新的叠加类
        layers.overlay.classList.add(overlayClass);

        // 更新透明度
        if (opacity !== null) {
            layers.overlay.style.opacity = opacity;
        }
    }

    /**
     * 移除叠加层
     * @param {string|HTMLElement} container - 容器元素或选择器
     */
    removeOverlay(container) {
        const element = typeof container === 'string' ? 
            document.querySelector(container) : container;
        
        const layers = this.layers.get(element);
        if (!layers || !layers.overlay) {
            return;
        }

        if (layers.overlay.parentNode) {
            layers.overlay.parentNode.removeChild(layers.overlay);
        }
        layers.overlay = null;
    }

    /**
     * 调整瓦片大小
     * @param {string|HTMLElement} container - 容器元素或选择器
     * @param {number} baseSize - 基础层瓦片大小
     * @param {number} overlaySize - 叠加层瓦片大小
     */
    adjustTileSize(container, baseSize, overlaySize = null) {
        const element = typeof container === 'string' ? 
            document.querySelector(container) : container;
        
        const layers = this.layers.get(element);
        if (!layers) {
            console.warn('图层不存在');
            return;
        }

        if (layers.base && baseSize) {
            layers.base.style.backgroundSize = `${baseSize}px ${baseSize}px`;
        }

        if (layers.overlay && overlaySize) {
            layers.overlay.style.backgroundSize = `${overlaySize}px ${overlaySize}px`;
        }
    }

    /**
     * 淡入效果
     * @param {string|HTMLElement} container - 容器元素或选择器
     * @param {number} duration - 持续时间（毫秒）
     */
    fadeIn(container, duration = 1000) {
        const element = typeof container === 'string' ? 
            document.querySelector(container) : container;
        
        const layers = this.layers.get(element);
        if (!layers) {
            return;
        }

        const animate = (layer, targetOpacity) => {
            if (!layer) return;
            
            layer.style.opacity = 0;
            layer.style.transition = `opacity ${duration}ms ease-in-out`;
            
            setTimeout(() => {
                layer.style.opacity = targetOpacity;
            }, 10);
        };

        if (layers.base) {
            const baseOpacity = parseFloat(layers.base.dataset.targetOpacity || 0.8);
            animate(layers.base, baseOpacity);
        }

        if (layers.overlay) {
            const overlayOpacity = parseFloat(layers.overlay.dataset.targetOpacity || 0.5);
            animate(layers.overlay, overlayOpacity);
        }
    }

    /**
     * 淡出效果
     * @param {string|HTMLElement} container - 容器元素或选择器
     * @param {number} duration - 持续时间（毫秒）
     */
    fadeOut(container, duration = 1000) {
        const element = typeof container === 'string' ? 
            document.querySelector(container) : container;
        
        const layers = this.layers.get(element);
        if (!layers) {
            return;
        }

        const animate = (layer) => {
            if (!layer) return;
            
            layer.style.transition = `opacity ${duration}ms ease-in-out`;
            layer.style.opacity = 0;
        };

        if (layers.base) animate(layers.base);
        if (layers.overlay) animate(layers.overlay);
    }

    /**
     * 清理所有图层
     */
    cleanup() {
        this.layers.forEach((_, element) => {
            this.removeFloorLayers(element);
        });
        this.layers.clear();
    }
}

// 创建全局实例
const floorLayerManager = new FloorLayerManager();

// 导出到全局作用域
if (typeof window !== 'undefined') {
    window.FloorLayerManager = FloorLayerManager;
    window.floorLayerManager = floorLayerManager;
}

