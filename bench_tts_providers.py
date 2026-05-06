"""TTS Provider 真实性能基准

用相同的 3 段叙事文本（短/中/长）分别跑 mimo_openai_compatible 与 qwen_gradio
两个 provider，每段 2 次合成（取最小 latency 避免网络抖动），输出同维度对比表。

注意：
- 直接读 .env 中的真实 TTS_* 配置；如果 mimo 那条链路在你的环境里没配 key，
  脚本会跳过 mimo 段并继续跑 qwen 段。
- 不会打印任何 api_key 内容。
- 输出仅包含耗时、字节数、ms/char 等可发布指标。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

import config
import tts_gateway
import qwen_tts_adapter  # noqa: F401  注册 qwen_gradio


TEXTS: List[Tuple[str, str]] = [
    (
        "short_23",
        "地牢深处传来低沉回响，第一缕微光照亮了石阶。",
    ),
    (
        "medium_56",
        "你站在十字路口，左侧通道渗出蓝色雾气，右侧传来金属敲击的回响。"
        "你的手悄悄按上了剑柄，决意先观察片刻。",
    ),
    (
        "long_110",
        "破旧石门前的火炬剧烈摇曳，墙壁上的符文随着血色月光微微显形，"
        "似乎在低声吟唱古老的咒语。空气中弥漫着潮湿的霉味与铁锈交织的气息，"
        "远处偶尔传来不属于活物的拖曳声。你深吸一口气，握紧手中的长剑，"
        "决定推开这扇门。",
    ),
]


def _bench_provider(provider_name: str, runs: int = 2) -> Dict[str, Dict[str, float]]:
    print(f"\n===== {provider_name} =====")

    saved = {
        "provider": config.config.tts.provider,
        "base_url": config.config.tts.base_url,
        "default_voice": config.config.tts.default_voice,
        "model_name": config.config.tts.model_name,
        "api_key": config.config.tts.api_key,
    }

    try:
        config.config.tts.enabled = True
        config.config.tts.provider = provider_name
        if provider_name == "qwen_gradio":
            config.config.tts.base_url = "https://qwen-qwen3-tts-demo.ms.show"
            config.config.tts.default_voice = "vivian"
            # qwen 不要求 api_key/model_name；保持其他字段为空也无所谓
        # mimo 沿用 .env 中的真实配置

        try:
            warmup_provider = tts_gateway.TTSGateway.get_provider()
        except ValueError as exc:
            print(f"  跳过：provider 配置缺失 ({exc})")
            return {}

        # warm-up：一次空合成（catch network init / catalog refresh 开销）
        try:
            t0 = time.time()
            warmup_provider.synthesize(
                "测试一句话。",
                voice=None,
                response_format="wav",
            )
            dt = time.time() - t0
            print(f"  warm-up 合成耗时: {dt:.2f}s")
        except Exception as exc:
            print(f"  warm-up 失败: {str(exc)[:160]}")

        results: Dict[str, Dict[str, float]] = {}
        for label, text in TEXTS:
            char_count = len(text)
            timings: List[float] = []
            sizes: List[int] = []

            for run_idx in range(runs):
                provider = tts_gateway.TTSGateway.get_provider()
                t0 = time.time()
                try:
                    audio_bytes, voice = provider.synthesize(
                        text,
                        voice=None,
                        response_format="wav",
                    )
                    dt = time.time() - t0
                    timings.append(dt)
                    sizes.append(len(audio_bytes))
                    print(
                        f"  [{label}] run {run_idx + 1}: {dt:.2f}s, "
                        f"{len(audio_bytes)} bytes, voice={voice}"
                    )
                except Exception as exc:
                    print(f"  [{label}] run {run_idx + 1} FAILED: {str(exc)[:160]}")

            if timings:
                avg_t = sum(timings) / len(timings)
                min_t = min(timings)
                avg_s = sum(sizes) / len(sizes)
                ms_per_char = (avg_t * 1000) / char_count
                results[label] = {
                    "chars": char_count,
                    "avg_s": avg_t,
                    "min_s": min_t,
                    "avg_bytes": avg_s,
                    "ms_per_char": ms_per_char,
                }
                print(
                    f"  [{label}] {char_count} chars: avg={avg_t:.2f}s "
                    f"min={min_t:.2f}s avg_bytes={avg_s:.0f} ms/char={ms_per_char:.1f}"
                )

        return results
    finally:
        for key, value in saved.items():
            setattr(config.config.tts, key, value)


def _format_compare(
    mimo: Dict[str, Dict[str, float]],
    qwen: Dict[str, Dict[str, float]],
) -> None:
    print("\n" + "=" * 78)
    print("性能对比")
    print("=" * 78)
    header = f"{'label':<14}{'chars':<8}{'mimo avg':<14}{'qwen avg':<14}{'qwen/mimo':<10}"
    print(header)
    print("-" * 78)
    for label, _ in TEXTS:
        m = mimo.get(label)
        q = qwen.get(label)
        if not m and not q:
            print(f"{label:<14}{'-':<8}{'-':<14}{'-':<14}{'-':<10}")
            continue
        chars = (m or q).get("chars", 0)
        m_avg = f"{m['avg_s']:.2f}s" if m else "-"
        q_avg = f"{q['avg_s']:.2f}s" if q else "-"
        ratio = f"{q['avg_s'] / m['avg_s']:.2f}x" if (m and q) else "-"
        print(f"{label:<14}{int(chars):<8}{m_avg:<14}{q_avg:<14}{ratio:<10}")

    print("\n" + "-" * 78)
    print("ms/char 对比（越低越快）")
    print("-" * 78)
    for label, _ in TEXTS:
        m = mimo.get(label)
        q = qwen.get(label)
        m_mc = f"{m['ms_per_char']:.1f}" if m else "-"
        q_mc = f"{q['ms_per_char']:.1f}" if q else "-"
        print(f"  {label:<14} mimo={m_mc:<10} qwen={q_mc:<10}")


def main() -> int:
    mimo_results = _bench_provider("mimo_openai_compatible", runs=2)
    qwen_results = _bench_provider("qwen_gradio", runs=2)
    _format_compare(mimo_results, qwen_results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
