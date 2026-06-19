from pydantic import BaseModel


class CheckedOutBook(BaseModel):
    biblio_id: int
    title: str
    author: str
    due_date: str


class LoanSummary(BaseModel):
    loan_count: int
    loan_limit: int


class UserMeResponse(BaseModel):
    roll_no: str
    name: str
    email: str | None = None
    loan_summary: LoanSummary
    checked_out_books: list[CheckedOutBook]


class FinesResponse(BaseModel):
    outstanding_fine: float


class FineHistoryItem(BaseModel):
    amount: float
    date: str
    status: str


class FineHistoryResponse(BaseModel):
    items: list[FineHistoryItem]


class AccountActivityResponse(BaseModel):
    items: list[FineHistoryItem]


class BookStatusResponse(BaseModel):
    borrowed_by_current_user: bool
