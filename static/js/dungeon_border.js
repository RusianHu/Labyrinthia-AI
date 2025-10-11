/**
 * 地牢边框效果管理器
 * 用于动态应用和管理地牢盒子风格的边框效果
 */

class DungeonBorderManager {
    constructor() {
        this.borderElements = new Map();
    }

    /**
     * 为指定元素应用完整的地牢边框效果
     * @param {string|HTMLElement} target - 目标元素或选择器
     * @param {Object} options - 配置选项
     * @returns {Object} 返回创建的边框元素引用
     */
    applyFullBorder(target, options = {}) {
        const element = typeof target === 'string' ? document.querySelector(target) : target;
        if (!element) {
            console.error('目标元素不存在:', target);
            return null;
        }

        // 默认配置
        const config = {
            showCorners: true,
            showEdges: true,
            addShadow: true,
            addGlow: false,
            addTexture: false,
            ...options
        };

        // 确保元素有正确的定位
        if (getComputedStyle(element).position === 'static') {
            element.style.position = 'relative';
        }

        // 添加基础样式类
        element.classList.add('dungeon-box-style');
        if (config.addShadow) {
            element.classList.add('dungeon-shadow-effect');
        }
        if (config.addGlow) {
            element.classList.add('dungeon-glow-edge');
        }

        const borderElements = {
            corners: [],
            edges: []
        };

        // 添加四角装饰
        if (config.showCorners) {
            const corners = ['top-left', 'top-right', 'bottom-left', 'bottom-right'];
            corners.forEach(position => {
                const corner = document.createElement('div');
                corner.className = `dungeon-corner ${position}`;
                element.appendChild(corner);
                borderElements.corners.push(corner);
            });
        }

        // 添加边框
        if (config.showEdges) {
            // 水平边框
            ['top', 'bottom'].forEach(position => {
                const edge = document.createElement('div');
                edge.className = `dungeon-border-horizontal ${position}`;
                element.appendChild(edge);
                borderElements.edges.push(edge);
            });

            // 垂直边框
            ['left', 'right'].forEach(position => {
                const edge = document.createElement('div');
                edge.className = `dungeon-border-vertical ${position}`;
                element.appendChild(edge);
                borderElements.edges.push(edge);
            });
        }

        // 添加纹理叠加
        if (config.addTexture) {
            const texture = document.createElement('div');
            texture.className = 'dungeon-texture-overlay';
            element.appendChild(texture);
            borderElements.texture = texture;
        }

        // 保存引用
        this.borderElements.set(element, borderElements);

        return borderElements;
    }

    /**
     * 移除元素的地牢边框效果
     * @param {string|HTMLElement} target - 目标元素或选择器
     */
    removeBorder(target) {
        const element = typeof target === 'string' ? document.querySelector(target) : target;
        if (!element) {
            console.error('目标元素不存在:', target);
            return;
        }

        const borderElements = this.borderElements.get(element);
        if (!borderElements) {
            console.warn('该元素没有应用边框效果');
            return;
        }

        // 移除所有边框元素
        [...borderElements.corners, ...borderElements.edges].forEach(el => {
            if (el && el.parentNode) {
                el.parentNode.removeChild(el);
            }
        });

        if (borderElements.texture && borderElements.texture.parentNode) {
            borderElements.texture.parentNode.removeChild(borderElements.texture);
        }

        // 移除样式类
        element.classList.remove('dungeon-box-style', 'dungeon-shadow-effect', 'dungeon-glow-edge');

        // 清除引用
        this.borderElements.delete(element);
    }

    /**
     * 应用简单边框效果
     * @param {string|HTMLElement} target - 目标元素或选择器
     */
    applySimpleBorder(target) {
        const element = typeof target === 'string' ? document.querySelector(target) : target;
        if (!element) {
            console.error('目标元素不存在:', target);
            return;
        }

        element.classList.add('dungeon-map-container');
    }

    /**
     * 切换发光效果
     * @param {string|HTMLElement} target - 目标元素或选择器
     * @param {boolean} enable - 是否启用
     */
    toggleGlow(target, enable = true) {
        const element = typeof target === 'string' ? document.querySelector(target) : target;
        if (!element) {
            console.error('目标元素不存在:', target);
            return;
        }

        if (enable) {
            element.classList.add('dungeon-glow-edge');
        } else {
            element.classList.remove('dungeon-glow-edge');
        }
    }

    /**
     * 切换阴影效果
     * @param {string|HTMLElement} target - 目标元素或选择器
     * @param {boolean} enable - 是否启用
     */
    toggleShadow(target, enable = true) {
        const element = typeof target === 'string' ? document.querySelector(target) : target;
        if (!element) {
            console.error('目标元素不存在:', target);
            return;
        }

        if (enable) {
            element.classList.add('dungeon-shadow-effect');
        } else {
            element.classList.remove('dungeon-shadow-effect');
        }
    }

    /**
     * 为地图容器应用边框（包装现有内容）
     * @param {string|HTMLElement} mapContainer - 地图容器元素或选择器
     * @param {Object} options - 配置选项
     */
    wrapMapWithBorder(mapContainer, options = {}) {
        const container = typeof mapContainer === 'string' ? 
            document.querySelector(mapContainer) : mapContainer;
        
        if (!container) {
            console.error('地图容器不存在:', mapContainer);
            return null;
        }

        // 创建包装器
        const wrapper = document.createElement('div');
        wrapper.className = 'dungeon-content';

        // 将容器的所有子元素移到包装器中
        while (container.firstChild) {
            wrapper.appendChild(container.firstChild);
        }

        // 将包装器添加回容器
        container.appendChild(wrapper);

        // 应用边框效果
        return this.applyFullBorder(container, options);
    }

    /**
     * 动态调整边框大小（响应式）
     * @param {string|HTMLElement} target - 目标元素或选择器
     */
    adjustBorderSize(target) {
        const element = typeof target === 'string' ? document.querySelector(target) : target;
        if (!element) {
            console.error('目标元素不存在:', target);
            return;
        }

        const borderElements = this.borderElements.get(element);
        if (!borderElements) {
            console.warn('该元素没有应用边框效果');
            return;
        }

        // 根据容器大小调整边框元素
        const rect = element.getBoundingClientRect();
        const isMobile = rect.width < 768;
        const isSmall = rect.width < 480;

        const cornerSize = isSmall ? 30 : (isMobile ? 50 : 80);
        const edgeSize = isSmall ? 20 : (isMobile ? 30 : 40);

        // 调整角落大小
        borderElements.corners.forEach(corner => {
            corner.style.width = `${cornerSize}px`;
            corner.style.height = `${cornerSize}px`;
        });

        // 调整边框大小
        borderElements.edges.forEach((edge, index) => {
            if (index < 2) { // 水平边框
                edge.style.height = `${edgeSize}px`;
                edge.style.left = `${cornerSize}px`;
                edge.style.right = `${cornerSize}px`;
            } else { // 垂直边框
                edge.style.width = `${edgeSize}px`;
                edge.style.top = `${cornerSize}px`;
                edge.style.bottom = `${cornerSize}px`;
            }
        });
    }

    /**
     * 初始化所有带有特定类名的元素
     * @param {string} selector - 选择器，默认为 '.auto-dungeon-border'
     */
    initializeAll(selector = '.auto-dungeon-border') {
        const elements = document.querySelectorAll(selector);
        elements.forEach(element => {
            const options = {
                showCorners: element.dataset.showCorners !== 'false',
                showEdges: element.dataset.showEdges !== 'false',
                addShadow: element.dataset.addShadow !== 'false',
                addGlow: element.dataset.addGlow === 'true',
                addTexture: element.dataset.addTexture === 'true'
            };
            this.applyFullBorder(element, options);
        });
    }

    /**
     * 清理所有边框效果
     */
    cleanup() {
        this.borderElements.forEach((_, element) => {
            this.removeBorder(element);
        });
        this.borderElements.clear();
    }
}

// 创建全局实例
const dungeonBorderManager = new DungeonBorderManager();

// 页面加载完成后自动初始化
if (typeof window !== 'undefined') {
    window.addEventListener('DOMContentLoaded', () => {
        dungeonBorderManager.initializeAll();
    });

    // 窗口大小改变时调整边框
    let resizeTimer;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            dungeonBorderManager.borderElements.forEach((_, element) => {
                dungeonBorderManager.adjustBorderSize(element);
            });
        }, 250);
    });
}

// 导出到全局作用域
if (typeof window !== 'undefined') {
    window.DungeonBorderManager = DungeonBorderManager;
    window.dungeonBorderManager = dungeonBorderManager;
}

