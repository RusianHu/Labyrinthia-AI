// MapZoomManager.js - 地图缩放管理器
// 处理地图容器的缩放功能（滚轮和触摸手势）

class MapZoomManager {
    constructor(mapContainerId, mapGridId) {
        this.mapContainerId = mapContainerId;
        this.mapGridId = mapGridId;
        this.mapContainer = document.getElementById(mapContainerId);
        this.mapGrid = document.getElementById(mapGridId);

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

        // 设置初始样式
        this.mapGrid.style.transformOrigin = 'top left';
        this.mapGrid.style.transition = 'transform 0.1s ease-out';

        // 绑定事件
        this.bindEvents();

        console.log('MapZoomManager: 事件已绑定');
    }
    
    bindEvents() {
        // 绑定方法到this上下文
        this._handleWheel = this.handleWheel.bind(this);
        this._handleTouchStart = this.handleTouchStart.bind(this);
        this._handleTouchMove = this.handleTouchMove.bind(this);
        this._handleTouchEnd = this.handleTouchEnd.bind(this);
        this._handleMouseDown = this.handleMouseDown.bind(this);
        this._handleMouseMove = this.handleMouseMove.bind(this);
        this._handleMouseUp = this.handleMouseUp.bind(this);

        // 鼠标滚轮缩放
        this.mapContainer.addEventListener('wheel', this._handleWheel, { passive: false });

        // 触摸手势缩放
        this.mapContainer.addEventListener('touchstart', this._handleTouchStart, { passive: false });
        this.mapContainer.addEventListener('touchmove', this._handleTouchMove, { passive: false });
        this.mapContainer.addEventListener('touchend', this._handleTouchEnd, { passive: false });

        // 鼠标拖拽平移（可选功能，按住Ctrl键拖拽）
        this.mapContainer.addEventListener('mousedown', this._handleMouseDown);
        this.mapContainer.addEventListener('mousemove', this._handleMouseMove);
        this.mapContainer.addEventListener('mouseup', this._handleMouseUp);
        this.mapContainer.addEventListener('mouseleave', this._handleMouseUp);
    }
    
    handleWheel(e) {
        e.preventDefault();
        
        // 获取鼠标在容器中的位置
        const rect = this.mapContainer.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        
        // 计算缩放方向
        const delta = e.deltaY > 0 ? -this.scaleStep : this.scaleStep;
        const newScale = Math.max(this.minScale, Math.min(this.maxScale, this.scale + delta));
        
        if (newScale !== this.scale) {
            // 计算缩放前后的偏移量，使缩放以鼠标位置为中心
            const scaleRatio = newScale / this.scale;
            
            // 更新滚动位置以保持鼠标位置不变
            const scrollX = this.mapContainer.scrollLeft;
            const scrollY = this.mapContainer.scrollTop;
            
            this.scale = newScale;
            this.applyScale();
            
            // 调整滚动位置
            this.mapContainer.scrollLeft = scrollX * scaleRatio + (x * (scaleRatio - 1));
            this.mapContainer.scrollTop = scrollY * scaleRatio + (y * (scaleRatio - 1));
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
            this.scrollLeft = this.mapContainer.scrollLeft;
            this.scrollTop = this.mapContainer.scrollTop;

            // 直接进入拖动模式
            this.isPanning = true;
            this.mapContainer.style.cursor = 'grabbing';
        }
    }
    
    handleTouchMove(e) {
        if (e.touches.length === 2 && this.isTouchZooming) {
            // 双指缩放
            e.preventDefault();

            const touch1 = e.touches[0];
            const touch2 = e.touches[1];

            const currentDistance = this.getDistance(touch1, touch2);
            const scaleChange = currentDistance / this.initialDistance;

            const newScale = Math.max(
                this.minScale,
                Math.min(this.maxScale, this.initialScale * scaleChange)
            );

            if (newScale !== this.scale) {
                this.scale = newScale;
                this.applyScale();
            }
        } else if (e.touches.length === 1 && this.isPanning) {
            // 单指拖动
            e.preventDefault();
            const touch = e.touches[0];
            const x = touch.pageX;
            const y = touch.pageY;
            const walkX = this.startX - x;
            const walkY = this.startY - y;

            this.mapContainer.scrollLeft = this.scrollLeft + walkX;
            this.mapContainer.scrollTop = this.scrollTop + walkY;
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
            this.mapContainer.style.cursor = '';
        }
    }
    
    handleMouseDown(e) {
        // 只处理左键
        if (e.button !== 0) return;

        this.hasMoved = false;
        this.startX = e.pageX;
        this.startY = e.pageY;
        this.scrollLeft = this.mapContainer.scrollLeft;
        this.scrollTop = this.mapContainer.scrollTop;

        // 直接进入拖动模式
        this.isPanning = true;
        this.mapContainer.style.cursor = 'grabbing';
    }
    
    handleMouseMove(e) {
        // 如果正在拖动模式
        if (this.isPanning) {
            e.preventDefault();
            const x = e.pageX;
            const y = e.pageY;
            const walkX = this.startX - x;
            const walkY = this.startY - y;

            this.mapContainer.scrollLeft = this.scrollLeft + walkX;
            this.mapContainer.scrollTop = this.scrollTop + walkY;
        }
    }
    
    handleMouseUp() {
        this.isPanning = false;
        this.mapContainer.style.cursor = '';
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
        if (!this.mapContainer) return;
        this.scale = 1;
        this.applyScale();
        this.mapContainer.scrollLeft = 0;
        this.mapContainer.scrollTop = 0;
    }
    
    // 公共方法：设置缩放级别
    setZoom(scale) {
        this.scale = Math.max(this.minScale, Math.min(this.maxScale, scale));
        this.applyScale();
    }
    
    // 公共方法：获取当前缩放级别
    getZoom() {
        return this.scale;
    }
    
    // 公共方法：销毁管理器
    destroy() {
        // 移除所有事件监听器
        this.mapContainer.removeEventListener('wheel', this._handleWheel);
        this.mapContainer.removeEventListener('touchstart', this._handleTouchStart);
        this.mapContainer.removeEventListener('touchmove', this._handleTouchMove);
        this.mapContainer.removeEventListener('touchend', this._handleTouchEnd);
        this.mapContainer.removeEventListener('mousedown', this._handleMouseDown);
        this.mapContainer.removeEventListener('mousemove', this._handleMouseMove);
        this.mapContainer.removeEventListener('mouseup', this._handleMouseUp);
        this.mapContainer.removeEventListener('mouseleave', this._handleMouseUp);

        // 重置样式
        this.mapGrid.style.transform = '';
        this.mapGrid.style.transformOrigin = '';
        this.mapGrid.style.transition = '';
        this.mapContainer.style.cursor = '';
    }
}

// 导出到全局作用域
window.MapZoomManager = MapZoomManager;

