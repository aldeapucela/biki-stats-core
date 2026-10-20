from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str
    message: str
    field: str | None = None


class PaginationMeta(BaseModel):
    limit: int
    offset: int
    returned: int
    has_more: bool


class Meta(BaseModel):
    request_id: str | None = None
    generated_at: datetime | None = None
    pagination: PaginationMeta | None = None
    warnings: list[str] = Field(default_factory=list)


class Envelope(BaseModel, Generic[T]):
    model_config = ConfigDict(serialize_by_alias=True)

    status: str
    code: int
    data: T | None
    errors: list[ErrorDetail] | None
    meta: Meta


class EmptyData(BaseModel):
    model_config = ConfigDict(extra="forbid")
