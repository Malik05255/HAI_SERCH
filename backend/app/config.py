from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "production"
    app_name: str = "البحث العميق"
    database_url: str = "postgresql+psycopg://deepsearch:deepsearch@localhost:5432/deepsearch"
    public_base_url: str = "http://localhost:8000"

    searxng_url: str = "http://localhost:8080"
    search_max_results: int = 10
    search_max_candidates: int = 250
    search_http_timeout_seconds: int = 15
    search_browser_budget_per_job: int = 8
    search_max_active_jobs: int = 2
    search_idle_sleep_seconds: int = 5

    video_max_upload_mb: int = 250
    video_max_keyframes: int = 12
    audio_transcribe_max_minutes: int = 20
    temp_file_ttl_hours: int = 24

    r2_endpoint: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "deep-search"
    r2_public_base_url: str = ""

    fcm_project_id: str = ""
    fcm_service_account_json: str = ""
    egress_proxy_url: str = ""
    github_repository: str = "Malik05255/HAI_SERCH"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
