/**
 * Labyrinthia AI - TTS 白名单回归测试
 *
 * 用法: node tests/test_tts_whitelist.js
 *
 * 该脚本不依赖浏览器，自行 mock 出 window/localStorage 后引入 TTSManager.js
 * 然后断言关键消息的 voice_category 与 shouldRead 决策。
 */

'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

// ----- 构造一个最小的浏览器 sandbox -----
const memoryStorage = (() => {
    const map = new Map();
    return {
        getItem(k) { return map.has(k) ? map.get(k) : null; },
        setItem(k, v) { map.set(k, String(v)); },
        removeItem(k) { map.delete(k); },
        clear() { map.clear(); },
    };
})();

const sandbox = {
    console,
    setTimeout,
    clearTimeout,
    URL: { createObjectURL: () => 'blob://test' },
    document: {
        querySelectorAll: () => [],
        getElementById: () => null,
        addEventListener: () => {},
    },
    window: {
        localStorage: memoryStorage,
        dispatchEvent: () => {},
        addEventListener: () => {},
        CustomEvent: function (name, opts) { this.type = name; this.detail = opts?.detail; },
    },
};
sandbox.window.document = sandbox.document;
vm.createContext(sandbox);

const ttsManagerSource = fs.readFileSync(
    path.resolve(__dirname, '..', 'static', 'TTSManager.js'),
    'utf8'
);
vm.runInContext(ttsManagerSource, sandbox);

const TTSManager = sandbox.window.TTSManager;
if (typeof TTSManager !== 'function') {
    throw new Error('TTSManager not exported on window');
}

// ----- 测试装置 -----
const tts = new TTSManager({});
tts.config = { ...tts.config, enabled: true, max_text_chars: 800, voice_whitelist_defaults: null };
tts.autoEnabled = true;

let pass = 0;
let fail = 0;
const failures = [];

function expect(label, decision, expectations) {
    const errors = [];
    Object.entries(expectations).forEach(([key, expected]) => {
        const actual = decision[key];
        if (actual !== expected) {
            errors.push(`  ${key}: expected=${JSON.stringify(expected)} actual=${JSON.stringify(actual)}`);
        }
    });
    if (errors.length === 0) {
        pass += 1;
        process.stdout.write(`  \x1b[32m✓\x1b[0m ${label}\n`);
    } else {
        fail += 1;
        failures.push({ label, errors, decision });
        process.stdout.write(`  \x1b[31m✗\x1b[0m ${label}\n`);
        errors.forEach((e) => process.stdout.write(`${e}\n`));
    }
}

function decide(text, type, opts) {
    return tts.decideMessage(text, type, opts || {});
}

console.log('\n=== 默认（均衡）白名单 ===');

// 应朗读：长叙事
expect('长叙事 narrative 应朗读', decide('你穿过潮湿的石廊，看见远处烛火摇曳。古老的回声从墙壁渗出。', 'narrative'), {
    shouldRead: true,
    voiceCategory: 'narrative',
});

// 应朗读：事件
expect('事件 event 应朗读', decide('一阵阴风吹过，墙上的浮雕睁开了眼睛。', 'event'), {
    shouldRead: true,
    voiceCategory: 'event',
});

// 应朗读：长 LLM 战斗叙事
expect('长战斗叙事 combat 应朗读', decide('你侧身闪过哥布林的劈砍，借势挥剑砍中它的肩膀，鲜血飞溅。', 'combat'), {
    shouldRead: true,
    voiceCategory: 'combat_narrative',
});

// 应朗读：升级
expect('升级 success 升级里程碑', decide('恭喜升级！', 'success'), {
    shouldRead: true,
    voiceCategory: 'milestone',
});

// 应朗读：发现楼梯
expect('系统：发现楼梯', decide('你发现了通往下一层的楼梯。你可以选择进入下一层。', 'system'), {
    shouldRead: true,
    voiceCategory: 'milestone',
});

console.log('\n=== 默认应被静音的模板消息（核心需求） ===');

// 不应朗读：移动模板
expect('移动到 (x,y) 不读', decide('移动到 (3, 5)', 'action'), { shouldRead: false });

// 不应朗读：攻击模板（action）
expect('攻击了 怪物 不读', decide('攻击了 哥布林', 'action'), { shouldRead: false });

// 不应朗读：怪物攻击你模板（combat）
expect('哥布林攻击了你 不读', decide('哥布林 攻击了你，造成 5 点伤害！', 'combat'), { shouldRead: false });

// 不应朗读：被击败模板
expect('哥布林 被击败了 不读', decide('哥布林 被击败了！', 'combat'), { shouldRead: false });

// 不应朗读：经验
expect('获得 5 点经验 不读', decide('获得了 5 点经验', 'system'), { shouldRead: false });

// 不应朗读：保存提示
expect('游戏已保存 不读', decide('游戏已保存', 'success'), { shouldRead: false });

// 不应朗读：错误提示
expect('网络错误 不读', decide('网络错误，请重试', 'error'), { shouldRead: false });
expect('无法穿过墙壁 不读', decide('无法穿过墙壁', 'error'), { shouldRead: false });
expect('目标距离太远 不读', decide('目标距离太远，无法攻击', 'error'), { shouldRead: false });

// 不应朗读：调试 emoji
expect('调试 emoji 输出 不读', decide('🎲 已触发随机事件', 'system'), { shouldRead: false });
expect('错误调试 输出 不读', decide('❌ 请先开始游戏', 'system'), { shouldRead: false });

// 不应朗读：状态
expect('对 怪物 造成 N 伤害 不读', decide('对 哥布林 造成了 7 点伤害', 'combat'), { shouldRead: false });

console.log('\n=== 用户白名单覆盖：开启战斗模板后允许朗读 ===');
tts.setCategoryEnabled('combat_summary', true);
expect('开启 combat_summary 后 哥布林被击败 应朗读', decide('哥布林 被击败了！', 'combat'), {
    shouldRead: true,
    voiceCategory: 'combat_summary',
});
tts.resetCategory('combat_summary');

console.log('\n=== 手动复读（manualReplay 跳过白名单开关，仅尊重硬黑名单） ===');
expect('replay action 模板：手动复读时应允许朗读（软分类不阻止）',
    decide('攻击了 哥布林', 'action', { manualReplay: true }),
    { shouldRead: true, voiceCategory: 'action' });

expect('replay 硬黑名单：手动复读也无法朗读纯坐标',
    decide('移动到 (3, 5)', 'action', { manualReplay: true }),
    { shouldRead: false });

expect('replay 长叙事：手动复读应通过',
    decide('你穿过潮湿的石廊，看见远处烛火摇曳。', 'narrative', { manualReplay: true }),
    { shouldRead: true });

console.log('\n=== 长度门槛 ===');
expect('过短叙事 长度 < 8 拒绝', decide('好。', 'narrative'), { shouldRead: false });
expect('过短战斗叙事 < 30 应归 combat_summary 默认不读',
    decide('你击中。', 'combat'), { shouldRead: false, voiceCategory: 'combat_summary' });

console.log('\n=== 决策记录与统计 ===');
const stats = tts.getDecisionStats();
console.log(`  累计 total=${stats.total} spoken=${stats.spoken} blocked=${stats.blocked}`);
console.log(`  分类分布: ${JSON.stringify(stats.byCategory)}`);

console.log('\n========================================');
console.log(`测试结果: ${pass} 通过 / ${fail} 失败`);
if (fail > 0) {
    console.log('\n失败详情:');
    failures.forEach((f) => {
        console.log(`  - ${f.label}`);
        console.log(`    decision: ${JSON.stringify(f.decision)}`);
    });
    process.exit(1);
}
console.log('全部通过 ✅');
