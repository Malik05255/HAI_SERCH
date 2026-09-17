import json
import re
import subprocess
import tempfile
from pathlib import Path

from .config import settings


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}
UPLOAD_ID_RE = re.compile(r"^[0-9a-f-]{36}(?:\.[a-z0-9]{1,8})?$")
ACCOUNT_ID_RE = re.compile(r"^[0-9a-f-]{36}$")


def _uploads_root() -> Path:
    root = Path(settings.data_dir, "uploads")
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def account_upload_root(account_id: str) -> Path:
    if not ACCOUNT_ID_RE.fullmatch(account_id.casefold()):
        raise ValueError("invalid account id")
    root = _uploads_root()
    folder = (root / account_id).resolve()
    folder.relative_to(root)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def resolve_upload_id(upload_id: str | None, account_id: str) -> Path | None:
    if not upload_id or not UPLOAD_ID_RE.fullmatch(upload_id.casefold()):
        return None
    try:
        root = account_upload_root(account_id)
        path = (root / upload_id).resolve()
        path.relative_to(root)
        return path if path.is_file() else None
    except (OSError, ValueError):
        return None


def _safe_local_path(value: str | None) -> Path | None:
    if not value:
        return None
    try:
        path = Path(value).resolve(strict=True)
        root = _uploads_root()
        path.relative_to(root)
        return path if path.is_file() else None
    except (OSError, ValueError):
        return None


def _analysis_cache_path(path: Path) -> Path:
    folder = path.parent / ".analysis"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{path.name}.json"


def delete_uploaded_media(value: str | None) -> bool:
    path = _safe_local_path(value)
    if path is None:
        return False
    try:
        cache = _analysis_cache_path(path)
        cache.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        try:
            cache.parent.rmdir()
        except OSError:
            pass
        try:
            path.parent.rmdir()
        except OSError:
            pass
        return True
    except OSError:
        return False


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


def _video_transcript(path: Path) -> str:
    if not settings.whisper_enabled:
        return ""
    cli = Path(settings.whisper_cli_path)
    model = Path(settings.whisper_model_path)
    if not cli.is_file() or not model.is_file():
        return ""

    tmp_root = Path(settings.data_dir, "tmp")
    tmp_root.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=tmp_root) as directory:
            work = Path(directory)
            audio = work / "audio.wav"
            output = work / "transcript"
            extracted = subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
                    "-t", str(settings.video_transcribe_max_seconds),
                    "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio),
                ],
                capture_output=True,
                timeout=180,
                check=False,
            )
            if extracted.returncode != 0 or not audio.is_file() or audio.stat().st_size == 0:
                return ""

            transcribed = subprocess.run(
                [
                    str(cli), "-m", str(model), "-f", str(audio),
                    "-otxt", "-of", str(output), "-np",
                ],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            transcript_file = Path(f"{output}.txt")
            if transcript_file.is_file():
                return " ".join(transcript_file.read_text(encoding="utf-8", errors="ignore").split())[:6000]
            return " ".join(transcribed.stdout.split())[:6000] if transcribed.returncode == 0 else ""
    except Exception:
        return ""


def _analyse(path: Path, input_type: str, max_frames: int) -> dict[str, str]:
    cache_path = _analysis_cache_path(path)
    if cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict):
                return {
                    "ocr": str(cached.get("ocr") or ""),
                    "transcript": str(cached.get("transcript") or ""),
                }
        except Exception:
            pass

    suffix = path.suffix.casefold()
    ocr_text = ""
    transcript = ""
    if input_type == "image" or suffix in IMAGE_EXTS:
        ocr_text = _ocr(path)
    elif input_type == "video" or suffix in VIDEO_EXTS:
        ocr_text = _video_ocr(path, max_frames=max_frames)
        transcript = _video_transcript(path)

    result = {"ocr": ocr_text, "transcript": transcript}
    try:
        cache_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return result


def enrich_query(base_query: str, input_url: str | None, input_type: str, max_frames: int) -> str:
    path = _safe_local_path(input_url)
    if path is None:
        return base_query.strip()

    analysis = _analyse(path, input_type=input_type, max_frames=max_frames)
    parts = [
        part.strip()
        for part in (base_query, analysis.get("ocr", ""), analysis.get("transcript", ""))
        if part and part.strip()
    ]
    return " ".join(parts)[:9000]
