from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_name: str = "البحث العميق"
    api_token: str = ""
    database_url: str = "postgresql+psycopg://deepsearch:deepsearch_local@localhost:5432/deepsearch"
    public_base_url: str = "http://localhost:8000"
    data_dir: str = "/data"

    searxng_url: str = "http://localhost:8080"
    search_max_results: int = 10
    search_max_candidates: int = 250
    search_verify_pages_per_run: int = 40
    search_http_timeout_seconds: int = 15
    search_max_active_jobs: int = 5
    search_idle_sleep_seconds: int = 5
    search_max_attempts: int = 48
    search_continue_attempt_floor: int = 8

    planner_enabled: bool = True
    planner_url: str = "http://planner:8082"
    planner_timeout_seconds: int = 75
    planner_max_queries: int = 6

    image_max_upload_mb: int = 30
    image_max_pixels: int = 80_000_000
    video_max_upload_mb: int = 250
    video_max_duration_seconds: int = 600
    video_max_keyframes: int = 12
    video_transcribe_max_seconds: int = 300
    ocr_languages: str = "eng+ara+deu+fra+spa+chi_sim+chi_tra+jpn+kor+rus+tur"
    whisper_enabled: bool = True
    whisper_cli_path: str = "/usr/local/bin/whisper-cli"
    whisper_model_path: str = "/opt/whisper.cpp/models/ggml-tiny.bin"

    vision_enabled: bool = True
    vision_url: str = "http://vision:8081"
    vision_max_frames: int = 4
    vision_timeout_seconds: int = 90
    visual_hash_max_distance: int = 14

    cloud_media_quota_gb: int = 20
    temp_file_ttl_hours: int = 24

    notifications_enabled: bool = False
    firebase_project_id: str = ""
    firebase_service_account_b64: str = ""

    # Public web egress only. SearXNG and other Docker-internal services always
    # stay on the direct internal network and are never sent through this proxy.
    egress_mode: str = "auto"  # auto | direct | vpn
    egress_proxy_url: str = ""

    github_repository: str = "Malik05255/HAI_SERCH"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
