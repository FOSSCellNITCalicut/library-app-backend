import logging

from fastapi import APIRouter

from app.domains.curriculum.schemas import CurriculumResponse, VersionResponse
from app.domains.curriculum.service import get_curriculum, get_version

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/curriculum", tags=["curriculum"])


@router.get(
    "/version",
    response_model=VersionResponse,
)
async def version():
    return VersionResponse(version=get_version())


@router.get(
    "",
    response_model=CurriculumResponse,
)
async def curriculum():
    data = get_curriculum()
    return CurriculumResponse(
        version=data.get("version", "unknown"),
        programmes=data.get("programmes", {}),
    )
