"""qwen-tts-skill 真实调用评估脚本（仅用于研究迁移可行性，与项目主链路解耦）。

评估目标：
1. 远端 Gradio 服务可用性 / 默认音色与语言枚举
2. 单段合成耗时、音频字节大小、保存可行性
3. 与当前 main.py 的 mimo TTS 接口签名差异（输出格式、headers、缓存策略）
"""

from __future__ import annotations

import sys
import time
import os
from pathlib import Path

skill_root_env = os.getenv("QWEN_TTS_SKILL_ROOT", "").strip()
SKILL_ROOT = Path(skill_root_env).expanduser() if skill_root_env else Path("external/qwen-tts-skill")
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def main() -> int:
    if not SCRIPTS_DIR.exists():
        print(
            "[ABORT] 未找到 qwen-tts-skill scripts 目录；"
            "请设置 QWEN_TTS_SKILL_ROOT 指向外部 qwen-tts-skill 仓库。"
        )
        return 1

    from qwen_tts_skill import QwenTTSBackend  # type: ignore

    print("=" * 60)
    print("Step 1: 创建 backend，验证 upstream 与默认配置")
    print("=" * 60)
    backend = QwenTTSBackend()
    print(f"  upstream_url = {backend.upstream_url}")
    print(f"  api_name     = {backend.api_name}")

    print("\n" + "=" * 60)
    print("Step 2: refresh_catalog —— 拉取远端音色/语言枚举")
    print("=" * 60)
    t0 = time.time()
    ok = backend.refresh_catalog(force=True)
    dt = time.time() - t0
    print(f"  refresh_catalog ok = {ok}, 耗时 = {dt:.2f}s")
    print(f"  voices    数量 = {len(backend.voices)}")
    print(f"  languages 数量 = {len(backend.languages)}")
    print(f"  默认音色 = {backend.default_voice_id} -> {backend._default_voice_name!r}")
    print(f"  默认语言 = {backend.default_language_id} -> {backend._default_language_name!r}")

    sample_voices = list(backend.voices.items())[:8]
    print("  音色样本:")
    for vid, name in sample_voices:
        print(f"    - {vid}: {name}")

    sample_langs = list(backend.languages.items())[:6]
    print("  语言样本:")
    for lid, name in sample_langs:
        print(f"    - {lid}: {name}")

    if not ok or not backend.voices:
        print("\n[ABORT] 无法获取上游音色目录，后续合成测试跳过")
        return 1

    print("\n" + "=" * 60)
    print("Step 3: 真实合成短文本（模拟 Labyrinthia 开场旁白）")
    print("=" * 60)
    text = "地牢深处传来低沉回响，第一缕微光照亮了石阶。"
    t0 = time.time()
    result = backend.synthesize(text=text, voice=None, language="zh")
    dt = time.time() - t0
    print(f"  synthesize 耗时 = {dt:.2f}s")
    print(f"  result.success      = {result.success}")
    print(f"  result.voice_id     = {result.voice_id}")
    print(f"  result.language_id  = {result.language_id}")
    print(f"  result.error_message= {result.error_message}")
    if result.audio_data:
        size = len(result.audio_data)
        head = result.audio_data[:12]
        print(f"  audio_data bytes    = {size}")
        print(f"  audio header bytes  = {head!r}")
        out_path = Path("artifacts/qwen_tts_eval_zh.wav")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(result.audio_data)
        print(f"  saved to            = {out_path}")

    print("\n" + "=" * 60)
    print("Step 4: 真实合成中等长度文本（模拟事件叙述）")
    print("=" * 60)
    text2 = (
        "你站在十字路口，左侧通道渗出蓝色雾气，右侧传来金属敲击的回响。"
        "你的手悄悄按上了剑柄，决意先观察片刻。"
    )
    t0 = time.time()
    result2 = backend.synthesize(text=text2, voice=None, language="zh")
    dt2 = time.time() - t0
    print(f"  synthesize 耗时 = {dt2:.2f}s")
    print(f"  result.success      = {result2.success}")
    if result2.audio_data:
        out_path2 = Path("artifacts/qwen_tts_eval_zh_long.wav")
        out_path2.write_bytes(result2.audio_data)
        print(f"  bytes={len(result2.audio_data)} saved to {out_path2}")
    elif result2.error_message:
        print(f"  error = {result2.error_message}")

    print("\n" + "=" * 60)
    print("Step 5: 错误路径 —— 空文本 / 不存在音色 ID")
    print("=" * 60)
    empty = backend.synthesize("", voice=None, language="zh")
    print(f"  empty text   -> success={empty.success}, err={empty.error_message}")

    bad_voice = backend.synthesize("测试一句", voice="this-voice-does-not-exist", language="zh")
    print(
        f"  bogus voice  -> success={bad_voice.success}, "
        f"resolved_voice={bad_voice.voice_id}, err={bad_voice.error_message}"
    )

    print("\n[DONE]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
