// Labyrinthia AI - 地图视觉管理器
// 统一管理地图的所有视觉效果：地板图层、环境粒子等

/**
 * 地图视觉管理器类
 * 职责：协调和管理地图的所有视觉效果
 * - 地板图层（FloorLayerManager）
 * - 环境粒子特效（EnhancedEffectsManager）
 * - 未来可扩展：天气系统、动态光照、环境音效等
 */
class MapVisualManager {
    constructor(game) {
        this.game = game;
        
        // 引用其他管理器
        this.floorLayerManager = window.floorLayerManager;
        this.enhancedEffects = game.enhancedEffects;
        
        // 状态追踪
        this.currentTheme = null;  // 当前应用的主题
        this.lastMapSize = null;   // 上次地图尺寸 {width, height}
        
        // 支持的主题列表
        this.validThemes = [
            'normal', 'magic', 'abandoned', 'cave', 'combat',
            'grassland', 'desert', 'farmland', 'snowfield', 'town'
        ];
        
        console.log('[MapVisualManager] Initialized');
    }
    
    /**
     * 应用地图主题（统一入口）
     * 这是外部调用的主要接口，协调地板图层和粒子特效的应用
     * 
     * @param {string} theme - 主题名称
     * @param {boolean} isFullRebuild - 是否完全重建（地图尺寸变化或首次加载）
     * @returns {boolean} 是否成功应用主题
     */
    applyMapTheme(theme, isFullRebuild = false) {
        console.log('[MapVisualManager] applyMapTheme called:', {
            theme: theme,
            isFullRebuild: isFullRebuild,
            currentTheme: this.currentTheme
        });
        
        // 验证主题是否有效
        const validatedTheme = this._validateTheme(theme);
        
        // 获取地图容器
        const mapGrid = document.getElementById('map-grid');
        if (!mapGrid) {
            console.warn('[MapVisualManager] Map grid container not found');
            return false;
        }
        
        try {
            // 1. 应用地板图层
            this._applyFloorLayers(mapGrid, validatedTheme);
            
            // 2. 应用环境粒子特效
            this._applyEnvironmentParticles(mapGrid, validatedTheme, isFullRebuild);
            
            // 3. 更新状态
            this.currentTheme = validatedTheme;
            
            console.log('[MapVisualManager] Map theme applied successfully:', validatedTheme);
            return true;
            
        } catch (error) {
            console.error('[MapVisualManager] Failed to apply map theme:', error);
            return false;
        }
    }
    
    /**
     * 验证并规范化主题名称
     * @private
     * @param {string} theme - 原始主题名称
     * @returns {string} 验证后的主题名称
     */
    _validateTheme(theme) {
        if (!theme || !this.validThemes.includes(theme)) {
            console.warn('[MapVisualManager] Invalid theme:', theme, '- using default: normal');
            return 'normal';
        }
        return theme;
    }
    
    /**
     * 应用地板图层
     * @private
     * @param {HTMLElement} mapGrid - 地图网格容器
     * @param {string} theme - 主题名称
     */
    _applyFloorLayers(mapGrid, theme) {
        // 检查 FloorLayerManager 是否可用
        if (!this.floorLayerManager) {
            console.warn('[MapVisualManager] FloorLayerManager not available, skipping floor layers');
            return;
        }
        
        try {
            // 移除旧的地板图层（如果存在）
            const hasExistingLayers = this.floorLayerManager.layers.has(mapGrid);
            if (hasExistingLayers) {
                this.floorLayerManager.removeFloorLayers(mapGrid);
                console.log('[MapVisualManager] Removed old floor layers');
            }
            
            // 应用新的地板图层
            this.floorLayerManager.applyPreset(mapGrid, theme);
            console.log('[MapVisualManager] Applied floor layers:', theme);
            
        } catch (error) {
            console.error('[MapVisualManager] Failed to apply floor layers:', error);
        }
    }
    
    /**
     * 应用环境粒子特效
     * @private
     * @param {HTMLElement} mapGrid - 地图网格容器
     * @param {string} theme - 主题名称
     * @param {boolean} forceRebuild - 是否强制重建粒子系统
     */
    _applyEnvironmentParticles(mapGrid, theme, forceRebuild) {
        // 检查 EnhancedEffectsManager 是否可用
        if (!this.enhancedEffects) {
            console.warn('[MapVisualManager] EnhancedEffectsManager not available, skipping particles');
            return;
        }
        
        try {
            // 判断是否需要重建粒子系统
            const shouldRebuild = this._shouldRebuildParticles(theme, forceRebuild);
            
            console.log('[MapVisualManager] Particle rebuild check:', {
                forceRebuild: forceRebuild,
                themeChanged: this.currentTheme !== theme,
                currentTheme: this.currentTheme,
                newTheme: theme,
                particleSystemExists: this.enhancedEffects.particleSystems.has(theme),
                shouldRebuild: shouldRebuild
            });
            
            if (shouldRebuild) {
                console.log('[MapVisualManager] Rebuilding environment particles...');
                this.enhancedEffects.createEnvironmentParticles(mapGrid, theme);
                console.log('[MapVisualManager] Environment particles rebuilt');
            } else {
                console.log('[MapVisualManager] Keeping existing particle system (no rebuild needed)');
            }
            
        } catch (error) {
            console.error('[MapVisualManager] Failed to apply environment particles:', error);
        }
    }
    
    /**
     * 判断是否需要重建粒子系统
     * @private
     * @param {string} theme - 新主题
     * @param {boolean} forceRebuild - 强制重建标志
     * @returns {boolean} 是否需要重建
     */
    _shouldRebuildParticles(theme, forceRebuild) {
        // 1. 强制重建标志为 true（地图完全重建）
        if (forceRebuild) {
            return true;
        }
        
        // 2. 地板主题发生变化
        const themeChanged = this.currentTheme !== theme;
        if (themeChanged) {
            return true;
        }
        
        // 3. 粒子系统不存在
        const particleSystemExists = this.enhancedEffects && 
                                     this.enhancedEffects.particleSystems.has(theme);
        if (!particleSystemExists) {
            return true;
        }
        
        // 其他情况不需要重建
        return false;
    }
    
    /**
     * 清理所有视觉效果
     * 用于地图切换或游戏结束时的资源清理
     */
    cleanup() {
        console.log('[MapVisualManager] Cleaning up visual effects...');
        
        try {
            // 清理地板图层
            if (this.floorLayerManager) {
                this.floorLayerManager.cleanup();
            }
            
            // 清理粒子系统
            if (this.enhancedEffects) {
                this.enhancedEffects.clearEnvironmentParticles();
            }
            
            // 重置状态
            this.currentTheme = null;
            this.lastMapSize = null;
            
            console.log('[MapVisualManager] Cleanup completed');
            
        } catch (error) {
            console.error('[MapVisualManager] Cleanup failed:', error);
        }
    }
    
    /**
     * 获取当前主题
     * @returns {string|null} 当前主题名称
     */
    getCurrentTheme() {
        return this.currentTheme;
    }
    
    /**
     * 检查主题是否有效
     * @param {string} theme - 主题名称
     * @returns {boolean} 是否有效
     */
    isValidTheme(theme) {
        return this.validThemes.includes(theme);
    }
    
    /**
     * 获取所有支持的主题列表
     * @returns {Array<string>} 主题名称数组
     */
    getSupportedThemes() {
        return [...this.validThemes];
    }
    
    /**
     * 更新管理器引用（用于动态更新）
     * 当 EnhancedEffectsManager 重新初始化时调用
     */
    updateManagerReferences() {
        this.floorLayerManager = window.floorLayerManager;
        this.enhancedEffects = this.game.enhancedEffects;
        console.log('[MapVisualManager] Manager references updated');
    }
}

// 导出到全局作用域
if (typeof window !== 'undefined') {
    window.MapVisualManager = MapVisualManager;
}

