from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class JobCreate(BaseModel):
    query: str = Field(default="", max_length=4000)
    input_type: str = Field(default="text", pattern="^(text|image|video)$")
    upload_id: str | None = Field(default=None, max_length=64)
    target_results: int = Field(default=10, ge=1, le=20)

    @model_validator(mode="after")
    def require_query_or_input(self):
        if not self.query.strip() and not self.upload_id:
            raise ValueError("query or upload_id is required")
        if self.input_type == "text" and self.upload_id:
            raise ValueError("text jobs cannot contain upload_id")
        if self.input_type != "text" and not self.upload_id:
            raise ValueError("media jobs require upload_id")
        return self


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    query: str
    input_type: str
    target_results: int
    status: str
    progress: float
    found_count: int
    attempts: int
    queue_position: int | None = None
    media_available: bool = False
    created_at: datetime
    updated_at: datetime


class ResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rank: int
    title: str
    url: str
    image_url: str | None
    summary: str
    match_score: float
    evidence: dict
