import json
from types import SimpleNamespace

from PIL import Image, ImageDraw

import app.media as media
from app.media import probe_uploaded_media


def test_probe_uploaded_media_detects_real_image_bytes(tmp_path) -> None:
    path = tmp_path / "misleading.bin"
    Image.new("RGB", (64, 32), "white").save(path, format="PNG")

    probe = probe_uploaded_media(path)

    assert probe is not None
    assert probe.input_type == "image"
    assert probe.canonical_suffix == ".png"
    assert probe.width == 64
    assert probe.height == 32


def test_probe_uploaded_media_rejects_arbitrary_bytes(tmp_path, monkeypatch) -> None:
    path = tmp_path / "fake.jpg"
    path.write_bytes(b"not an image or a video")
    monkeypatch.setattr(
        "app.media.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="bad"),
    )

    assert probe_uploaded_media(path) is None


def test_probe_uploaded_media_requires_video_stream(tmp_path, monkeypatch) -> None:
    path = tmp_path / "audio-only.mp4"
    path.write_bytes(b"fake container bytes")
    payload = {
        "streams": [],
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "12.5"},
    }
    monkeypatch.setattr(
        "app.media.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr=""),
    )

    assert probe_uploaded_media(path) is None


def test_probe_uploaded_media_reads_video_container_and_duration(tmp_path, monkeypatch) -> None:
    path = tmp_path / "clip.bin"
    path.write_bytes(b"fake container bytes")
    payload = {
        "streams": [{"codec_type": "video"}],
        "format": {"format_name": "matroska,webm", "duration": "9.75"},
    }
    monkeypatch.setattr(
        "app.media.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr=""),
    )

    probe = probe_uploaded_media(path)

    assert probe is not None
    assert probe.input_type == "video"
    assert probe.canonical_suffix == ".webm"
    assert probe.duration == 9.75


def test_scene_frames_skip_second_decode_when_visual_evidence_is_enough(tmp_path, monkeypatch) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    scene_frames = [tmp_path / f"scene-{index:02d}.jpg" for index in range(1, 5)]
    calls: list[str] = []

    def fake_extract(_path, pattern, _filter, _max_frames):
        calls.append(pattern.name)
        if pattern.name.startswith("scene-"):
            return scene_frames
        raise AssertionError("uniform fallback should not run")

    monkeypatch.setattr(media, "_extract_with_filter", fake_extract)
    monkeypatch.setattr(media, "_dedupe_frames", lambda paths, limit: paths[:limit])

    result = media._extract_video_frames(video, tmp_path, max_frames=12)

    assert result == scene_frames
    assert calls == ["scene-%02d.jpg"]


def test_scene_sampling_falls_back_to_temporal_coverage_when_cuts_are_sparse(tmp_path, monkeypatch) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    scene_frames = [tmp_path / "scene-01.jpg", tmp_path / "scene-02.jpg"]
    uniform_frames = [tmp_path / "uniform-01.jpg", tmp_path / "uniform-02.jpg"]
    calls: list[str] = []

    def fake_extract(_path, pattern, _filter, _max_frames):
        calls.append(pattern.name)
        return scene_frames if pattern.name.startswith("scene-") else uniform_frames

    monkeypatch.setattr(media, "_extract_with_filter", fake_extract)
    monkeypatch.setattr(media, "_dedupe_frames", lambda paths, limit: paths[:limit])
    monkeypatch.setattr(media, "_video_duration", lambda _path: 120.0)

    result = media._extract_video_frames(video, tmp_path, max_frames=8)

    assert result == scene_frames + uniform_frames
    assert calls == ["scene-%02d.jpg", "uniform-%02d.jpg"]


def test_frame_dedupe_removes_near_identical_images(tmp_path) -> None:
    first = tmp_path / "first.jpg"
    duplicate = tmp_path / "duplicate.jpg"
    distinct = tmp_path / "distinct.jpg"

    base = Image.new("RGB", (128, 128), "white")
    draw = ImageDraw.Draw(base)
    draw.rectangle((12, 12, 52, 116), fill="black")
    base.save(first)
    base.save(duplicate)

    other = Image.new("RGB", (128, 128), "white")
    draw = ImageDraw.Draw(other)
    draw.rectangle((76, 8, 116, 120), fill="black")
    other.save(distinct)

    selected = media._dedupe_frames([first, duplicate, distinct], max_frames=8)

    assert first in selected
    assert duplicate not in selected
    assert distinct in selected


def test_media_cache_rejects_stale_versions(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "old.json"
    cache.write_text(
        json.dumps({
            "version": media.MEDIA_CACHE_VERSION - 1,
            "ocr": "text",
            "transcript": "speech",
            "vision": "scene",
            "hashes": ["abc"],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(media.settings, "vision_enabled", True)

    assert media._cached_features(cache) is None


def test_media_cache_accepts_current_version(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "current.json"
    cache.write_text(
        json.dumps({
            "version": media.MEDIA_CACHE_VERSION,
            "ocr": "text",
            "transcript": "speech",
            "vision": "scene",
            "hashes": ["abc"],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(media.settings, "vision_enabled", True)

    cached = media._cached_features(cache)

    assert cached is not None
    assert cached["vision"] == "scene"
    assert cached["hashes"] == ["abc"]
