"""Download offline ASR models into the Docker-mounted models directory."""

import argparse
import os
from pathlib import Path


MODELS_DIR = Path(os.getenv("MODELS_DIR", "/app/models"))
MODELS = {
    "paraformer": "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
    "sensevoice": "iic/SenseVoiceSmall",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="下载 StudentLog 本地语音识别模型")
    parser.add_argument("model", choices=[*MODELS, "all"], nargs="?", default="paraformer")
    args = parser.parse_args()
    try:
        from modelscope import snapshot_download
    except ImportError as exc:
        raise SystemExit("当前镜像不包含本地 ASR 依赖") from exc

    names = list(MODELS) if args.model == "all" else [args.model]
    for name in names:
        target = MODELS_DIR / name
        target.mkdir(parents=True, exist_ok=True)
        print(f"正在下载 {name} 到 {target}。下载进度由 ModelScope 显示。")
        snapshot_download(MODELS[name], local_dir=str(target))
        print(f"{name} 安装完成。")


if __name__ == "__main__":
    main()
