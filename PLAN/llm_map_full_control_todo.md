# Labyrinthia AI - 完全版 LLM 地图控制权能实施 TODO（分 P 规划）

> 目标：构建“LLM 高权能 + 本地强约束 + 可审计 + 可回滚”的生产级地图生成体系。  
> 范围：后端生产链路（地图生成、怪物生成、任务进度、事件系统、调试与审计），不包含临时最小改动方案。  
> 约束：保证地图可达、楼梯规则、任务节奏、单活跃任务与进度安全阈值。

---

## P0 - 架构基线与契约层（必须先完成）

### P0.1 统一生成契约（Generation Contract）
- [ ] 定义 `generation_contract` 顶层结构并落盘（版本化）
- [ ] 在地图请求中新增 `contract_version` 与 `contract_hash`
- [ ] 统一 `llm`/`local` 两条链路都消费同一契约对象
- [ ] 增加契约解析失败降级策略（回退默认契约 + 明确告警）
- [ ] 在 metadata 中记录 `contract_source`（llm/manual/default）

### P0.2 LLM 蓝图 Schema V2（高权能）
- [ ] 扩展 `room_nodes`：支持 `placement_policy`、`must_contain`、`room_tags`
- [ ] 扩展 `corridor_edges`：支持 `risk_level`、`gate_type`、`encounter_bias`
- [ ] 新增 `quest_monster_bindings`：任务怪物与节点/边绑定
- [ ] 新增 `event_plan`：mandatory/optional/forbidden 三层规则
- [ ] 新增 `progress_plan`：任务目标、进度预算、完成策略
- [ ] 保留 “禁止绝对坐标输出” 规则（LLM 仅给结构意图）

### P0.3 本地白名单与安全收敛
- [ ] 白名单过滤未知字段（所有层级）
- [ ] 标准化 ID、去重、上限裁剪（节点数/边数/意图数量）
- [ ] 强制连通图修复（多连通分量自动桥接）
- [ ] 强制关键路径修复（entrance -> objective/boss 可达）
- [ ] 强制楼梯合法性（首层无上楼、顶层无下楼）
- [ ] 强制陷阱密度上限（全链路统一口径）

### P0.4 地图更新契约统一
- [ ] 统一 `map_updates` 格式为 `{"tiles": {"x,y": {...}}}`
- [ ] 统一事件系统/状态修改器的地图更新口径
- [ ] 增加契约校验错误码（字段错位/类型错误/越权字段）

---

## P1 - 生产算法执行器（LLM 权能真正落地）

### P1.1 Blueprint Realizer 2.0
- [ ] 支持按节点角色与大小落地房间（small/medium/large）
- [ ] 支持按 `placement_policy` 落地（center/edge/branch/corridor_adjacent）
- [ ] 支持房间模板实例（祭坛房、宝库、Boss 前厅、隐藏房）
- [ ] 支持节点级“必须内容”落地（事件/怪物/任务怪物）
- [ ] 对落地失败节点输出 `realization_errors` 并自动补偿

### P1.2 Corridor Planner 2.0
- [ ] 支持 direct/branch/loop 目标比例
- [ ] 支持关键路径长度下限与分支复杂度上限
- [ ] 支持通道风格标签影响（风险区/叙事区/过渡区）
- [ ] 连接失败时执行最小修复并输出修复日志

### P1.3 Spawn Planner（普通怪 + 任务怪）
- [ ] 普通怪支持 `spawn_profile`（数量、难度、分布偏置）
- [ ] 任务怪支持 `quest_monster_bindings` 精确绑定（节点/边）
- [ ] 支持“同层多任务怪”与“主次目标怪”
- [ ] 支持冲突解算（怪物点位冲突、与事件冲突、与楼梯冲突）
- [ ] 生成最终 `monster_hints` + `spawn_audit`

#### P1.3.A LLM 怪物定制权限矩阵（生产规则）
- [ ] 定义 `monster_customization_policy`（llm_allowed / llm_guarded / local_only）
- [ ] `llm_allowed`：允许 LLM 直接定制 `name/description/tags/behavior`
- [ ] `llm_guarded`：允许 LLM 提议 `hp/ac/damage/status_effects/resistances/skills`，必须经本地规则裁剪
- [ ] `local_only`：`spawn_cap/同屏上限/跨层刷怪限制/战斗资源上限` 仅本地可改
- [ ] 对“超模参数”执行自动压制并写入 `monster_adjustment_report`

#### P1.3.B Boss/任务怪模板与超模阈值
- [ ] 建立 `monster_power_budget`（按玩家等级、楼层、任务阶段计算）
- [ ] 支持任务怪模板字段：`is_final_objective`、`phase_count`、`special_status_pack`
- [ ] 允许出现高血量怪（如 `hp=666`）但必须满足 `final_floor + final_objective + power_budget_pass`
- [ ] 特殊状态（灼烧、诅咒、护盾、召唤）需走 `status_whitelist` 与回合上限
- [ ] 若超预算，自动降级（如 `666 -> budget_cap`）并记录原因


### P1.4 Event Planner（任务事件优先）
- [ ] mandatory 事件先放置，再放 optional
- [ ] 支持事件类型禁用列表与密度区间
- [ ] 支持房间/通道级事件意图映射
- [ ] 对 mandatory 事件做可达性二次验证
- [ ] 输出 `event_placement_report`

---

## P2 - 任务进度系统重构（支持“任务怪=100%”但可控）

### P2.1 Progress Plan 契约化
- [ ] 为每个任务生成 `progress_plan`（预算总表）
- [ ] 拆分预算桶：`events`、`quest_monsters`、`map_transition`、`exploration_buffer`
- [ ] 明确 `completion_policy`：`aggregate` / `single_target_100` / `hybrid`
- [ ] 预算校验与自动修正接入验证器

### P2.2 单目标 100% 完成策略（你需要的核心能力）
- [ ] 增加 `QuestMonster.is_final_objective` 字段
- [ ] 增加 `completion_guard`：
  - [ ] `require_final_floor`
  - [ ] `require_all_mandatory_events`
  - [ ] `min_progress_before_final_burst`
  - [ ] `max_single_increment_except_final`
- [ ] 战斗结算时若命中 final objective 且 guard 通过，允许直接完成
- [ ] guard 不通过时降级为上限增量并记录原因

### P2.3 进度安全与防滥用
- [ ] 增加进度异常检测（单次突增、重复击杀、非法怪物ID）
- [ ] 增加幂等保护（同一任务怪物重复结算只生效一次）
- [ ] 增加“进度账本”审计（每次增量来源与依据）
- [ ] 与补偿器协同：只做收尾，不覆盖硬规则

---

## P3 - LLM Patch 引擎与可回滚执行

### P3.1 Patch DSL（指令层）
- [ ] 定义 `patches[]` 指令集（add/remove/update）
- [ ] 支持对象：room/corridor/tile/event/monster/quest_binding
- [ ] 每条 patch 增加 `intent_reason` 与 `risk_level`
- [ ] 支持 patch 批次签名与顺序依赖

### P3.2 Patch Executor
- [ ] patch 逐条执行 + 每步验证
- [ ] 任一失败可部分回滚或全量回滚（策略可配）
- [ ] 输出 `accepted_patches` / `rejected_patches` / `rollback_trace`
- [ ] 按错误类型生成可操作诊断（非静默失败）

### P3.3 运行时稳定性
- [ ] patch 后必须复跑：连通性、楼梯合法、mandatory 可达
- [ ] patch 后必须复跑：怪物/事件冲突与进度预算检查
- [ ] 复检失败自动回退到上一快照

---

## P4 - 调试、观测、审计与运维

### P4.1 调试面板增强（完整原始数据）
- [ ] 展示原始 LLM 请求体与响应体（地图生成专用）
- [ ] 展示 Blueprint V2、Patch DSL、修复与拒绝详情
- [ ] 展示 Progress Plan 与实时进度账本
- [ ] 提供“一键导出调试包（JSON）”

### P4.2 指标与告警
- [ ] 地图生成成功率、回退率、修复率、回滚率
- [ ] 关键目标不可达率、楼梯违规率、进度异常率
- [ ] 任务怪 100% 直完触发率与失败原因分布
- [ ] 告警分级（P0/P1 线上阻断）

### P4.3 回归测试体系
- [ ] 构建固定种子场景库（Boss、探索、救援、调查、多目标）
- [ ] 构建契约兼容测试（schema 版本升级）
- [ ] 构建进度正确性测试（特别是单目标100%）
- [ ] 构建并发与锁测试（异步多请求下状态一致）

---

## P5 - 发布策略（灰度到全面）

### P5.1 发布分级
- [ ] `debug`：仅测试接口启用 Contract V2 + Patch
- [ ] `canary`：按用户比例放量，实时观测告警
- [ ] `stable`：替换旧链路为默认主链路

### P5.2 数据迁移与兼容
- [ ] 旧任务缺失 `progress_plan` 时自动补全
- [ ] 旧地图 metadata 缺失字段自动填默认
- [ ] 存档读写版本号与迁移记录

### P5.3 回滚预案
- [ ] 配置开关一键切回旧生成链路
- [ ] 保留审计日志与失败样本供复盘
- [ ] 回滚后自动禁用高风险 patch 类型

---

## 验收标准（Definition of Done）

### 功能验收
- [ ] LLM 可指定房间数量区间与目标值，并稳定落地
- [ ] LLM 可定制多个房间（角色、规模、意图）并通过验证
- [ ] LLM 可定制普通怪与任务怪绑定点位（无冲突）
- [ ] 支持“任务怪击败后直接100%完成”且 guard 生效
- [ ] 所有 mandatory 目标可达，楼梯规则零违规

### 质量验收
- [ ] 地图生成失败回退率低于阈值（可配置）
- [ ] 关键目标不可达率 < 0.1%
- [ ] 进度异常告警率持续下降并可定位
- [ ] 调试面板可完整还原一次生成全过程

---

## 研发执行清单（建议顺序）
- [ ] 先完成 P0（契约 + 安全收敛）
- [ ] 再完成 P1（执行器）
- [ ] 同步推进 P2（进度重构，重点单目标100%）
- [ ] 然后上 P3（Patch 可回滚）
- [ ] 最后 P4/P5（观测、测试、发布）

---

## 典型任务样例（建议纳入需求基线）

### 样例 A：终局回收遗物（特殊瓦片 + 守卫）
- [ ] 任务目标：到达最深层并回收遗物
- [ ] LLM 生成 `mandatory` 特殊事件瓦片（回收点）
- [ ] LLM 生成守卫编组（可含任务怪/精英怪/状态包）
- [ ] 规则：守卫未清空时不可触发回收成功
- [ ] 规则：回收成功后按 `completion_policy` 判定是否直达 100%
- [ ] 守卫与瓦片都必须通过可达性与冲突校验

### 样例 B：单目标讨伐（任务怪击败直完）
- [ ] 任务怪标记 `is_final_objective=true`
- [ ] 任务怪允许高规格参数（示例：高HP + 特殊状态）
- [ ] 仅在 `completion_guard` 满足时允许 100%
- [ ] 不满足 guard 自动降级为受限增量并审计

### 样例 C：多目标混合任务（事件 + 怪物 + 地图切换）
- [ ] 进度预算拆分到 `events/quest_monsters/map_transition`
- [ ] 允许 `hybrid` 完成策略（终局触发补齐）
- [ ] 禁止任一普通目标单次直接打满 100%

---

## 补充建议（架构与产品层）
- [ ] 为每次生成输出“任务可达证明”（关键目标路径摘要）
- [ ] 增加“难度意图 vs 实际落地”偏差报告，防止 LLM 过拟合叙事而失衡
- [ ] 对 Boss/任务怪建立可解释战力评分（前端调试可视化）
- [ ] 在调试面板加入“一键复现实例”（contract + seed + patch 批次）
- [ ] 为直达 100% 的任务建立专项回归集，防止剧情短路

---

## 备注
- 本文档为“完全版”实施清单，不包含最小改动路径。
- 若后续调整规则（例如进度阈值、楼层系数、陷阱密度），需同步更新本清单对应条目。
