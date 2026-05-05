/**
 * Labyrinthia AI - Voice whitelist settings panel
 *
 * 负责:
 *   1. 把 TTSManager 暴露的 voice category 渲染成可勾选清单
 *   2. 用户切换时回写到 TTSManager.setCategoryEnabled
 *   3. 显示当前会话决策统计 + 调试日志开关
 *   4. 点击 voice-gm-settings-btn 打开/关闭面板
 *
 * 浮层 HTML 已在 templates/index.html 内提供，本脚本只负责行为逻辑。
 */

(function () {
    'use strict';

    const MODAL_ID = 'voice-whitelist-modal';
    const LIST_ID = 'voice-whitelist-list';
    const STATS_ID = 'voice-whitelist-stats';
    const DEBUG_TOGGLE_ID = 'voice-whitelist-debug-toggle';
    const RESET_BTN_ID = 'voice-whitelist-reset';
    const TRIGGER_BTN_ID = 'voice-gm-settings-btn';

    function getTTSManager() {
        return window.game?.ttsManager || null;
    }

    function ensureModalReady() {
        const modal = document.getElementById(MODAL_ID);
        if (!modal) return null;
        if (modal.dataset.bound === '1') return modal;
        modal.dataset.bound = '1';

        modal.querySelectorAll('[data-voice-close]').forEach((el) => {
            el.addEventListener('click', (event) => {
                event.preventDefault();
                hideModal();
            });
        });

        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && !modal.hidden) {
                hideModal();
            }
        });

        const resetBtn = modal.querySelector(`#${RESET_BTN_ID}`);
        if (resetBtn) {
            resetBtn.addEventListener('click', () => {
                const tts = getTTSManager();
                if (!tts) return;
                tts.resetAllWhitelist();
                renderList();
            });
        }

        const debugToggle = modal.querySelector(`#${DEBUG_TOGGLE_ID}`);
        if (debugToggle) {
            debugToggle.addEventListener('change', (event) => {
                const tts = getTTSManager();
                if (!tts) return;
                tts.setDebugDecisions(Boolean(event.target.checked));
            });
        }

        return modal;
    }

    function showModal() {
        const modal = ensureModalReady();
        if (!modal) return;
        renderList();
        modal.hidden = false;
        document.body.classList.add('voice-whitelist-open');
    }

    function hideModal() {
        const modal = document.getElementById(MODAL_ID);
        if (!modal) return;
        modal.hidden = true;
        document.body.classList.remove('voice-whitelist-open');
    }

    function renderList() {
        const tts = getTTSManager();
        const list = document.getElementById(LIST_ID);
        const debugToggle = document.getElementById(DEBUG_TOGGLE_ID);
        const stats = document.getElementById(STATS_ID);
        if (!list) return;
        list.innerHTML = '';
        if (!tts) {
            list.innerHTML = '<p class="voice-whitelist-empty">语音 GM 未初始化。</p>';
            return;
        }

        const snapshot = tts.getWhitelistSnapshot();
        const entries = Object.entries(snapshot)
            .sort((a, b) => (b[1].priority || 0) - (a[1].priority || 0));

        entries.forEach(([key, info]) => {
            const row = document.createElement('label');
            row.className = 'voice-whitelist-row';
            row.dataset.category = key;

            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.checked = Boolean(info.effective);
            checkbox.addEventListener('change', () => {
                tts.setCategoryEnabled(key, checkbox.checked);
                renderList();
            });

            const text = document.createElement('div');
            text.className = 'voice-whitelist-row-text';

            const title = document.createElement('div');
            title.className = 'voice-whitelist-row-title';
            title.textContent = info.label;

            // 状态标签：默认 / 服务端 / 用户覆盖
            const tag = document.createElement('span');
            tag.className = 'voice-whitelist-row-tag';
            if (info.userOverride !== null) {
                tag.classList.add(info.userOverride ? 'is-on' : 'is-off');
                tag.textContent = info.userOverride ? '用户开启' : '用户关闭';
            } else if (info.serverDefault !== null && info.serverDefault !== info.defaultEnabled) {
                tag.classList.add('is-server');
                tag.textContent = info.serverDefault ? '服务端开启' : '服务端关闭';
            } else {
                tag.classList.add(info.defaultEnabled ? 'is-default-on' : 'is-default-off');
                tag.textContent = info.defaultEnabled ? '默认朗读' : '默认静音';
            }
            title.appendChild(tag);

            const desc = document.createElement('div');
            desc.className = 'voice-whitelist-row-desc';
            desc.textContent = info.description;

            text.appendChild(title);
            text.appendChild(desc);

            row.appendChild(checkbox);
            row.appendChild(text);
            list.appendChild(row);
        });

        if (debugToggle) {
            debugToggle.checked = Boolean(tts.debugDecisions);
        }

        if (stats) {
            const summary = tts.getDecisionStats();
            stats.querySelectorAll('[data-stat]').forEach((el) => {
                const key = el.getAttribute('data-stat');
                el.textContent = String(summary[key] ?? 0);
            });
        }
    }

    function bindTrigger() {
        const trigger = document.getElementById(TRIGGER_BTN_ID);
        if (!trigger) {
            // 此处不立即重试，避免无限轮询；GameCore 加载完后会触发 voice setup 一并出现
            return false;
        }
        if (trigger.dataset.bound === '1') return true;
        trigger.dataset.bound = '1';
        trigger.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            showModal();
        });
        return true;
    }

    function init() {
        bindTrigger();
        ensureModalReady();
        // 当 TTSManager 重新初始化或后端配置返回时，刷新一次
        window.addEventListener('tts:whitelist-change', () => {
            const modal = document.getElementById(MODAL_ID);
            if (modal && !modal.hidden) renderList();
        });

        // GameCore 在 setupControls 时可能延迟挂载按钮，做一次 250ms 复试
        if (!bindTrigger()) {
            setTimeout(() => bindTrigger(), 300);
            setTimeout(() => bindTrigger(), 1500);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.VoiceWhitelistPanel = { show: showModal, hide: hideModal, render: renderList };
})();
