from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1, description="Page number, 1-indexed")
    per_page: int = Field(default=20, ge=1, le=100, description="Items per page")


class ErrorResponse(BaseModel):
    error: str = Field(description="Short machine-readable error code")
    detail: str | None = Field(default=None, description="Human-readable explanation")
