from typing import Literal, BinaryIO
from faster_whisper import WhisperModel
from tqdm import tqdm


def generate_subtitles(
    audio: BinaryIO,
    type: Literal["text", "timestamped"],
    model_size: str = "small",
    device: str = "cpu",
) -> str:
    print("Using device:", device)
    print(f"Loading whisper model: {model_size}")

    # Set compute type based on device
    compute_type = "int8" if "cuda" in device else "float32"
    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    print("Transcribing...")
    segments, info = model.transcribe(audio, beam_size=5)

    results = []
    # Use tqdm for a real-time progress bar
    with tqdm(total=round(info.duration, 2), desc="Transcribing", unit="s") as pbar:
        last_end = 0.0
        for segment in segments:
            if type == "text":
                results.append(segment.text.strip())
            else:
                results.append(
                    f"""{format_timestamp(segment.start)} --> {format_timestamp(segment.end)}
{segment.text.strip()}
"""
                )
            # Update progress bar with the duration of the processed segment
            pbar.update(round(segment.end - last_end, 2))
            last_end = segment.end
        
        # Ensure the progress bar completes fully
        if last_end < info.duration:
            pbar.update(round(info.duration - last_end, 2))

    return "\n".join(results)


def format_timestamp(seconds: float) -> str:
    """将秒转换为 SRT 时间格式"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}".replace(".", ",")