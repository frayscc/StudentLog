"""Download offline ASR models into the portable StudentLog directory."""

import argparse
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
MODELS = {
    "paraformer": "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
    "sensevoice": "iic/SenseVoiceSmall",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="安装 StudentLog 本地语音识别模型")
    parser.add_argument("model", choices=[*MODELS, "all"], nargs="?", default="paraformer")
    args = parser.parse_args()
    try:
        from modelscope import snapshot_download
    except ImportError as exc:
        raise SystemExit("请先安装 backend/requirements-asr.txt") from exc

    names = list(MODELS) if args.model == "all" else [args.model]
    for name in names:
        target = ROOT_DIR / "models" / name
        target.mkdir(parents=True, exist_ok=True)
        print(f"正在下载 {name} 到 {target}。下载进度由 ModelScope 显示。")
        snapshot_download(MODELS[name], local_dir=str(target))
        print(f"{name} 安装完成。")


if __name__ == "__main__":
    main()
