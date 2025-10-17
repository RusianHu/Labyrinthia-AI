// CameraFollowManager.js - 地图视角追踪管理器
// 实现玩家角色视角自动居中功能

class CameraFollowManager {
    constructor(mapContainerId, mapGridId) {
        this.mapContainerId = mapContainerId;
        this.mapGridId = mapGridId;
        this.mapContainer = document.getElementById(mapContainerId);
        this.mapGrid = document.getElementById(mapGridId);
        
        // 获取滚动容器
        this.scrollContainer = null;
        
        // 配置参数
        this.enabled = true;  // 是否启用视角追踪
        this.smoothScroll = true;  // 是否使用平滑滚动
        this.scrollDuration = 300;  // 平滑滚动持续时间（毫秒）
        this.edgeThreshold = 0.2;  // 边缘阈值（0-1），当玩家距离边缘小于此比例时才居中
        
        // 动画状态
        this.isAnimating = false;
        this.animationFrame = null;
        
        // 调试模式
        this.debugMode = false;
        
        this.init();
    }
    
    init() {
        if (!this.mapContainer || !this.mapGrid) {
            console.warn('[CameraFollowManager] Map container or grid not found');
            return;
        }
        
        // 获取滚动容器
        this.scrollContainer = this.mapContainer.querySelector('.dungeon-content');
        if (!this.scrollContainer) {
            console.warn('[CameraFollowManager] Scroll container (.dungeon-content) not found');
            return;
        }
        
        console.log('[CameraFollowManager] Initialized successfully');
    }
    
    /**
     * 重新初始化（当容器在构造后才可用时调用）
     */
    reinitialize() {
        this.mapContainer = document.getElementById(this.mapContainerId);
        this.mapGrid = document.getElementById(this.mapGridId);
        
        if (!this.mapContainer || !this.mapGrid) {
            console.warn('[CameraFollowManager] Reinitialize failed - containers not available');
            return false;
        }
        
        this.scrollContainer = this.mapContainer.querySelector('.dungeon-content');
        if (!this.scrollContainer) {
            console.warn('[CameraFollowManager] Reinitialize failed - scroll container not available');
            return false;
        }
        
        console.log('[CameraFollowManager] Reinitialized successfully');
        return true;
    }
    
    /**
     * 获取当前缩放级别（从 MapZoomManager）
     */
    getCurrentScale() {
        // 尝试从 MapZoomManager 获取缩放级别
        if (window.game && window.game.mapZoomManager) {
            return window.game.mapZoomManager.scale || 1;
        }
        
        // 备用方案：从 transform 样式中解析
        if (this.mapGrid) {
            const transform = this.mapGrid.style.transform;
            const match = transform.match(/scale\(([\d.]+)\)/);
            if (match) {
                return parseFloat(match[1]);
            }
        }
        
        return 1;
    }
    
    /**
     * 获取滚动内边距（从 MapZoomManager）
     */
    getScrollPadding() {
        if (window.game && window.game.mapZoomManager && 
            typeof window.game.mapZoomManager.getScrollPadding === 'function') {
            return window.game.mapZoomManager.getScrollPadding();
        }
        
        return { top: 0, right: 0, bottom: 0, left: 0 };
    }
    
    /**
     * 获取瓦片大小
     */
    getTileSize() {
        const tempTile = document.createElement('div');
        tempTile.className = 'map-tile';
        tempTile.style.visibility = 'hidden';
        document.body.appendChild(tempTile);
        const size = tempTile.offsetWidth;
        document.body.removeChild(tempTile);
        return size > 0 ? size : 24; // 提供回退值
    }
    
    /**
     * 计算玩家在视口中的像素位置
     * @param {number} playerX - 玩家X坐标（瓦片坐标）
     * @param {number} playerY - 玩家Y坐标（瓦片坐标）
     * @returns {Object} { pixelX, pixelY } - 玩家在地图中的像素位置
     */
    calculatePlayerPixelPosition(playerX, playerY) {
        const tileSize = this.getTileSize();
        const scale = this.getCurrentScale();
        
        // 玩家在地图中的像素位置（未缩放）
        const pixelX = (playerX + 0.5) * tileSize;  // +0.5 使其居中到瓦片中心
        const pixelY = (playerY + 0.5) * tileSize;
        
        return { pixelX, pixelY };
    }
    
    /**
     * 计算目标滚动位置以使玩家居中
     * @param {number} playerX - 玩家X坐标（瓦片坐标）
     * @param {number} playerY - 玩家Y坐标（瓦片坐标）
     * @returns {Object} { scrollLeft, scrollTop } - 目标滚动位置
     */
    calculateCenterScrollPosition(playerX, playerY) {
        if (!this.scrollContainer) {
            console.warn('[CameraFollowManager] Scroll container not available');
            return null;
        }
        
        const { pixelX, pixelY } = this.calculatePlayerPixelPosition(playerX, playerY);
        const scale = this.getCurrentScale();
        const padding = this.getScrollPadding();
        
        // 视口尺寸
        const viewportWidth = this.scrollContainer.clientWidth;
        const viewportHeight = this.scrollContainer.clientHeight;
        
        // 计算目标滚动位置（使玩家居中）
        const targetScrollLeft = padding.left + pixelX * scale - viewportWidth / 2;
        const targetScrollTop = padding.top + pixelY * scale - viewportHeight / 2;
        
        // 边界限制
        const maxScrollLeft = this.scrollContainer.scrollWidth - viewportWidth;
        const maxScrollTop = this.scrollContainer.scrollHeight - viewportHeight;
        
        const clampedScrollLeft = Math.max(0, Math.min(targetScrollLeft, maxScrollLeft));
        const clampedScrollTop = Math.max(0, Math.min(targetScrollTop, maxScrollTop));
        
        if (this.debugMode) {
            console.log('[CameraFollowManager] Calculate center position:', {
                playerPos: [playerX, playerY],
                pixelPos: [pixelX, pixelY],
                scale: scale,
                padding: padding,
                viewport: [viewportWidth, viewportHeight],
                target: [targetScrollLeft, targetScrollTop],
                clamped: [clampedScrollLeft, clampedScrollTop]
            });
        }
        
        return {
            scrollLeft: clampedScrollLeft,
            scrollTop: clampedScrollTop
        };
    }
    
    /**
     * 检查玩家是否需要居中（是否靠近边缘）
     * @param {number} playerX - 玩家X坐标
     * @param {number} playerY - 玩家Y坐标
     * @returns {boolean} 是否需要居中
     */
    shouldCenterPlayer(playerX, playerY) {
        if (!this.scrollContainer) return false;
        
        const { pixelX, pixelY } = this.calculatePlayerPixelPosition(playerX, playerY);
        const scale = this.getCurrentScale();
        const padding = this.getScrollPadding();
        
        // 玩家在视口中的位置
        const playerViewportX = padding.left + pixelX * scale - this.scrollContainer.scrollLeft;
        const playerViewportY = padding.top + pixelY * scale - this.scrollContainer.scrollTop;
        
        const viewportWidth = this.scrollContainer.clientWidth;
        const viewportHeight = this.scrollContainer.clientHeight;
        
        // 计算玩家距离边缘的比例
        const leftRatio = playerViewportX / viewportWidth;
        const rightRatio = (viewportWidth - playerViewportX) / viewportWidth;
        const topRatio = playerViewportY / viewportHeight;
        const bottomRatio = (viewportHeight - playerViewportY) / viewportHeight;
        
        // 如果玩家距离任何边缘小于阈值，则需要居中
        const needsCenter = leftRatio < this.edgeThreshold || 
                           rightRatio < this.edgeThreshold ||
                           topRatio < this.edgeThreshold || 
                           bottomRatio < this.edgeThreshold;
        
        if (this.debugMode && needsCenter) {
            console.log('[CameraFollowManager] Player near edge, needs centering:', {
                ratios: { left: leftRatio, right: rightRatio, top: topRatio, bottom: bottomRatio },
                threshold: this.edgeThreshold
            });
        }
        
        return needsCenter;
    }
    
    /**
     * 平滑滚动到目标位置
     * @param {number} targetScrollLeft - 目标水平滚动位置
     * @param {number} targetScrollTop - 目标垂直滚动位置
     * @param {boolean} immediate - 是否立即跳转（不使用动画）
     */
    smoothScrollTo(targetScrollLeft, targetScrollTop, immediate = false) {
        if (!this.scrollContainer) {
            console.warn('[CameraFollowManager] Scroll container not available');
            return;
        }
        
        // 取消之前的动画
        if (this.animationFrame) {
            cancelAnimationFrame(this.animationFrame);
            this.animationFrame = null;
        }
        
        // 如果禁用平滑滚动或要求立即跳转，直接设置位置
        if (!this.smoothScroll || immediate) {
            this.scrollContainer.scrollLeft = targetScrollLeft;
            this.scrollContainer.scrollTop = targetScrollTop;
            this.isAnimating = false;
            
            if (this.debugMode) {
                console.log('[CameraFollowManager] Immediate scroll to:', [targetScrollLeft, targetScrollTop]);
            }
            return;
        }
        
        // 使用 requestAnimationFrame 实现平滑滚动
        const startScrollLeft = this.scrollContainer.scrollLeft;
        const startScrollTop = this.scrollContainer.scrollTop;
        const deltaLeft = targetScrollLeft - startScrollLeft;
        const deltaTop = targetScrollTop - startScrollTop;
        const startTime = performance.now();
        
        this.isAnimating = true;
        
        const animate = (currentTime) => {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / this.scrollDuration, 1);
            
            // 使用 easeOutCubic 缓动函数
            const eased = 1 - Math.pow(1 - progress, 3);
            
            this.scrollContainer.scrollLeft = startScrollLeft + deltaLeft * eased;
            this.scrollContainer.scrollTop = startScrollTop + deltaTop * eased;
            
            if (progress < 1) {
                this.animationFrame = requestAnimationFrame(animate);
            } else {
                this.isAnimating = false;
                this.animationFrame = null;
                
                if (this.debugMode) {
                    console.log('[CameraFollowManager] Smooth scroll completed');
                }
            }
        };
        
        this.animationFrame = requestAnimationFrame(animate);
        
        if (this.debugMode) {
            console.log('[CameraFollowManager] Starting smooth scroll:', {
                from: [startScrollLeft, startScrollTop],
                to: [targetScrollLeft, targetScrollTop],
                duration: this.scrollDuration
            });
        }
    }
    
    /**
     * 将视角居中到玩家位置
     * @param {number} playerX - 玩家X坐标
     * @param {number} playerY - 玩家Y坐标
     * @param {boolean} immediate - 是否立即跳转（不使用动画）
     * @param {boolean} force - 是否强制居中（忽略边缘检查）
     */
    centerOnPlayer(playerX, playerY, immediate = false, force = false) {
        if (!this.enabled) {
            if (this.debugMode) {
                console.log('[CameraFollowManager] Camera follow is disabled');
            }
            return;
        }
        
        if (!this.scrollContainer) {
            console.warn('[CameraFollowManager] Scroll container not available');
            return;
        }
        
        // 检查是否需要居中（除非强制）
        if (!force && !this.shouldCenterPlayer(playerX, playerY)) {
            if (this.debugMode) {
                console.log('[CameraFollowManager] Player not near edge, skipping center');
            }
            return;
        }
        
        // 计算目标滚动位置
        const targetPos = this.calculateCenterScrollPosition(playerX, playerY);
        if (!targetPos) return;
        
        // 执行滚动
        this.smoothScrollTo(targetPos.scrollLeft, targetPos.scrollTop, immediate);
    }
    
    /**
     * 启用/禁用视角追踪
     */
    setEnabled(enabled) {
        this.enabled = enabled;
        console.log('[CameraFollowManager] Camera follow', enabled ? 'enabled' : 'disabled');
    }
    
    /**
     * 设置调试模式
     */
    setDebugMode(enabled) {
        this.debugMode = enabled;
        console.log('[CameraFollowManager] Debug mode', enabled ? 'enabled' : 'disabled');
    }
    
    /**
     * 销毁管理器
     */
    destroy() {
        if (this.animationFrame) {
            cancelAnimationFrame(this.animationFrame);
            this.animationFrame = null;
        }
        this.isAnimating = false;
        console.log('[CameraFollowManager] Destroyed');
    }
}

// 导出到全局作用域
window.CameraFollowManager = CameraFollowManager;

