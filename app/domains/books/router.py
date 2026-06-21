from fastapi import APIRouter, Query ,Path, Depends, HTTPException , status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.domains.books.service import (
    BookService,                 
    BookNotFoundError,           
    ServiceValidationError, 
    BiblioNotFoundError,
)
#need repository file done to create service
from app.domains.books.repository import BooksRepository
from app.domains.books.schemas import (
    BookListResponse,
    BookDetailSchema,
)

router = APIRouter(
    prefix="/books",
    tags=["books"]
)


# Dependency to create service
def get_book_service(
    db: AsyncSession = Depends(get_db),
) -> BookService:
    
    repository = BooksRepository(db)
    return BookService(repository)


@router.get(
    "/browse",
    response_model=BookListResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "List of books retrieved successfully"},
        400: {"description": "Invalid query parameters"},
        500: {"description": "Internal server error"},
    },
)
async def browse_books(
    service: BookService = Depends(get_book_service),
    page: int = Query(
        default=1,
        ge=1,
        description="Page number for pagination",
    ),
    per_page: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Number of books per page",
    ),

    # REMOVED: home_library_id ,Service layer doesn't support this parameter.

):
    try:
        return await service.browse_books(            
            page=page,
            per_page=per_page,
        )

    except ServiceValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/search",
    response_model=BookListResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Search results returned successfully"},
        400: {"description": "Invalid search query"},
        500: {"description": "Internal server error"},
    },
)
async def search_books(
    service: BookService = Depends(get_book_service), 
    q: str = Query(
        ...,
        min_length=1,
        max_length=100,
        description="Search query for books",
    ),
    page: int = Query(
        default=1,
        ge=1,
        description="Page number for pagination",
    ),
    per_page: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Number of books per page",
    ),
    
):
    try:
        return await service.search_books(
            query=q,                                  
            # service expects query not q
            page=page,
            per_page=per_page,
        )

    except ServiceValidationError as e:              
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/search/isbn",
    response_model=BookListResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "ISBN search results returned successfully"},
        400: {"description": "Invalid ISBN query"},
        500: {"description": "Internal server error"},
    },
)
async def search_by_isbn(
    service: BookService = Depends(get_book_service),
    q: str = Query(
        ...,
        min_length=1,
        max_length=20,
        description="ISBN to search for (10 or 13 digits, with or without hyphens)",
    ),
):
    try:
        return await service.search_by_isbn(isbn=q)

    except ServiceValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/{biblio_id}",
    response_model=BookDetailSchema,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Book retrieved successfully"},
        404: {"description": "Book not found"},
        500: {"description": "Internal server error"},
    },
)
async def get_book(
    service: BookService = Depends(get_book_service),
    biblio_id: int = Path(
        ...,
        description="ID of the book to retrieve",
    ),
):
    try:
        return await service.get_book_details(         
            biblio_id=biblio_id
        )

    except BookNotFoundError as e:                   
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )

    except ServiceValidationError as e:              
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
        
@router.get(
    "/{biblio_id}/availability",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Availability fetched successfully"},
        404: {"description": "Book not found"},
        500: {"description": "Internal server error"},
    },
)
async def check_availability(
    service: BookService = Depends(get_book_service),
    biblio_id: int = Path(..., description="ID of the book"),
):
    try:
        return await service.check_availability(biblio_id=biblio_id)

    except BiblioNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )

    except ServiceValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
