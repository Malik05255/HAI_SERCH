import json
from types import SimpleNamespace

from PIL import Image

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
