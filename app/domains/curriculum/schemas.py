from pydantic import BaseModel, Field


class VersionResponse(BaseModel):
    version: str = Field(description="Current curriculum version string")


class CurriculumResponse(BaseModel):
    version: str = Field(description="Current curriculum version string")
    programmes: dict = Field(description="Full curriculum tree: programmes > branches > courses")
