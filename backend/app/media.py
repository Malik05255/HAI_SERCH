import subprocess
import tempfile
from pathlib import Path

from .config import settings


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}


def _safe_local_path(value: str | None) -> Path | None:
    if not value:
        return None
    try:
        path = Path(value).resolve(strict=True)
        root = Path(settings.data_dir).resolve(strict=True)
        path.relative_to(root)
        return path
    except (OSError, ValueError):
        return None


def _ocr(path: Path) -> str:
    try:
        result = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", "ara+eng", "--psm", "6"],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        return " ".join(result.stdout.split())[:2500]
    except Exception:
        return ""


def _video_ocr(path: Path, max_frames: int) -> str:
    tmp_root = Path(settings.data_dir, "tmp")
    tmp_root.mkdir(parents=True, exist_ok=True)
    chunks: list[str] = []
    try:
        with tempfile.TemporaryDirectory(dir=tmp_root) as directory:
            pattern = str(Path(directory, "frame-%02d.jpg"))
            subprocess.run(
                [
                    "ffmpeg", "-loglevel", "error", "-i", str(path),
                    "-vf", "fps=1/12,scale=1280:-2:force_original_aspect_ratio=decrease",
                    "-frames:v", str(max_frames), "-q:v", "3", pattern,
                ],
                capture_output=True,
                timeout=180,
                check=False,
            )
            for frame in sorted(Path(directory).glob("frame-*.jpg"))[:max_frames]:
                text = _ocr(frame)
                if text and text not in chunks:
                    chunks.append(text)
    except Exception:
        return ""
    return " ".join(chunks)[:5000]


def enrich_query(base_query: str, input_url: str | None, input_type: str, max_frames: int) -> str:
    path = _safe_local_path(input_url)
    if path is None:
        return base_query.strip()

    media_text = ""
    suffix = path.suffix.casefold()
    if input_type == "image" or suffix in IMAGE_EXTS:
        media_text = _ocr(path)
    elif input_type == "video" or suffix in VIDEO_EXTS:
        media_text = _video_ocr(path, max_frames=max_frames)

    parts = [part.strip() for part in (base_query, media_text) if part and part.strip()]
    return " ".join(parts)[:6000]
