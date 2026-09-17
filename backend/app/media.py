import base64
import json
import re
import subprocess
import tempfile
from pathlib import Path

import httpx
import imagehash
from PIL import Image

from .config import settings


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}
UPLOAD_ID_RE = re.compile(r"^[0-9a-f-]{36}(?:\.[a-z0-9]{1,8})?$")
ACCOUNT_ID_RE = re.compile(r"^[0-9a-f-]{36}$")

VISION_PROMPT = (
    "Describe only what is visibly supported by this image for the purpose of finding its original source online. "
    "Mention setting, people appearance without guessing identity, clothing, objects, logos, readable title clues, "
    "cinematic style, animation/live-action, distinctive landmarks, and anything useful for identifying a movie, "
    "series, video, product, place, or webpage. Do not invent names or facts. Be concise and search-oriented."
)


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


def _phash(path: Path) -> str:
    try:
        with Image.open(path) as image:
            return str(imagehash.phash(image.convert("RGB")))
    except Exception:
        return ""


def _vision_input(path: Path, target: Path) -> Path | None:
    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((1024, 1024))
            image.save(target, format="JPEG", quality=82, optimize=True)
        return target
    except Exception:
        return None


def _vision_describe(path: Path) -> str:
    if not settings.vision_enabled:
        return ""
    try:
        tmp_root = Path(settings.data_dir, "tmp")
        tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=tmp_root) as directory:
            normalized = _vision_input(path, Path(directory, "vision.jpg"))
            if normalized is None:
                return ""
            encoded = base64.b64encode(normalized.read_bytes()).decode("ascii")
            payload = {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": VISION_PROMPT},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
                        ],
                    }
                ],
                "temperature": 0,
                "max_tokens": 240,
            }
            response = httpx.post(
                f"{settings.vision_url.rstrip('/')}/v1/chat/completions",
                json=payload,
                timeout=settings.vision_timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if isinstance(content, list):
                content = " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
            return " ".join(str(content).split())[:3500]
    except Exception:
        return ""


def _extract_video_frames(path: Path, directory: Path, max_frames: int) -> list[Path]:
    pattern = str(directory / "frame-%02d.jpg")
    try:
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
    except Exception:
        return []
    return sorted(directory.glob("frame-*.jpg"))[:max_frames]


def _video_transcript(path: Path, work: Path) -> str:
    if not settings.whisper_enabled:
        return ""
    cli = Path(settings.whisper_cli_path)
    model = Path(settings.whisper_model_path)
    if not cli.is_file() or not model.is_file():
        return ""
    try:
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
            [str(cli), "-m", str(model), "-f", str(audio), "-otxt", "-of", str(output), "-np"],
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


def _empty_features() -> dict:
    return {"ocr": "", "transcript": "", "vision": "", "hashes": []}


def _cached_features(cache_path: Path) -> dict | None:
    if not cache_path.is_file():
        return None
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(cached, dict):
            return None
        result = {
            "ocr": str(cached.get("ocr") or ""),
            "transcript": str(cached.get("transcript") or ""),
            "vision": str(cached.get("vision") or ""),
            "hashes": [str(x) for x in cached.get("hashes", []) if x],
        }
        if settings.vision_enabled and not result["vision"]:
            return None
        return result
    except Exception:
        return None


def media_features(input_url: str | None, input_type: str, max_frames: int) -> dict:
    path = _safe_local_path(input_url)
    if path is None:
        return _empty_features()

    cache_path = _analysis_cache_path(path)
    cached = _cached_features(cache_path)
    if cached is not None:
        return cached

    result = _empty_features()
    suffix = path.suffix.casefold()
    tmp_root = Path(settings.data_dir, "tmp")
    tmp_root.mkdir(parents=True, exist_ok=True)

    if input_type == "image" or suffix in IMAGE_EXTS:
        result["ocr"] = _ocr(path)
        result["vision"] = _vision_describe(path)
        fingerprint = _phash(path)
        if fingerprint:
            result["hashes"] = [fingerprint]
    elif input_type == "video" or suffix in VIDEO_EXTS:
        try:
            with tempfile.TemporaryDirectory(dir=tmp_root) as directory:
                work = Path(directory)
                frames = _extract_video_frames(path, work, max_frames=max_frames)
                ocr_chunks: list[str] = []
                vision_chunks: list[str] = []
                hashes: list[str] = []
                visual_frames = frames[: settings.vision_max_frames]
                for frame in frames:
                    text = _ocr(frame)
                    if text and text not in ocr_chunks:
                        ocr_chunks.append(text)
                    fingerprint = _phash(frame)
                    if fingerprint and fingerprint not in hashes:
                        hashes.append(fingerprint)
                for frame in visual_frames:
                    description = _vision_describe(frame)
                    if description and description not in vision_chunks:
                        vision_chunks.append(description)
                result["ocr"] = " ".join(ocr_chunks)[:5000]
                result["vision"] = " | ".join(vision_chunks)[:6500]
                result["hashes"] = hashes[:max_frames]
                result["transcript"] = _video_transcript(path, work)
        except Exception:
            pass

    # A media job that requires Vision is not considered analysed until the
    # visual model actually returned content. This prevents an early service
    # startup failure from becoming a permanent empty cache.
    if not settings.vision_enabled or result["vision"]:
        try:
            cache_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return result


def enrich_query(base_query: str, input_url: str | None, input_type: str, max_frames: int) -> str:
    features = media_features(input_url, input_type=input_type, max_frames=max_frames)
    parts = [
        part.strip()
        for part in (base_query, features["ocr"], features["transcript"], features["vision"])
        if part and part.strip()
    ]
    return " ".join(parts)[:12000]


def visual_hashes(input_url: str | None, input_type: str, max_frames: int) -> list[str]:
    return list(media_features(input_url, input_type=input_type, max_frames=max_frames).get("hashes", []))
