// MapZoomManager.js - 地图缩放管理器
// 处理地图容器的缩放功能（滚轮和触摸手势）

class MapZoomManager {
    constructor(mapContainerId, mapGridId) {
        this.mapContainerId = mapContainerId;
        this.mapGridId = mapGridId;
        this.mapContainer = document.getElementById(mapContainerId);
        this.mapGrid = document.getElementById(mapGridId);

        // 获取实际的滚动容器（.dungeon-content）
        this.scrollContainer = null;
        this.scrollPadding = {
            top: 0,
            right: 0,
            bottom: 0,
            left: 0
        };
        this.panBufferThreshold = 1.05;

        // 缩放配置
        this.scale = 1;
        this.minScale = 0.5;
        this.maxScale = 3;
        this.scaleStep = 0.1;

        // 触摸手势相关
        this.initialDistance = 0;
        this.initialScale = 1;
        this.touchStartTime = 0;
        this.isTouchZooming = false;

        // 平移相关
        this.isPanning = false;
        this.startX = 0;
        this.startY = 0;
        this.scrollLeft = 0;
        this.scrollTop = 0;
        this.hasMoved = false;

        // 事件处理器引用（用于移除事件监听器）
        this._handleWheel = null;
        this._handleTouchStart = null;
        this._handleTouchMove = null;
        this._handleTouchEnd = null;
        this._handleMouseDown = null;
        this._handleMouseMove = null;
        this._handleMouseUp = null;

        this.init();
    }

    init() {
        if (!this.mapContainer || !this.mapGrid) {
            console.warn('MapZoomManager: 地图容器或地图网格未找到，将在容器可用时重新初始化');
            // 不要返回，继续执行，以便后续可以重新初始化
            return;
        }

        // 获取实际的滚动容器
        this.scrollContainer = this.mapContainer.querySelector('.dungeon-content');
        if (!this.scrollContainer) {
            console.warn('MapZoomManager: 未找到 .dungeon-content 滚动容器');
            return;
        }

        // 缓存当前的内边距，供滚动偏移使用
        this.updateScrollPadding();
        this.updatePanPaddingForScale(this.scrollPadding, { overrideScroll: true });

        // 设置初始样式
        this.mapGrid.style.transformOrigin = 'top left';
        this.mapGrid.style.transition = 'transform 0.1s ease-out';

        // 绑定事件
        this.bindEvents();

        console.log('MapZoomManager: 事件已绑定，滚动容器:', this.scrollContainer);
    }
    
    bindEvents() {
        if (!this.scrollContainer) {
            console.warn('MapZoomManager: 无法绑定事件，滚动容器不存在');
            return;
        }

        // 绑定方法到this上下文
        this._handleWheel = this.handleWheel.bind(this);
        this._handleTouchStart = this.handleTouchStart.bind(this);
        this._handleTouchMove = this.handleTouchMove.bind(this);
        this._handleTouchEnd = this.handleTouchEnd.bind(this);
        this._handleMouseDown = this.handleMouseDown.bind(this);
        this._handleMouseMove = this.handleMouseMove.bind(this);
        this._handleMouseUp = this.handleMouseUp.bind(this);

        // 鼠标滚轮缩放 - 绑定到滚动容器
        this.scrollContainer.addEventListener('wheel', this._handleWheel, { passive: false });

        // 触摸手势缩放 - 绑定到滚动容器
        this.scrollContainer.addEventListener('touchstart', this._handleTouchStart, { passive: false });
        this.scrollContainer.addEventListener('touchmove', this._handleTouchMove, { passive: false });
        this.scrollContainer.addEventListener('touchend', this._handleTouchEnd, { passive: false });

        // 鼠标拖拽平移 - 绑定到滚动容器
        this.scrollContainer.addEventListener('mousedown', this._handleMouseDown);
        this.scrollContainer.addEventListener('mousemove', this._handleMouseMove);
        this.scrollContainer.addEventListener('mouseup', this._handleMouseUp);
        this.scrollContainer.addEventListener('mouseleave', this._handleMouseUp);
    }

    updateScrollPadding() {
        if (!this.scrollContainer) {
            this.scrollPadding = { top: 0, right: 0, bottom: 0, left: 0 };
            return this.scrollPadding;
        }

        const styles = window.getComputedStyle(this.scrollContainer);
        const parseValue = (value) => {
            const parsed = parseFloat(value);
            return Number.isNaN(parsed) ? 0 : parsed;
        };

        this.scrollPadding = {
            top: parseValue(styles.paddingTop),
            right: parseValue(styles.paddingRight),
            bottom: parseValue(styles.paddingBottom),
            left: parseValue(styles.paddingLeft)
        };

        return this.scrollPadding;
    }

    computePanBufferScale() {
        if (this.scale <= this.panBufferThreshold) {
            return 0;
        }

        const effectiveRange = this.maxScale - this.panBufferThreshold;
        if (effectiveRange <= 0) {
            return 1;
        }

        const ratio = (this.scale - this.panBufferThreshold) / effectiveRange;
        return Math.min(1, Math.max(0, ratio));
    }

    updatePanPaddingForScale(prevPadding = null, options = {}) {
        if (!this.scrollContainer) {
            if (prevPadding) {
                this.scrollPadding = { ...prevPadding };
                return this.scrollPadding;
            }
            return { top: 0, right: 0, bottom: 0, left: 0 };
        }

        const previousPadding = prevPadding ? { ...prevPadding } : { ...this.scrollPadding };
        const { overrideScroll = false } = options;

        const bufferScale = this.computePanBufferScale();
        this.scrollContainer.style.setProperty('--map-pan-scale', bufferScale.toFixed(4));

        const newPadding = this.updateScrollPadding();

        if (!overrideScroll) {
            const deltaLeft = newPadding.left - previousPadding.left;
            const deltaTop = newPadding.top - previousPadding.top;

            if (deltaLeft !== 0) {
                this.scrollContainer.scrollLeft += deltaLeft;
            }
            if (deltaTop !== 0) {
                this.scrollContainer.scrollTop += deltaTop;
            }
        }

        return newPadding;
    }

    getScrollPadding() {
        return { ...this.updateScrollPadding() };
    }
    
    handleWheel(e) {
        if (!this.scrollContainer) return;

        e.preventDefault();

        const rect = this.scrollContainer.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;

        const previousScale = this.scale;
        const delta = e.deltaY > 0 ? -this.scaleStep : this.scaleStep;
        const newScale = Math.max(this.minScale, Math.min(this.maxScale, previousScale + delta));

        if (newScale !== previousScale) {
            const scrollX = this.scrollContainer.scrollLeft;
            const scrollY = this.scrollContainer.scrollTop;
            const previousPadding = { ...this.scrollPadding };
            const scaleRatio = newScale / previousScale;

            this.scale = newScale;
            this.applyScale();

            const newPadding = this.updatePanPaddingForScale(previousPadding, { overrideScroll: true });

            const newScrollLeft = (scrollX + x - previousPadding.left) * scaleRatio + newPadding.left - x;
            const newScrollTop = (scrollY + y - previousPadding.top) * scaleRatio + newPadding.top - y;

            this.scrollContainer.scrollLeft = newScrollLeft;
            this.scrollContainer.scrollTop = newScrollTop;
        }
    }
    
    handleTouchStart(e) {
        if (e.touches.length === 2) {
            // 双指触摸开始 - 缩放模式
            e.preventDefault();
            this.isTouchZooming = true;

            const touch1 = e.touches[0];
            const touch2 = e.touches[1];

            this.initialDistance = this.getDistance(touch1, touch2);
            this.initialScale = this.scale;
        } else if (e.touches.length === 1) {
            // 单指触摸 - 直接进入拖动模式
            this.touchStartTime = Date.now();
            this.hasMoved = false;

            const touch = e.touches[0];
            this.startX = touch.pageX;
            this.startY = touch.pageY;
            this.scrollLeft = this.scrollContainer.scrollLeft;
            this.scrollTop = this.scrollContainer.scrollTop;

            // 直接进入拖动模式
            this.isPanning = true;
            this.scrollContainer.style.cursor = 'grabbing';
        }
    }
    
    handleTouchMove(e) {
        if (e.touches.length === 2 && this.isTouchZooming) {
            // 双指缩放
            e.preventDefault();

            const touch1 = e.touches[0];
            const touch2 = e.touches[1];

            const currentDistance = this.getDistance(touch1, touch2);
            if (currentDistance <= 0) {
                return;
            }

            const scaleChange = currentDistance / this.initialDistance;
            const previousScale = this.scale;
            const tentativeScale = this.initialScale * scaleChange;
            const newScale = Math.max(this.minScale, Math.min(this.maxScale, tentativeScale));

            if (newScale !== previousScale) {
                const rect = this.scrollContainer.getBoundingClientRect();
                const anchorX = ((touch1.clientX + touch2.clientX) / 2) - rect.left;
                const anchorY = ((touch1.clientY + touch2.clientY) / 2) - rect.top;

                const scrollX = this.scrollContainer.scrollLeft;
                const scrollY = this.scrollContainer.scrollTop;
                const previousPadding = { ...this.scrollPadding };
                const scaleRatio = newScale / previousScale;

                this.scale = newScale;
                this.applyScale();

                const newPadding = this.updatePanPaddingForScale(previousPadding, { overrideScroll: true });

                const newScrollLeft = (scrollX + anchorX - previousPadding.left) * scaleRatio + newPadding.left - anchorX;
                const newScrollTop = (scrollY + anchorY - previousPadding.top) * scaleRatio + newPadding.top - anchorY;

                this.scrollContainer.scrollLeft = newScrollLeft;
                this.scrollContainer.scrollTop = newScrollTop;
            }
        } else if (e.touches.length === 1 && this.isPanning) {
            // 单指拖动
            e.preventDefault();
            const touch = e.touches[0];
            const x = touch.pageX;
            const y = touch.pageY;
            const walkX = this.startX - x;
            const walkY = this.startY - y;

            this.scrollContainer.scrollLeft = this.scrollLeft + walkX;
            this.scrollContainer.scrollTop = this.scrollTop + walkY;
        }
    }
    
    handleTouchEnd(e) {
        if (e.touches.length < 2) {
            // 重置触摸状态
            this.initialDistance = 0;
            this.initialScale = this.scale;
            this.isTouchZooming = false;
        }

        if (e.touches.length === 0) {
            // 所有手指都离开了
            this.isPanning = false;
            this.scrollContainer.style.cursor = '';
        }
    }
    
    handleMouseDown(e) {
        // 只处理左键
        if (e.button !== 0) return;

        this.hasMoved = false;
        this.startX = e.pageX;
        this.startY = e.pageY;
        this.scrollLeft = this.scrollContainer.scrollLeft;
        this.scrollTop = this.scrollContainer.scrollTop;

        // 直接进入拖动模式
        this.isPanning = true;
        this.scrollContainer.style.cursor = 'grabbing';
    }

    handleMouseMove(e) {
        // 如果正在拖动模式
        if (this.isPanning) {
            e.preventDefault();
            const x = e.pageX;
            const y = e.pageY;
            const walkX = this.startX - x;
            const walkY = this.startY - y;

            this.scrollContainer.scrollLeft = this.scrollLeft + walkX;
            this.scrollContainer.scrollTop = this.scrollTop + walkY;
        }
    }

    handleMouseUp() {
        this.isPanning = false;
        this.scrollContainer.style.cursor = '';
    }
    
    getDistance(touch1, touch2) {
        const dx = touch1.clientX - touch2.clientX;
        const dy = touch1.clientY - touch2.clientY;
        return Math.sqrt(dx * dx + dy * dy);
    }
    
    applyScale() {
        this.mapGrid.style.transform = `scale(${this.scale})`;
        
        // 触发自定义事件，通知其他组件缩放已改变
        const event = new CustomEvent('mapZoomChanged', {
            detail: { scale: this.scale }
        });
        this.mapContainer.dispatchEvent(event);
    }
    
    // 公共方法：重新初始化（当容器在构造后才可用时调用）
    reinitialize() {
        // 重新获取容器引用
        this.mapContainer = document.getElementById(this.mapContainerId);
        this.mapGrid = document.getElementById(this.mapGridId);

        if (!this.mapContainer || !this.mapGrid) {
            console.warn('MapZoomManager: 重新初始化失败，容器仍然不可用');
            return false;
        }

        // 重新获取滚动容器
        this.scrollContainer = this.mapContainer.querySelector('.dungeon-content');
        if (!this.scrollContainer) {
            console.warn('MapZoomManager: 重新初始化失败，滚动容器不可用');
            return false;
        }

        // 先移除旧的事件监听器（如果有）
        if (this._handleWheel) {
            this.destroy();
        }

        // 重新初始化
        this.init();
        return true;
    }

    // 公共方法：重置缩放
    resetZoom() {
        if (!this.scrollContainer) return;
        const previousPadding = { ...this.scrollPadding };
        this.scale = 1;
        this.applyScale();
        const newPadding = this.updatePanPaddingForScale(previousPadding, { overrideScroll: true });
        this.scrollContainer.scrollLeft = newPadding.left;
        this.scrollContainer.scrollTop = newPadding.top;
    }
    
    // 公共方法：设置缩放级别
    setZoom(scale) {
        const clamped = Math.max(this.minScale, Math.min(this.maxScale, scale));
        if (!this.scrollContainer) {
            this.scale = clamped;
            this.applyScale();
            return;
        }

        const previousScale = this.scale || 1;
        const previousPadding = { ...this.scrollPadding };

        this.scale = clamped;
        this.applyScale();

        const newPadding = this.updatePanPaddingForScale(previousPadding, { overrideScroll: true });

        if (clamped !== previousScale) {
            const ratio = clamped / previousScale;
            if (Number.isFinite(ratio) && ratio > 0) {
                const scrollX = this.scrollContainer.scrollLeft;
                const scrollY = this.scrollContainer.scrollTop;
                const anchorX = this.scrollContainer.clientWidth / 2;
                const anchorY = this.scrollContainer.clientHeight / 2;

                const newScrollLeft = (scrollX + anchorX - previousPadding.left) * ratio + newPadding.left - anchorX;
                const newScrollTop = (scrollY + anchorY - previousPadding.top) * ratio + newPadding.top - anchorY;

                this.scrollContainer.scrollLeft = newScrollLeft;
                this.scrollContainer.scrollTop = newScrollTop;
            }
        } else {
            const deltaLeft = newPadding.left - previousPadding.left;
            const deltaTop = newPadding.top - previousPadding.top;

            if (deltaLeft !== 0) {
                this.scrollContainer.scrollLeft += deltaLeft;
            }
            if (deltaTop !== 0) {
                this.scrollContainer.scrollTop += deltaTop;
            }
        }
    }
    
    // 公共方法：获取当前缩放级别
    getZoom() {
        return this.scale;
    }
    
    // 公共方法：销毁管理器
    destroy() {
        if (!this.scrollContainer) return;

        // 移除所有事件监听器
        this.scrollContainer.removeEventListener('wheel', this._handleWheel);
        this.scrollContainer.removeEventListener('touchstart', this._handleTouchStart);
        this.scrollContainer.removeEventListener('touchmove', this._handleTouchMove);
        this.scrollContainer.removeEventListener('touchend', this._handleTouchEnd);
        this.scrollContainer.removeEventListener('mousedown', this._handleMouseDown);
        this.scrollContainer.removeEventListener('mousemove', this._handleMouseMove);
        this.scrollContainer.removeEventListener('mouseup', this._handleMouseUp);
        this.scrollContainer.removeEventListener('mouseleave', this._handleMouseUp);

        // 重置样式
        if (this.mapGrid) {
            this.mapGrid.style.transform = '';
            this.mapGrid.style.transformOrigin = '';
            this.mapGrid.style.transition = '';
        }
        this.scrollContainer.style.cursor = '';
        this.scrollContainer.style.removeProperty('--map-pan-scale');
        this.scrollPadding = { top: 0, right: 0, bottom: 0, left: 0 };
    }
}

// 导出到全局作用域
window.MapZoomManager = MapZoomManager;
