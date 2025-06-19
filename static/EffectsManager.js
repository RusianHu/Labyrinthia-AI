// Labyrinthia AI - 特效和音效模块
// 包含任务完成特效、音效播放等功能

// 扩展核心游戏类，添加特效和音效功能
Object.assign(LabyrinthiaGame.prototype, {
    
    showQuestCompletionEffect(effect) {
        // 创建任务完成特效容器
        const effectContainer = document.createElement('div');
        effectContainer.className = 'quest-completion-effect';
        effectContainer.innerHTML = `
            <div class="quest-completion-content">
                <div class="quest-completion-icon">🎉</div>
                <div class="quest-completion-title">任务完成！</div>
                <div class="quest-completion-quest-name">${effect.quest_title}</div>
                <div class="quest-completion-reward">获得 ${effect.experience_reward} 经验值</div>
                <div class="quest-completion-particles">
                    <div class="particle"></div>
                    <div class="particle"></div>
                    <div class="particle"></div>
                    <div class="particle"></div>
                    <div class="particle"></div>
                    <div class="particle"></div>
                    <div class="particle"></div>
                    <div class="particle"></div>
                </div>
            </div>
        `;

        // 添加到页面
        document.body.appendChild(effectContainer);

        // 播放音效（如果有的话）
        this.playQuestCompletionSound();

        // 自动移除特效
        setTimeout(() => {
            effectContainer.classList.add('fade-out');
            setTimeout(() => {
                if (effectContainer.parentNode) {
                    effectContainer.parentNode.removeChild(effectContainer);
                }
            }, 1000);
        }, 4000);

        // 添加消息到日志
        this.addMessage(effect.message, 'success');
    },

    playQuestCompletionSound() {
        // 可以在这里添加音效播放逻辑
        // 例如使用 Web Audio API 或者 HTML5 Audio
        try {
            // 创建一个简单的成功音效
            if (typeof AudioContext !== 'undefined') {
                const audioContext = new AudioContext();
                const oscillator = audioContext.createOscillator();
                const gainNode = audioContext.createGain();

                oscillator.connect(gainNode);
                gainNode.connect(audioContext.destination);

                oscillator.frequency.setValueAtTime(523.25, audioContext.currentTime); // C5
                oscillator.frequency.setValueAtTime(659.25, audioContext.currentTime + 0.1); // E5
                oscillator.frequency.setValueAtTime(783.99, audioContext.currentTime + 0.2); // G5

                gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
                gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.5);

                oscillator.start(audioContext.currentTime);
                oscillator.stop(audioContext.currentTime + 0.5);
            }
        } catch (error) {
            // 音效播放失败时静默处理
            console.log('Audio playback not supported or failed');
        }
    }
});
