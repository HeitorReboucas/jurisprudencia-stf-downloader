from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


ContentType = Literal[
    "acordaos",
    "decisoes_monocraticas",
]


class CollectionRequest(BaseModel):
    content_types: list[ContentType] = Field(min_length=1)
    date_from: date | None = None
    date_to: date | None = None
    query: str | None = Field(default=None, max_length=500)
    process_class: str | None = Field(default=None, max_length=80)
    drive_folder_id: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def validate_date_range(self) -> "CollectionRequest":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("A data inicial deve ser anterior ou igual à data final")
        if not (self.query or "").strip():
            raise ValueError("Informe palavras-chave para a pesquisa")
        self.content_types = list(dict.fromkeys(self.content_types))
        return self


class JobResponse(BaseModel):
    id: str
    status: str
    content_types: list[str]
    date_from: date | None
    date_to: date | None
    query: str | None
    process_class: str | None
    drive_folder_id: str | None
    found: int
    downloaded: int
    uploaded: int
    duplicates: int
    errors: int
    current_item: str | None
    error: str | None
    created_at: str
    updated_at: str


class EventResponse(BaseModel):
    id: int
    level: str
    message: str
    created_at: str


class DriveFolder(BaseModel):
    id: str
    name: str


class DriveAuthResponse(BaseModel):
    authorization_url: str
