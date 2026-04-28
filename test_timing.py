#!/usr/bin/env python3
"""
测试视频下载 + Whisper 转录的完整流程耗时
"""

import time
import json
import requests
from datetime import timedelta

BASE_URL = "http://localhost:8000"
VIDEO_URL = "https://www.youtube.com/watch?v=dvt_74kV-RM"


def print_section(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


def test_workflow():
    total_start = time.time()
    timings = {}

    # 1. 检查视频信息
    print_section("1. 视频信息检查")
    start = time.time()
    try:
        resp = requests.post(
            f"{BASE_URL}/api/video/inspect", json={"url": VIDEO_URL}, timeout=30
        )
        timings["inspect"] = time.time() - start
        print(f"   耗时: {timings['inspect']:.2f} 秒")
        print(f"   状态: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"   视频标题: {data.get('title', 'N/A')}")
            print(f"   时长: {data.get('duration_sec', 'N/A')} 秒")
            print(f"   是否有字幕: {data.get('subtitles', [])}")
    except Exception as e:
        print(f"   错误: {e}")
        timings["inspect"] = time.time() - start

    # 2. 强制下载音频
    print_section("2. 音频下载 (force_audio 模式)")
    start = time.time()
    audio_path = None
    try:
        resp = requests.post(
            f"{BASE_URL}/api/video/fetch-source",
            json={"url": VIDEO_URL, "source_mode": "force_audio"},
            timeout=300,
        )
        timings["download"] = time.time() - start
        print(f"   耗时: {timings['download']:.2f} 秒")
        print(f"   状态: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            audio_path = data.get("audio_file_path")
            print(f"   音频路径: {audio_path}")
            print(f"   来源类型: {data.get('source_type')}")
    except Exception as e:
        print(f"   错误: {e}")
        timings["download"] = time.time() - start

    # 3. Whisper 转录
    if audio_path:
        print_section("3. Whisper 转录")
        start = time.time()
        try:
            resp = requests.post(
                f"{BASE_URL}/api/transcribe",
                json={"audio_file_path": audio_path},
                timeout=600,
            )
            timings["transcribe"] = time.time() - start
            print(f"   耗时: {timings['transcribe']:.2f} 秒")
            print(f"   状态: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                segments = data.get("segments", [])
                print(f"   识别段落数: {len(segments)}")
                print(f"   语言: {data.get('language', 'N/A')}")
                if segments:
                    print(f"   第一段示例: {segments[0].get('text', 'N/A')[:50]}...")
        except Exception as e:
            print(f"   错误: {e}")
            timings["transcribe"] = time.time() - start
    else:
        print_section("3. Whisper 转录")
        print("   跳过: 未获取到音频路径")
        timings["transcribe"] = 0

    # 汇总
    total_time = time.time() - total_start
    print_section("⏱️  时间汇总")
    print(f"   视频信息检查: {timings.get('inspect', 0):.2f} 秒")
    print(f"   音频下载:     {timings.get('download', 0):.2f} 秒")
    print(f"   Whisper转录:  {timings.get('transcribe', 0):.2f} 秒")
    print(f"   ─────────────────────────")
    print(
        f"   总耗时:       {total_time:.2f} 秒 ({timedelta(seconds=int(total_time))})"
    )
    print()

    return timings


if __name__ == "__main__":
    print("🎬 YouTube 视频处理流程耗时测试")
    print(f"视频URL: {VIDEO_URL}")

    # 检查后端健康
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=5)
        if resp.status_code == 200:
            print(f"✅ 后端服务正常: {resp.json()}")
        else:
            print(f"⚠️ 后端服务异常: {resp.status_code}")
            exit(1)
    except Exception as e:
        print(f"❌ 无法连接后端: {e}")
        exit(1)

    # 运行测试
    test_workflow()
