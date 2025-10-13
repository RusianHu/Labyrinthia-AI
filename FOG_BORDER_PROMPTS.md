# 🌫️ 战争迷雾边框素材 - AI生成提示词

本文档包含用于生成"战争迷雾"风格地图边框素材的AI图像生成提示词。这些提示词可用于Pollinations、Midjourney、DALL-E、Stable Diffusion等AI图像生成工具。

---

## 📦 素材清单

### 1. 顶部边框 (fog_border_top.png)
**尺寸**: 1024 x 200 像素  
**用途**: 地图顶部的迷雾渐变效果

**英文提示词**:
```
Fog of war map border overlay, top edge, dark misty fog gradient fading from opaque black at top to transparent at bottom, atmospheric smoke effect, game UI asset, seamless tileable horizontal pattern, 1024x200 pixels, RPG map border
```

**中文提示词**:
```
战争迷雾地图边框叠加层，顶部边缘，深色雾气渐变从顶部不透明黑色渐变到底部透明，大气烟雾效果，游戏UI素材，无缝可平铺水平图案，1024x200像素，RPG地图边框
```

**关键参数**:
- 渐变方向: 从上到下（不透明→透明）
- 颜色: 深黑色到透明
- 效果: 烟雾、迷雾、大气感
- 可平铺: 水平方向

---

### 2. 左侧边框 (fog_border_left.png)
**尺寸**: 200 x 1024 像素  
**用途**: 地图左侧的迷雾渐变效果（右侧通过旋转180度复用）

**英文提示词**:
```
Fog of war map border overlay, left edge, dark misty fog gradient fading from opaque black at left to transparent at right, atmospheric smoke effect, game UI asset, seamless tileable vertical pattern, 200x1024 pixels, RPG map border
```

**中文提示词**:
```
战争迷雾地图边框叠加层，左侧边缘，深色雾气渐变从左侧不透明黑色渐变到右侧透明，大气烟雾效果，游戏UI素材，无缝可平铺垂直图案，200x1024像素，RPG地图边框
```

**关键参数**:
- 渐变方向: 从左到右（不透明→透明）
- 颜色: 深黑色到透明
- 效果: 烟雾、迷雾、大气感
- 可平铺: 垂直方向

---

### 3. 角落迷雾 (fog_corner.png)
**尺寸**: 300 x 300 像素  
**用途**: 地图四个角落的迷雾晕影效果（通过旋转应用到四个角）

**英文提示词**:
```
dark fog corner vignette, misty smoke gradient, transparent center, game UI corner overlay, 300x300 pixels
```

**中文提示词**:
```
深色迷雾角落晕影，雾气烟雾渐变，中心透明，游戏UI角落叠加层，300x300像素
```

**关键参数**:
- 渐变方向: 从角落向中心（不透明→透明）
- 颜色: 深黑色到透明
- 效果: 晕影、烟雾
- 形状: 角落渐变

---

### 4. 迷雾粒子 (fog_particles.png)
**尺寸**: 512 x 512 像素  
**用途**: 动画迷雾粒子层，通过CSS动画创建漂浮效果

**英文提示词**:
```
Animated fog particles overlay, subtle floating mist particles, dark atmospheric smoke wisps, transparent background, game UI effect, 512x512 pixels, seamless loop texture for fog of war effect
```

**中文提示词**:
```
动画迷雾粒子叠加层，微妙的漂浮雾气粒子，深色大气烟雾缕缕，透明背景，游戏UI效果，512x512像素，战争迷雾效果的无缝循环纹理
```

**关键参数**:
- 粒子: 细小、漂浮、分散
- 颜色: 深灰色、半透明
- 背景: 透明
- 可平铺: 四方向无缝

---

## 🎨 生成技巧

### 通用建议
1. **颜色方案**: 使用深黑色 (#000000) 到透明的渐变
2. **透明度**: 确保渐变边缘完全透明，以便自然融合
3. **无缝平铺**: 边框素材需要能够无缝平铺
4. **分辨率**: 建议使用高分辨率生成，然后缩小以获得更好的质量

### 针对不同工具的调整

#### Midjourney
添加参数: `--ar 5:1` (顶部边框), `--ar 1:5` (左侧边框), `--ar 1:1` (角落和粒子)

#### DALL-E
强调 "transparent background" 和 "gradient to transparent"

#### Stable Diffusion
使用负面提示词: "hard edges, solid colors, patterns, textures"

#### Pollinations (Flux)
当前使用的工具，提示词已优化

---

## 🔧 CSS应用方式

生成的素材通过以下CSS类应用：

```css
/* 顶部边框 */
.fog-border-horizontal.top {
    background-image: url('../images/fog_border_top.png');
}

/* 底部边框（旋转180度） */
.fog-border-horizontal.bottom {
    background-image: url('../images/fog_border_top.png');
    transform: rotate(180deg);
}

/* 左侧边框 */
.fog-border-vertical.left {
    background-image: url('../images/fog_border_left.png');
}

/* 右侧边框（旋转180度） */
.fog-border-vertical.right {
    background-image: url('../images/fog_border_left.png');
    transform: rotate(180deg);
}

/* 四个角落（通过旋转应用） */
.fog-corner.top-left { transform: rotate(0deg); }
.fog-corner.top-right { transform: rotate(90deg); }
.fog-corner.bottom-left { transform: rotate(-90deg); }
.fog-corner.bottom-right { transform: rotate(180deg); }

/* 粒子动画 */
.fog-particles {
    background-image: url('../images/fog_particles.png');
    animation: fog-drift 30s linear infinite;
}
```

---

## 🎯 变体建议

### 不同颜色主题

#### 蓝色迷雾（魔法主题）
替换 "dark misty fog" 为 "dark blue magical mist"

#### 绿色迷雾（毒雾主题）
替换 "dark misty fog" 为 "dark green toxic fog"

#### 红色迷雾（血雾主题）
替换 "dark misty fog" 为 "dark red blood mist"

#### 紫色迷雾（暗影主题）
替换 "dark misty fog" 为 "dark purple shadow mist"

### 不同密度

#### 浓雾版本
添加 "dense, thick fog" 到提示词

#### 轻雾版本
添加 "light, subtle mist" 到提示词

---

## 📝 使用示例

### 在第三方工具中使用

1. **复制对应的提示词**
2. **设置正确的尺寸**
3. **生成图片**
4. **保存为PNG格式**（保留透明度）
5. **放置到 `static/images/` 目录**
6. **刷新浏览器查看效果**

### 快速测试
访问 `http://127.0.0.1:8001/test_fog_border.html` 查看边框效果对比

---

## 🔄 更新记录

- **2025-10-13**: 初始版本，创建4个基础迷雾边框素材
- 使用Pollinations (Flux模型) 生成
- 应用到Labyrinthia AI游戏项目

---

## 💡 提示

- 如果生成的边框不够透明，可以使用图像编辑软件调整透明度渐变
- 如果边框太浓或太淡，可以通过CSS的 `opacity` 属性调整
- 粒子层的动画速度可以通过修改 `animation-duration` 调整
- 可以创建多个粒子层叠加以获得更丰富的效果

---

**生成工具**: Pollinations AI (Flux Model)  
**项目**: Labyrinthia AI  
**日期**: 2025-10-13

