/**
 * Labyrinthia AI - Voice GM and message replay manager
 * Browser-only audio cache; no persistent storage.
 *
 * ====== 语音消息白名单分级 ======
 * 所有消息通过 classifyMessage(text, type) 归入若干 voice_category；
 * 每个 voice_category 都有 readByDefault / minLength / 决策标签，并允许被
 * localStorage 覆盖（白名单实时调整）；后端 .env 提供初始默认值。
 *
 * 设计目标：
 *   - 不让 “攻击了 xxx / 移动到 (x,y) / 网络错误 / 已保存” 这类模板消息触发 TTS
 *   - 优先朗读 LLM 叙事（narrative / event / combat_narrative / choice）
 *   - “均衡”默认：附加任务进展、升级、首次发现关键设施
 *   - 提供调试日志 (window.localStorage 'labyrinthia.tts.debug' = '1')
 *   - 决策完全可解释，调试面板可读
 */

const TTS_VOLUME_STORAGE_KEY = 'labyrinthia.tts.volume';
const TTS_MUTE_STORAGE_KEY = 'labyrinthia.tts.muted';
const TTS_WHITELIST_STORAGE_KEY = 'labyrinthia.tts.whitelist';
const TTS_DEBUG_STORAGE_KEY = 'labyrinthia.tts.debug';
const TTS_DECISION_HISTORY_LIMIT = 60;

// 语音消息分类表：决定哪些消息进入 TTS 队列
// readByDefault 为 true 表示该分类默认朗读，可被白名单覆盖
const TTS_VOICE_CATEGORIES = Object.freeze({
    narrative: {
        label: '叙事旁白',
        description: 'LLM 生成的旁白与场景描写',
        readByDefault: true,
        minLength: 8,
        ttsCategory: 'narrative',
        priority: 100,
    },
    event: {
        label: '事件叙述',
        description: '剧情/事件触发后的描述文本',
        readByDefault: true,
        minLength: 8,
        ttsCategory: 'event',
        priority: 95,
    },
    combat_narrative: {
        label: '战斗叙事',
        description: 'LLM 生成的战斗经过描述（≥24字符）',
        readByDefault: true,
        minLength: 24,
        ttsCategory: 'combat',
        priority: 90,
    },
    choice: {
        label: '事件选项',
        description: '事件选项的标题/描述/可选行动',
        readByDefault: true,
        minLength: 6,
        ttsCategory: 'choice',
        priority: 85,
    },
    quest: {
        label: '任务进展',
        description: '任务发布、目标更新、完成提示',
        readByDefault: true,
        minLength: 6,
        ttsCategory: 'event',
        priority: 80,
    },
    milestone: {
        label: '关键里程碑',
        description: '升级、首次发现楼梯/宝藏、击败重要敌人',
        readByDefault: true,
        minLength: 4,
        ttsCategory: 'system',
        priority: 70,
    },
    // ===== 默认黑名单（不读） =====
    combat_summary: {
        label: '战斗模板',
        description: '“X 攻击了 Y / 造成 N 伤害 / 被击败了”等模板',
        readByDefault: false,
        minLength: 0,
        ttsCategory: 'combat',
        priority: 30,
    },
    action: {
        label: '玩家行动',
        description: '“攻击了 xxx / 移动到 xxx / 拾取了 xxx”',
        readByDefault: false,
        minLength: 0,
        ttsCategory: 'action',
        priority: 25,
    },
    status: {
        label: '状态变化',
        description: '“获得 5 点经验 / 恢复 10 HP / 装备已穿戴”',
        readByDefault: false,
        minLength: 0,
        ttsCategory: 'system',
        priority: 20,
    },
    system_state: {
        label: '系统提示',
        description: '“游戏已保存 / 加载 / 删除”等无叙事系统消息',
        readByDefault: false,
        minLength: 0,
        ttsCategory: 'system',
        priority: 15,
    },
    error: {
        label: '错误提示',
        description: '“网络错误 / 无法穿过墙壁 / 目标距离太远”',
        readByDefault: false,
        minLength: 0,
        ttsCategory: 'system',
        priority: 10,
    },
    warning: {
        label: '警告提示',
        description: '会话失效、可重试错误等',
        readByDefault: false,
        minLength: 0,
        ttsCategory: 'system',
        priority: 8,
    },
    debug: {
        label: '调试输出',
        description: 'Emoji 前缀的调试/管理消息',
        readByDefault: false,
        minLength: 0,
        ttsCategory: 'system',
        priority: 1,
    },
});

// 通用强黑名单 — 任何分类匹配都拒绝（永远不会被朗读，包括用户开启对应分类后）
// 仅保留“绝对不应该出现在 GM 语音中的内容”：系统/调试/坐标/状态前缀。
const TTS_HARD_BLACKLIST_PATTERNS = [
    /^(游戏已加载|游戏已保存|存档已删除|新游戏开始|加载失败|保存失败|删除失败|创建游戏失败)/,
    /^(正在导出存档|存档导出成功|导出存档失败|正在导入存档|存档导入成功|导入存档失败)/,
    /^移动到\s*\(.+\)\s*$/,                  // 纯坐标移动行
    /(网络错误|无法连接到服务器|发生错误|请重试)/,
    /(LLM调用已终止|API请求|Trace|装备计算|物品影响摘要|生成链路|调试包)/i,
    /^(\[[^\]]+\]\s*)?(充能|冷却|是否消耗|情报等级|触发提示|风险提示|预期结果)[:：]/,
    /^(位置|楼层|AC|HP|MP|经验)[:：]/,
    /^[❌✅🎲📊📁📍📷🐛🚀💚💀🧹💎🎒🗺️👹🎮💡⚠️📦📜🧭✨]/u,  // 调试 Emoji 前缀
    /^(无法移动到该位置|该位置已被占据|无法穿过墙壁|目标距离太远|视线被阻挡|目标未找到|无效的移动方向)/,
    /^(陷阱事件注册失败|无法注册陷阱事件|陷阱触发失败|事件处理失败)/,
];

// 软分类识别：把短模板消息归入 action / combat_summary / status，
// 用户可在白名单中开启对应分类来允许朗读。
const TTS_SOFT_TEMPLATE_PATTERNS = [
    { regex: /^攻击了\s+\S+/u, voiceCategory: 'action' },
    { regex: /^(向\s*\S+\s*移动|拾取了\s+\S+|装备了\s+\S+|卸下了\s+\S+|使用了\s+\S+)/u, voiceCategory: 'action' },
    { regex: /^对\s+\S+\s*造成了?\s*\d+\s*点?伤害/u, voiceCategory: 'combat_summary' },
    { regex: /^[^，。.\s]{1,16}\s*被击败了[!！。]?$/u, voiceCategory: 'combat_summary' },
    { regex: /^[^，。.\s]{1,16}\s*攻击了你[，,]\s*造成\s*\d+\s*点伤害/u, voiceCategory: 'combat_summary' },
    { regex: /^获得了?\s*\d+\s*点?经验[!！。]?$/u, voiceCategory: 'status' },
    { regex: /^(恢复|回复|消耗|失去)了?\s*\d+/u, voiceCategory: 'status' },
    { regex: /^触发了陷阱[!！。]?$/u, voiceCategory: 'combat_summary' },
];

// 不再依赖该常量，但保留导出避免破坏可能的扩展
const TTS_SOFT_BLACKLIST_BY_CATEGORY = {
    combat_summary: true,
    action: true,
    status: true,
    system_state: true,
    error: true,
    warning: true,
    debug: true,
};

// 里程碑识别：消息含这些关键词 + 正向语义 → milestone
const TTS_MILESTONE_PATTERNS = [
    /(恭喜升级|经验升级)/,
    /(任务已完成|任务完成|主线完成)/,
    /(发现了通往(下一层|上一层)的楼梯)/,
    /(发现了一处隐藏宝藏)/,
    /(突破了头领|击败了首领|战胜了)/,
];

class TTSManager {
    constructor(game) {
        this.game = game;
        this.autoEnabled = false;
        this.config = {
            enabled: false,
            provider: 'mimo_openai_compatible',
            model_name: 'mimo-v2.5-tts',
            default_voice: 'mimo_default',
            output_format: 'wav',
            max_text_chars: 800,
            // 后端可下发的“服务端默认白名单覆盖”（按分类名 -> bool）
            voice_whitelist_defaults: null,
        };
        this.audioCache = new Map();
        this.audioPromises = new Map();
        this.queue = [];
        this.queuedKeys = new Set();
        this.currentQueueKey = '';
        this.currentAudio = null;
        this.isPlaying = false;
        this.lastAutoKey = '';

        // 音量控制状态
        this.volume = this.loadStoredVolume();
        this.muted = this.loadStoredMute();

        // 白名单状态（覆盖默认值）
        this.whitelistOverrides = this.loadWhitelistOverrides();
        this.debugDecisions = this.loadDebugFlag();
        this.decisionHistory = [];
        this.decisionStats = {
            total: 0,
            spoken: 0,
            blocked: 0,
            byCategory: {},
        };

        this.setupControls();
    }

    loadStoredVolume() {
        try {
            const raw = window.localStorage?.getItem(TTS_VOLUME_STORAGE_KEY);
            const parsed = Number.parseFloat(raw);
            if (Number.isFinite(parsed) && parsed >= 0 && parsed <= 1) {
                return parsed;
            }
        } catch (error) {
            console.warn('[TTSManager] Failed to read stored volume:', error);
        }
        return 0.8;
    }

    loadStoredMute() {
        try {
            return window.localStorage?.getItem(TTS_MUTE_STORAGE_KEY) === '1';
        } catch (error) {
            console.warn('[TTSManager] Failed to read stored mute flag:', error);
            return false;
        }
    }

    persistVolume() {
        try {
            window.localStorage?.setItem(TTS_VOLUME_STORAGE_KEY, String(this.volume));
        } catch (error) {
            // ignore storage errors silently
        }
    }

    persistMute() {
        try {
            window.localStorage?.setItem(TTS_MUTE_STORAGE_KEY, this.muted ? '1' : '0');
        } catch (error) {
            // ignore storage errors silently
        }
    }

    getEffectiveVolume() {
        if (this.muted) return 0;
        return Math.max(0, Math.min(1, this.volume));
    }

    setVolume(value, options = {}) {
        const numeric = Number(value);
        if (!Number.isFinite(numeric)) return;
        const clamped = Math.max(0, Math.min(1, numeric));
        const previous = this.volume;
        this.volume = clamped;

        // 拖动到 0 视为静音；拖回非 0 自动取消静音
        if (clamped <= 0.001 && !this.muted) {
            this.muted = true;
            this.persistMute();
        } else if (clamped > 0.001 && this.muted) {
            this.muted = false;
            this.persistMute();
        }

        if (clamped !== previous) {
            this.persistVolume();
        }

        if (this.currentAudio) {
            this.currentAudio.volume = this.getEffectiveVolume();
        }

        if (options.silent !== true) {
            this.applyVolumeToControls();
        }
    }

    toggleMute() {
        this.muted = !this.muted;
        this.persistMute();
        if (this.currentAudio) {
            this.currentAudio.volume = this.getEffectiveVolume();
        }
        this.applyVolumeToControls();
    }

    getVolumeIconName() {
        if (this.muted) return 'volume_off';
        if (this.volume <= 0.001) return 'volume_mute';
        if (this.volume < 0.4) return 'volume_down';
        return 'volume_up';
    }

    applyVolumeToControls() {
        const percent = Math.round(this.volume * 100);
        const effectivePercent = Math.round(this.getEffectiveVolume() * 100);
        const iconName = this.getVolumeIconName();

        if (Array.isArray(this.volumeInputs)) {
            this.volumeInputs.forEach((input) => {
                if (Number(input.value) !== percent) {
                    input.value = String(percent);
                }
            });
        }

        if (Array.isArray(this.volumeSliders)) {
            this.volumeSliders.forEach((slider) => {
                slider.style.setProperty('--volume-percent', `${effectivePercent}%`);
                const fill = slider.querySelector('.voice-volume-fill');
                if (fill) {
                    fill.style.width = `${effectivePercent}%`;
                }
            });
        }

        if (Array.isArray(this.volumeValues)) {
            this.volumeValues.forEach((label) => {
                label.textContent = String(effectivePercent);
            });
        }

        if (Array.isArray(this.volumeIcons)) {
            this.volumeIcons.forEach((button) => {
                const iconEl = button.querySelector('.material-icons');
                if (iconEl) iconEl.textContent = iconName;
                button.setAttribute('aria-pressed', this.muted ? 'true' : 'false');
                button.title = this.muted ? '点击恢复音量' : '点击静音';
            });
        }

        if (Array.isArray(this.volumeControls)) {
            this.volumeControls.forEach((control) => {
                control.classList.toggle('is-muted', this.muted || this.volume <= 0.001);
            });
        }
    }

    setupControls() {
        this.toggles = Array.from(document.querySelectorAll('.voice-gm-toggle'));
        this.statuses = Array.from(document.querySelectorAll('.voice-gm-status'));
        this.shells = Array.from(document.querySelectorAll('[data-voice-panel], .voice-gm-control'));
        this.panels = Array.from(document.querySelectorAll('[data-voice-panel]'));
        this.volumeInputs = Array.from(document.querySelectorAll('.voice-volume-input'));
        this.volumeSliders = Array.from(document.querySelectorAll('.voice-volume-slider'));
        this.volumeFills = Array.from(document.querySelectorAll('.voice-volume-fill'));
        this.volumeValues = Array.from(document.querySelectorAll('.voice-volume-value'));
        this.volumeIcons = Array.from(document.querySelectorAll('.voice-volume-icon'));
        this.volumeControls = Array.from(document.querySelectorAll('.voice-volume-control'));

        this.toggle = this.toggles[0] || null;
        this.status = this.statuses[0] || null;
        this.shell = this.shells[0] || null;

        if (this.toggles.length === 0) {
            setTimeout(() => this.setupControls(), 250);
            return;
        }

        this.toggles.forEach((toggle) => {
            toggle.checked = this.autoEnabled;
            if (toggle.dataset.ttsBound === 'true') return;
            toggle.dataset.ttsBound = 'true';
            toggle.addEventListener('change', () => {
                this.autoEnabled = Boolean(toggle.checked);
                if (!this.autoEnabled) {
                    this.stop();
                    this.queue = [];
                    this.queuedKeys.clear();
                }
                this.updateControlState();
            });
        });

        this.volumeInputs.forEach((input) => {
            if (input.dataset.ttsBound === 'true') return;
            input.dataset.ttsBound = 'true';
            input.value = String(Math.round(this.volume * 100));
            const handler = (event) => {
                const v = Number(event.target.value) / 100;
                this.setVolume(v);
            };
            input.addEventListener('input', handler);
            input.addEventListener('change', handler);
        });

        this.volumeIcons.forEach((button) => {
            if (button.dataset.ttsBound === 'true') return;
            button.dataset.ttsBound = 'true';
            button.addEventListener('click', (event) => {
                event.preventDefault();
                event.stopPropagation();
                this.toggleMute();
            });
        });

        this.applyVolumeToControls();
        this.updateControlState();
    }

    updateConfig(config) {
        const incoming = config || {};
        this.config = {
            ...this.config,
            ...incoming
        };

        // 后端可下发 voice_whitelist_defaults：仅当后端明确给出该字段时合并
        if (incoming && typeof incoming.voice_whitelist_defaults === 'object'
            && incoming.voice_whitelist_defaults !== null) {
            this.config.voice_whitelist_defaults = {
                ...incoming.voice_whitelist_defaults,
            };
        }
        this.updateControlState();
        this.updateReplayButtonStates();
    }

    isAvailable() {
        return Boolean(this.config?.enabled);
    }

    updateControlState() {
        if (!this.toggles || this.toggles.length === 0) return;

        const available = this.isAvailable();
        if (!available) {
            this.autoEnabled = false;
        }

        this.toggles.forEach((toggle) => {
            toggle.disabled = !available;
            toggle.checked = this.autoEnabled && available;
        });

        this.panels.forEach((panel) => {
            panel.classList.toggle('is-disabled', !available);
            panel.classList.toggle('is-active', this.autoEnabled && available);
        });

        // 兼容旧选择器：若有不在 panel 内的 voice-gm-control，也维护其状态
        document.querySelectorAll('.voice-gm-control').forEach((shell) => {
            if (shell.closest('[data-voice-panel]')) return;
            shell.classList.toggle('is-disabled', !available);
            shell.classList.toggle('is-active', this.autoEnabled && available);
        });

        this.statuses.forEach((status) => {
            status.textContent = available
                ? (this.autoEnabled ? '语音GM 已开启' : '语音GM')
                : '语音GM 未配置';
        });

        this.applyVolumeToControls();
    }

    updateReplayButtonStates() {
        const buttons = document.querySelectorAll('.message-tts-btn');
        buttons.forEach((button) => {
            button.disabled = !this.isAvailable();
            button.title = this.isAvailable() ? '复读这条消息' : '语音GM未启用';
        });
    }

    normalizeText(text) {
        return String(text || '')
            .replace(/\s+/g, ' ')
            .replace(/^[✓✗○⚠️✅❌🎯📖⭐]+\s*/u, '')
            .trim();
    }

    // ========== 白名单 / 调试持久化 ==========
    loadWhitelistOverrides() {
        try {
            const raw = window.localStorage?.getItem(TTS_WHITELIST_STORAGE_KEY);
            if (!raw) return {};
            const parsed = JSON.parse(raw);
            if (parsed && typeof parsed === 'object') {
                return parsed;
            }
        } catch (error) {
            console.warn('[TTSManager] Failed to read whitelist overrides:', error);
        }
        return {};
    }

    persistWhitelistOverrides() {
        try {
            window.localStorage?.setItem(
                TTS_WHITELIST_STORAGE_KEY,
                JSON.stringify(this.whitelistOverrides || {})
            );
        } catch (error) {
            console.warn('[TTSManager] Failed to persist whitelist overrides:', error);
        }
    }

    loadDebugFlag() {
        try {
            return window.localStorage?.getItem(TTS_DEBUG_STORAGE_KEY) === '1';
        } catch (error) {
            return false;
        }
    }

    setDebugDecisions(enabled) {
        this.debugDecisions = Boolean(enabled);
        try {
            window.localStorage?.setItem(TTS_DEBUG_STORAGE_KEY, this.debugDecisions ? '1' : '0');
        } catch (error) {
            // ignore
        }
    }

    // ========== 服务端 / 用户白名单合并 ==========
    isCategoryEnabled(category) {
        if (!category || !TTS_VOICE_CATEGORIES[category]) return false;
        const userOverride = this.whitelistOverrides?.[category];
        if (userOverride === true || userOverride === false) return userOverride;
        const serverDefaults = this.config?.voice_whitelist_defaults;
        if (serverDefaults && Object.prototype.hasOwnProperty.call(serverDefaults, category)) {
            return Boolean(serverDefaults[category]);
        }
        return TTS_VOICE_CATEGORIES[category].readByDefault;
    }

    setCategoryEnabled(category, enabled) {
        if (!TTS_VOICE_CATEGORIES[category]) return;
        if (!this.whitelistOverrides) this.whitelistOverrides = {};
        this.whitelistOverrides[category] = Boolean(enabled);
        this.persistWhitelistOverrides();
        this.notifyWhitelistChange();
    }

    resetCategory(category) {
        if (!this.whitelistOverrides) return;
        if (Object.prototype.hasOwnProperty.call(this.whitelistOverrides, category)) {
            delete this.whitelistOverrides[category];
            this.persistWhitelistOverrides();
            this.notifyWhitelistChange();
        }
    }

    resetAllWhitelist() {
        this.whitelistOverrides = {};
        this.persistWhitelistOverrides();
        this.notifyWhitelistChange();
    }

    getWhitelistSnapshot() {
        const snapshot = {};
        Object.keys(TTS_VOICE_CATEGORIES).forEach((key) => {
            const def = TTS_VOICE_CATEGORIES[key];
            const userOverride = this.whitelistOverrides?.[key];
            const serverDefaults = this.config?.voice_whitelist_defaults || {};
            snapshot[key] = {
                label: def.label,
                description: def.description,
                priority: def.priority,
                defaultEnabled: def.readByDefault,
                serverDefault: Object.prototype.hasOwnProperty.call(serverDefaults, key)
                    ? Boolean(serverDefaults[key])
                    : null,
                userOverride: userOverride === undefined ? null : Boolean(userOverride),
                effective: this.isCategoryEnabled(key),
            };
        });
        return snapshot;
    }

    notifyWhitelistChange() {
        try {
            window.dispatchEvent(new CustomEvent('tts:whitelist-change', {
                detail: this.getWhitelistSnapshot(),
            }));
        } catch (error) {
            // ignore
        }
        this.updateReplayButtonStates();
    }

    // ========== 决策记录 ==========
    recordDecision(record) {
        if (!record) return;
        const entry = {
            timestamp: Date.now(),
            ...record,
        };
        this.decisionHistory.push(entry);
        if (this.decisionHistory.length > TTS_DECISION_HISTORY_LIMIT) {
            this.decisionHistory.shift();
        }
        this.decisionStats.total += 1;
        if (entry.spoken) {
            this.decisionStats.spoken += 1;
        } else {
            this.decisionStats.blocked += 1;
        }
        const cat = entry.voiceCategory || 'unknown';
        this.decisionStats.byCategory[cat] = (this.decisionStats.byCategory[cat] || 0) + 1;

        if (this.debugDecisions) {
            const tag = entry.spoken ? '%c[TTS ✓ 朗读]' : '%c[TTS ✗ 跳过]';
            const style = entry.spoken
                ? 'color:#23d18b;font-weight:bold'
                : 'color:#cc7a7a;font-weight:bold';
            console.debug(
                `${tag} %c[${entry.voiceCategory || '-'}] %c${entry.reason || ''} %c→ ${entry.preview || ''}`,
                style,
                'color:#7aa3ff;font-weight:bold',
                'color:#999',
                'color:inherit'
            );
        }
    }

    getDecisionHistory() {
        return [...this.decisionHistory];
    }

    getDecisionStats() {
        return JSON.parse(JSON.stringify(this.decisionStats));
    }

    // ========== 消息分类 ==========
    /**
     * 根据原始 type + 文本特征，将消息归入精确的 voice_category。
     * 返回 null 表示拒绝朗读（命中硬黑名单）。
     */
    classifyMessage(text, rawType = 'system') {
        const normalized = this.normalizeText(text);
        if (!normalized) {
            return { voiceCategory: null, reason: 'empty', length: 0 };
        }
        if (normalized.length > Number(this.config?.max_text_chars || 800)) {
            return { voiceCategory: null, reason: 'too_long', length: normalized.length };
        }

        // 0. 通用强黑名单（永远不读）
        for (const pattern of TTS_HARD_BLACKLIST_PATTERNS) {
            if (pattern.test(normalized)) {
                return {
                    voiceCategory: null,
                    reason: 'hard_blacklist',
                    matchedPattern: String(pattern),
                    length: normalized.length,
                };
            }
        }

        // 0.5. 软模板识别（归入 action/combat_summary/status，由用户白名单决定是否读）
        for (const rule of TTS_SOFT_TEMPLATE_PATTERNS) {
            if (rule.regex.test(normalized)) {
                return {
                    voiceCategory: rule.voiceCategory,
                    reason: 'soft_template',
                    matchedPattern: String(rule.regex),
                    length: normalized.length,
                };
            }
        }

        const length = normalized.length;
        const type = String(rawType || 'system').toLowerCase();

        // 1. 直接映射的强叙事类型
        if (type === 'narrative') return { voiceCategory: 'narrative', reason: 'type_mapping', length };
        if (type === 'event') return { voiceCategory: 'event', reason: 'type_mapping', length };

        // 2. choice 由 speakChoiceContext 直接 enqueue('choice')，不经过本函数

        // 3. action：默认归 action（黑名单）；只有较长且具叙事感的才升级为 narrative
        if (type === 'action') {
            if (length >= 30) {
                return { voiceCategory: 'narrative', reason: 'long_action_as_narrative', length };
            }
            return { voiceCategory: 'action', reason: 'short_action', length };
        }

        // 4. combat：区分模板 vs 叙事（短消息归 combat_summary，长消息升级为 combat_narrative）
        if (type === 'combat') {
            if (length >= 24) {
                return { voiceCategory: 'combat_narrative', reason: 'combat_long_narrative', length };
            }
            return { voiceCategory: 'combat_summary', reason: 'combat_short', length };
        }

        // 5. system：拆分为 milestone / quest / status / system_state / event
        if (type === 'system') {
            // 状态：“获得了 5 点经验 / 恢复 10 HP / 装备已穿戴”（软模板已先匹配，剩下兜底）
            if (/^(获得了?|失去了?|消耗了?|回复了?|恢复了?|得到了?|装备了?|卸下了?|穿戴了?)\s*\d/.test(normalized)) {
                return { voiceCategory: 'status', reason: 'status_template', length };
            }
            // 任务相关
            if (/(任务|目标|主线|支线)/.test(normalized) && length >= 8) {
                return { voiceCategory: 'quest', reason: 'quest_keyword', length };
            }
            // 里程碑识别（升级 / 楼梯 / 重要发现）
            if (TTS_MILESTONE_PATTERNS.some((p) => p.test(normalized))) {
                return { voiceCategory: 'milestone', reason: 'milestone_keyword', length };
            }
            // 较长系统消息往往是事件描述
            if (length >= 24 && /(发现|进入|房间|地牢|怪物|楼层|楼梯|宝藏|陷阱)/.test(normalized)) {
                return { voiceCategory: 'event', reason: 'system_long_event', length };
            }
            return { voiceCategory: 'system_state', reason: 'system_default', length };
        }

        // 6. success：除“恭喜升级”外通常是“游戏已保存/创建成功”
        if (type === 'success') {
            if (TTS_MILESTONE_PATTERNS.some((p) => p.test(normalized))) {
                return { voiceCategory: 'milestone', reason: 'success_milestone', length };
            }
            return { voiceCategory: 'system_state', reason: 'success_default', length };
        }

        // 7. error / warning / info / debug 默认黑名单
        if (type === 'error') return { voiceCategory: 'error', reason: 'type_mapping', length };
        if (type === 'warning') return { voiceCategory: 'warning', reason: 'type_mapping', length };
        if (type === 'info') return { voiceCategory: 'system_state', reason: 'info_default', length };
        if (type === 'debug') return { voiceCategory: 'debug', reason: 'type_mapping', length };

        // 8. 兜底：系统状态
        return { voiceCategory: 'system_state', reason: 'fallback', length };
    }

    // 旧 API 兼容：仅返回 TTS API 类别（narrative/event/combat/action/system/choice）
    getCategoryForType(type) {
        const mapping = {
            narrative: 'narrative',
            event: 'event',
            combat: 'combat',
            action: 'action',
            choice: 'choice',
        };
        return mapping[String(type || '').toLowerCase()] || 'system';
    }

    /**
     * 决定一条消息是否应进入 TTS 队列。
     * @returns {{shouldRead: boolean, voiceCategory: string|null, ttsCategory: string, reason: string, length: number}}
     */
    decideMessage(text, rawType = 'system', options = {}) {
        const normalized = this.normalizeText(text);
        const decision = this.classifyMessage(text, rawType);
        const voiceCategory = decision.voiceCategory;
        const length = decision.length || normalized.length;
        const isManualReplay = Boolean(options.manualReplay);

        // 命中硬黑名单 / 空 / 过长
        if (!voiceCategory) {
            return {
                shouldRead: false,
                voiceCategory: null,
                ttsCategory: 'system',
                reason: decision.reason || 'rejected',
                length,
                preview: normalized.slice(0, 36),
            };
        }

        const def = TTS_VOICE_CATEGORIES[voiceCategory];
        const ttsCategory = def?.ttsCategory || 'system';
        const enabled = this.isCategoryEnabled(voiceCategory);

        // 长度门槛
        const minLength = Math.max(4, Number(def?.minLength || 0));
        if (length < minLength) {
            return {
                shouldRead: false,
                voiceCategory,
                ttsCategory,
                reason: `below_min_length(${length}<${minLength})`,
                length,
                preview: normalized.slice(0, 36),
            };
        }

        // 用户在白名单中关闭该分类（手动复读除外）
        if (!enabled && !isManualReplay) {
            return {
                shouldRead: false,
                voiceCategory,
                ttsCategory,
                reason: 'whitelist_disabled',
                length,
                preview: normalized.slice(0, 36),
            };
        }

        return {
            shouldRead: true,
            voiceCategory,
            ttsCategory,
            reason: decision.reason || 'allow',
            length,
            preview: normalized.slice(0, 36),
        };
    }

    isMessageReadable(text, type = 'system') {
        // 兼容旧调用（addMessage 用于决定是否显示复读按钮）。
        // 复读按钮即使分类被关闭也应可点击 -> 用 manualReplay=true。
        const decision = this.decideMessage(text, type, { manualReplay: true });
        return decision.shouldRead;
    }

    speakFromMessage(text, type = 'system') {
        if (!this.autoEnabled || !this.isAvailable()) {
            return;
        }
        const decision = this.decideMessage(text, type, { manualReplay: false });
        const normalized = this.normalizeText(text);

        if (!decision.shouldRead) {
            this.recordDecision({
                ...decision,
                rawType: type,
                spoken: false,
                source: 'auto',
            });
            return;
        }

        const ttsCategory = decision.ttsCategory;
        const autoKey = `${ttsCategory}:${normalized}`;
        if (autoKey === this.lastAutoKey) {
            this.recordDecision({
                ...decision,
                rawType: type,
                spoken: false,
                source: 'auto',
                reason: 'duplicate',
            });
            return;
        }
        this.lastAutoKey = autoKey;

        this.recordDecision({
            ...decision,
            rawType: type,
            spoken: true,
            source: 'auto',
        });

        this.enqueue({
            text: normalized,
            category: ttsCategory,
            immediate: false,
        });
    }

    prefetchMessage(text, type = 'system', categoryOverride = null) {
        if (!this.autoEnabled || !this.isAvailable()) return Promise.resolve(null);
        const decision = this.decideMessage(text, type, { manualReplay: false });
        const normalized = this.normalizeText(text);
        if (!normalized) return Promise.resolve(null);
        // 防御性：仅当当前决策允许朗读时才花费 TTS 合成额度。
        // 命中硬黑名单 / 白名单关闭 / 长度门槛不达标 一律拒绝预热。
        if (!decision.shouldRead) {
            this.recordDecision({
                ...decision,
                rawType: type,
                spoken: false,
                source: 'prefetch',
            });
            return Promise.resolve(null);
        }
        const category = categoryOverride || decision.ttsCategory || this.getCategoryForType(type);
        return this.getAudioUrl(normalized, category).catch((error) => {
            console.warn('[TTSManager] Speech prefetch skipped:', error);
            return null;
        });
    }

    prepareOpeningSegments(segments = []) {
        if (!this.autoEnabled || !this.isAvailable() || !Array.isArray(segments)) {
            return;
        }

        const prepared = segments
            .map((segment) => ({
                text: this.normalizeText(segment?.text),
                category: segment?.category || 'narrative',
            }))
            .filter((segment) => segment.text);

        if (prepared.length === 0) return;

        // 开场片段属于 GM 设定的"必须预热"，绕过白名单（白名单仅控制运行时自动朗读）。
        prepared.forEach((segment) => {
            this.getAudioUrl(segment.text, segment.category).catch((error) => {
                console.warn('[TTSManager] Opening speech prefetch skipped:', error);
            });
        });

        prepared.forEach((segment) => {
            this.recordDecision({
                voiceCategory: segment.category === 'event' ? 'event' : 'narrative',
                ttsCategory: segment.category,
                rawType: segment.category,
                source: 'opening',
                spoken: true,
                reason: 'opening_segment',
                length: segment.text.length,
                preview: segment.text.slice(0, 36),
            });
            this.enqueue({
                text: segment.text,
                category: segment.category,
                immediate: false,
            });
        });
    }

    replayMessage(text, type = 'system') {
        if (!this.isAvailable()) {
            this.flashUnavailable();
            return;
        }

        // 复读 = 用户显式请求，跳过白名单开关；仅尊重硬黑名单与长度限制。
        const decision = this.decideMessage(text, type, { manualReplay: true });
        if (!decision.shouldRead) {
            this.recordDecision({
                ...decision,
                rawType: type,
                spoken: false,
                source: 'replay',
            });
            return;
        }

        this.recordDecision({
            ...decision,
            rawType: type,
            spoken: true,
            source: 'replay',
        });

        this.enqueue({
            text: this.normalizeText(text),
            category: decision.ttsCategory,
            immediate: true,
        });
    }

    speakChoiceContext(choiceContext) {
        if (!this.autoEnabled || !this.isAvailable() || !choiceContext) return;
        // choice 直接受 voice_category=choice 控制
        if (!this.isCategoryEnabled('choice')) {
            this.recordDecision({
                voiceCategory: 'choice',
                ttsCategory: 'choice',
                rawType: 'choice',
                source: 'choice',
                spoken: false,
                reason: 'whitelist_disabled',
                length: 0,
                preview: '(choice context)',
            });
            return;
        }

        const pieces = [];
        if (choiceContext.title) pieces.push(choiceContext.title);
        if (choiceContext.description) pieces.push(choiceContext.description);

        const choices = Array.isArray(choiceContext.choices) ? choiceContext.choices : [];
        const availableChoices = choices
            .filter((choice) => choice && choice.is_available !== false)
            .slice(0, 4)
            .map((choice, index) => `${index + 1}. ${choice.text || ''}${choice.description ? `，${choice.description}` : ''}`);

        if (availableChoices.length > 0) {
            pieces.push(`可选行动：${availableChoices.join('；')}`);
        }

        const text = this.normalizeText(pieces.join('。'));
        if (!text) return;

        this.recordDecision({
            voiceCategory: 'choice',
            ttsCategory: 'choice',
            rawType: 'choice',
            source: 'choice',
            spoken: true,
            reason: 'choice_context',
            length: text.length,
            preview: text.slice(0, 36),
        });
        this.enqueue({ text, category: 'choice', immediate: false });
    }

    buildCacheKey(text, category) {
        const voice = this.config?.default_voice || 'mimo_default';
        const model = this.config?.model_name || 'mimo-v2.5-tts';
        const format = this.config?.output_format || 'wav';
        return [model, voice, format, category, this.normalizeText(text)].join('|');
    }

    enqueue(item) {
        if (!item?.text) return;
        const key = this.buildCacheKey(item.text, item.category);

        if (item.immediate) {
            this.stop();
            this.queuedKeys.delete(key);
            this.queue.unshift(item);
        } else {
            if (this.queuedKeys.has(key) || this.currentQueueKey === key) {
                return;
            }
            this.queuedKeys.add(key);
            this.queue.push(item);
        }

        this.processQueue();
    }

    async processQueue() {
        if (this.isPlaying || this.queue.length === 0) return;

        const item = this.queue.shift();
        const key = this.buildCacheKey(item.text, item.category);
        this.queuedKeys.delete(key);
        this.currentQueueKey = key;
        this.isPlaying = true;

        try {
            const url = await this.getAudioUrl(item.text, item.category);
            await this.playUrl(url);
        } catch (error) {
            console.warn('[TTSManager] Speech playback skipped:', error);
        } finally {
            this.isPlaying = false;
            this.currentQueueKey = '';
            if (this.queue.length > 0) {
                setTimeout(() => this.processQueue(), 80);
            }
        }
    }

    async getAudioUrl(text, category) {
        const key = this.buildCacheKey(text, category);
        if (this.audioCache.has(key)) {
            return this.audioCache.get(key);
        }
        if (this.audioPromises.has(key)) {
            return this.audioPromises.get(key);
        }

        const promise = fetch('/api/tts/synthesize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                text,
                category,
                voice: this.config?.default_voice || undefined
            })
        }).then(async (response) => {
            if (!response.ok) {
                throw new Error(`TTS request failed: ${response.status}`);
            }

            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            this.audioCache.set(key, url);
            return url;
        }).finally(() => {
            this.audioPromises.delete(key);
        });

        this.audioPromises.set(key, promise);
        return promise;
    }

    playUrl(url) {
        return new Promise((resolve, reject) => {
            const audio = new Audio(url);
            audio.volume = this.getEffectiveVolume();
            this.currentAudio = audio;
            audio.onended = () => resolve();
            audio.onerror = () => reject(new Error('audio playback failed'));
            audio.play().catch(reject);
        });
    }

    stop() {
        if (this.currentAudio) {
            this.currentAudio.pause();
            this.currentAudio.currentTime = 0;
            this.currentAudio = null;
        }
        this.isPlaying = false;
    }

    flashUnavailable() {
        const targets = (this.panels && this.panels.length > 0)
            ? this.panels
            : (this.shells || []);
        if (!targets || targets.length === 0) return;
        targets.forEach((shell) => shell.classList.add('is-unavailable-pulse'));
        setTimeout(() => {
            targets.forEach((shell) => shell.classList.remove('is-unavailable-pulse'));
        }, 600);
    }
}

window.TTSManager = TTSManager;
window.TTS_VOICE_CATEGORIES = TTS_VOICE_CATEGORIES;
