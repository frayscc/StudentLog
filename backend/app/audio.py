import io
import uuid
from pathlib import Path

from .config import settings
from .providers import ProviderError


def browser_audio_to_wav(content: bytes) -> Path:
    if not content:
        raise ProviderError("录音内容为空")
    try:
        import av
    except ImportError as exc:
        raise ProviderError("本地语音组件未安装，请安装 backend/requirements-asr.txt") from exc

    output_path = settings.data_dir / "temp_audio" / f"{uuid.uuid4().hex}.wav"
    try:
        with av.open(io.BytesIO(content), mode="r") as source, av.open(str(output_path), mode="w", format="wav") as target:
            stream = target.add_stream("pcm_s16le", rate=16000)
            stream.layout = "mono"
            resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=16000)
            for frame in source.decode(audio=0):
                for converted in resampler.resample(frame):
                    for packet in stream.encode(converted):
                        target.mux(packet)
            for converted in resampler.resample(None):
                for packet in stream.encode(converted):
                    target.mux(packet)
            for packet in stream.encode(None):
                target.mux(packet)
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        raise ProviderError(f"无法读取浏览器录音：{exc}") from exc
    return output_path
