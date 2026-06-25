import logging

from fastapi import APIRouter, HTTPException, status

from app.domains.opac_home.schemas import OpacHomeResponse
from app.domains.opac_home.service import fetch_homepage_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/opac", tags=["opac"])


@router.get(
    "/home",
    response_model=OpacHomeResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "OPAC homepage data retrieved successfully"},
        502: {"description": "Failed to fetch OPAC homepage"},
    },
)
async def get_opac_home_data():
    try:
        return await fetch_homepage_data()
    except Exception as e:
        logger.exception("Failed to fetch OPAC homepage data")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch OPAC homepage data: {str(e)}",
        )
