from pydantic import BaseModel
from app.domains.books.schemas import BookDetailSchema

class CatalogBookDetailSchema(BookDetailSchema):
    search_string: str 

class CatalogBooksResponse(BaseModel):
    course_id: str
    books: list[CatalogBookDetailSchema]
