# -*- coding: utf-8 -*-
"""
环境引导脚本：检查 Python 版本、pip 安装依赖、模型预下载引导。

用法：
    python scripts/setup_env.py                        # 完整安装全部阶段依赖
    python scripts/setup_env.py --stage1               # 只安装阶段一依赖（录音 + 转写）
    python scripts/setup_env.py --download-model       # 预下载 Whisper 模型（跳过安装）
"""

import argparse
import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS = os.path.join(PROJECT_ROOT, "requirements.txt")

# 阶段一依赖：录音（sounddevice）+ 转写（faster-whisper）+ 音频运算（numpy）
STAGE1_PACKAGES = ["faster-whisper", "sounddevice", "numpy"]

# faster-whisper / edge-tts / pvporcupine 官方支持范围，推荐 3.10+
MIN_PYTHON = (3, 10)

# 模型下载镜像（国内网络加速，下载失败时提示用户设置）
HF_MIRROR = "https://hf-mirror.com"


def check_python() -> None:
    """检查 Python 版本，不满足则退出。"""
    print(f"[python] {sys.version}")
    if sys.version_info < MIN_PYTHON:
        print(f"[error] Python 版本过低，需要 {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 及以上，"
              f"当前 {sys.version_info.major}.{sys.version_info.minor}")
        sys.exit(1)
    print("[python] 版本 OK")


def _pip_install(packages: list, label: str) -> None:
    """用当前解释器的 pip 安装一组包。"""
    print(f"[pip] 安装{label}依赖：{' '.join(packages)}（可能耗时几分钟）...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", *packages])
    print(f"[pip] {label}依赖安装完成")


def install_requirements() -> None:
    """安装 requirements.txt 中的全部依赖。"""
    if not os.path.exists(REQUIREMENTS):
        print(f"[error] 找不到 {REQUIREMENTS}")
        sys.exit(1)
    _pip_install(["-r", REQUIREMENTS], "全部阶段")


def install_stage1() -> None:
    """只安装阶段一依赖：faster-whisper（转写）、sounddevice（录音）、numpy。"""
    _pip_install(STAGE1_PACKAGES, "阶段一")


def download_model(model: str = "small") -> None:
    """预下载 faster-whisper 模型到本地缓存。

    原理：WhisperModel(...) 构造时若本地缓存没有该模型，会自动从
    HuggingFace（或 HF_ENDPOINT 指定的镜像）下载，因此加载一次即完成下载。
    这里用 cpu + int8 加载，只触发下载，不占用 GPU 显存。
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("[error] 未安装 faster-whisper，请先执行：python scripts/setup_env.py --stage1")
        sys.exit(1)
    print(f"[model] 开始下载模型 {model}（small 约 461MB，视网速而定，请耐心等待）...")
    try:
        WhisperModel(model, device="cpu", compute_type="int8")
    except Exception as e:
        print(f"[error] 模型下载/加载失败：{e}")
        print("若为网络问题，请先设置镜像后重试：")
        print(f"  set HF_ENDPOINT={HF_MIRROR}")
        sys.exit(1)
    print("[model] 模型就绪，缓存位置：C:\\Users\\<用户名>\\.cache\\huggingface\\hub")


def print_next_steps() -> None:
    """输出运行提示（含模型准备与镜像说明）。"""
    print(f"""
[下一步]
1. faster-whisper 模型有两种准备方式（二选一）：
   a) 自动下载：首次转写时自动从 HuggingFace 下载到本地缓存，无需手动操作；
   b) 预下载（推荐，提前确认网络）：若网络受限，先设镜像再执行
      set HF_ENDPOINT={HF_MIRROR}
      python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"
2. 确认 Hana server 已在后台启动（桌面端打开即可），
   且 C:\\Users\\<用户名>\\.hanako\\server-info.json 存在。
3. 复制配置并启动：
   copy config.example.json config.json
   run.cmd
4. 当前 TTS / 唤醒为占位实现，录音与转写（阶段一）已完成；
   按 README.md 的阶段计划逐阶段补齐。
""")


def main() -> None:
    parser = argparse.ArgumentParser(description="小雅语音助手环境引导")
    parser.add_argument("--stage1", action="store_true",
                        help="只安装阶段一依赖（faster-whisper / sounddevice / numpy）")
    parser.add_argument("--download-model", action="store_true",
                        help="预下载 Whisper 模型到本地缓存（需已安装 faster-whisper）")
    args = parser.parse_args()

    check_python()

    if args.download_model:
        download_model()
        return
    if args.stage1:
        install_stage1()
    else:
        install_requirements()
    print_next_steps()


if __name__ == "__main__":
    main()
