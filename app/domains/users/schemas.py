from typing import Literal

from pydantic import BaseModel


class CheckedOutBook(BaseModel):
    biblio_id: int
    issue_id: int = 0
    title: str
    author: str
    due_date: str
    renewals_allowed: int = 0
    renewals_remaining: int = 0


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


class PickupBranch(BaseModel):
    code: str
    name: str
    is_default: bool = False


class HoldFormResponse(BaseModel):
    biblio_id: int
    holdable: bool
    branches: list[PickupBranch]


class PlaceHoldRequest(BaseModel):
    branch_code: Literal["LIB", "MAT"]


class PlaceHoldResponse(BaseModel):
    success: bool
    message: str


class HoldItem(BaseModel):
    reserve_id: str
    biblio_id: int
    title: str
    branch: str
    status: str


class HoldsResponse(BaseModel):
    items: list[HoldItem]


class CancelHoldResponse(BaseModel):
    success: bool
    message: str


class RenewBookResponse(BaseModel):
    success: bool
    message: str
