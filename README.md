# 🏰 Labyrinthia AI

[![GitHub stars](https://img.shields.io/github/stars/RusianHu/Labyrinthia-AI?style=social)](https://github.com/RusianHu/Labyrinthia-AI/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/RusianHu/Labyrinthia-AI?style=social)](https://github.com/RusianHu/Labyrinthia-AI/network/members)
[![LLM Powered](https://img.shields.io/badge/LLM-Powered-purple.svg)](https://github.com/RusianHu/Labyrinthia-AI)
[![Status](https://img.shields.io/badge/Status-Active-success.svg)](https://github.com/RusianHu/Labyrinthia-AI)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

> 一个基于 DND 背景的 Roguelike 地牢探险游戏，由大语言模型实时生成游戏内容和叙事。

<img width="784" height="1282" alt="image" src="https://github.com/user-attachments/assets/1cd663be-5162-445f-b96f-3b1b72bc5250" />

## ✨ 基础功能

### 无限的内容生成
- **实时叙事生成**：每一次行动都由 LLM 生成独特的故事叙述
- **动态地图创建**：基于任务上下文智能生成地下城地图
- **智能怪物生成**：根据玩家等级和任务需求动态创建敌人
- **任务系统**：LLM 控制的任务进度和剧情发展

### 事件与风格选择
- **事件选择框**：类似 Galgame 的选项系统，让玩家做出关键决策
- **LLM 完全控制**：AI 可以直接修改地图、创建事件、调整角色属性
- **动态剧情分支**：每个选择都会影响游戏世界和任务进展

### 完全随机地图系统
- **任务驱动生成**：地图布局基于当前任务需求动态调整
- **多样化地形**：房间、走廊、宝藏室、BOSS房等多种地形类型
- **交互式探索**：点击移动、悬停显示详情、路径高亮

### 进度管理与控制
- **智能进度追踪**：自动记录玩家行为并推进任务进度
- **事件权重系统**：不同行为对任务进度的贡献度不同
- **动态难度调整**：根据进度自动调整挑战难度

### 存档管理系统
- **用户识别**：基于 Cookie + Session 的自动用户识别
- **存档隔离**：每个用户拥有独立的存档空间
- **存档导出**：一键导出存档为 JSON 文件，支持备份和分享
- **存档导入**：导入之前导出的存档，支持跨设备游戏
- **多存档支持**：同一用户可以拥有多个存档槽位
- **用户统计**：查看总游戏时长、最高等级等统计信息

## 🚀 快速开始

### 环境要求

- Python 3.10+
- 支持的 LLM 服务商：
  - Google Gemini API
  - OpenRouter
  - OpenAI 兼容 API
  - LM Studio (本地部署)

### 安装步骤

1. **克隆仓库**
```bash
git clone https://github.com/RusianHu/Labyrinthia-AI.git
cd Labyrinthia-AI
```

2. **安装依赖**
```bash
pip install -r requirements.txt
```

3. **配置 API 密钥**

直接把 `.env.example` 重命名为 `.env`：

```python
# 选择 LLM 提供商
LLM_PROVIDER=openai  # 可选: gemini, openrouter, openai, lmstudio

# API 密钥配置
GEMINI_API_KEY=your_gemini_key
OPENROUTER_API_KEY=your_openrouter_key
OPENAI_API_KEY=your_openai_key
OPENAI_BASE_URL=https://your-api-endpoint/v1
```

4. **启动游戏**
```bash
python start.py
```

或直接运行：
```bash
python main.py
```

游戏将在 `http://127.0.0.1:8001` 启动。

### 快速测试

访问 `/direct-start` 可以自动创建游戏并直接进入：
```
http://127.0.0.1:8001/direct-start
```

## 🎮 基础游戏玩法

### 基础操作
- **移动**：点击相邻的瓦片移动角色
- **攻击**：点击相邻的怪物进行攻击
- **使用物品**：在背包中点击物品使用
- **事件选择**：在弹出的选项框中做出决策

### 任务系统
- 每个任务都有独特的故事背景和目标
- 任务进度由 LLM 智能控制
- 完成任务后可以选择新的冒险方向

### 战斗系统
- 基于 DND 规则的回合制战斗
- 考虑距离、地形和角色属性
- 战斗结果影响任务进度

### 存档管理 🆕
- **导出存档**：在存档列表中点击"导出"按钮，下载 JSON 格式的存档文件
- **导入存档**：在主菜单点击"导入存档"，选择之前导出的文件
- **跨设备游戏**：通过导出/导入功能在不同设备间迁移存档
- **存档备份**：定期导出重要存档，防止数据丢失
- **存档分享**：将精彩的游戏进度分享给朋友

详细使用说明请查看 [存档管理指南](./SAVE_MANAGEMENT_GUIDE.md)

## 🛠️ 技术架构

### 后端技术栈
- **FastAPI**：高性能异步 Web 框架
- **Pydantic**：数据验证和序列化
- **Asyncio**：异步 LLM 调用和并发处理

### LLM 集成
- **多提供商支持**：灵活切换不同的 LLM 服务
- **异步调用**：高效的并发请求处理
- **错误重试**：自动重试机制确保稳定性
- **上下文管理**：智能的对话历史压缩

### 前端技术
- **原生 JavaScript**：模块化的游戏逻辑
- **Material Icons**：丰富的图标库
- **CSS3 动画**：流畅的视觉效果

## 📝 配置说明

### 游戏配置 (`config.py`)

```python
# 调试模式
debug_mode = True
show_llm_debug = True

# 地图设置
default_map_size = (20, 20)

# 任务设置
quest_progress_multiplier = 30.0  # 每层楼增加的进度百分比
max_quest_floors = 3              # 任务最大楼层数

# LLM 设置
max_output_tokens = None          # 不限制输出长度
temperature = 0.8
```

### 代理配置

如果需要使用代理访问 LLM API：

```python
use_proxy = True
proxy_url = "http://127.0.0.1:10808"
```

## 🔧 开发与调试

### 调试模式

启用调试模式后可以访问：
- `/quick_test.html` - 快速测试界面
- `/api/debug/*` - 调试 API 端点
- LLM 请求/响应查看器

### 测试 API

项目提供了丰富的测试端点：
```
POST /api/test/gemini              # 测试 Gemini API
POST /api/test/content-generation  # 测试内容生成
POST /api/test/map-generation      # 测试地图生成
POST /api/test/quest-system        # 测试任务系统
```

## 🙏 致谢

- 感谢 Google Gemini、OpenRouter 等 LLM 服务提供商
- 感谢 FastAPI 和 Python 社区
- 灵感来源于经典的 DND 和 Roguelike 游戏

## 📄 许可证

本项目采用 [MIT 许可证](./LICENSE)。
