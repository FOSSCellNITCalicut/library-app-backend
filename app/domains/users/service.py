from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.auth.service import (
    call_with_koha_retry,
    fetch_and_parse_account_page,
    fetch_and_parse_charges_page,
)
from app.domains.users.schemas import (
    AccountActivityResponse,
    BookStatusResponse,
    CheckedOutBook,
    FineHistoryResponse,
    FineHistoryItem,
    FinesResponse,
    LoanSummary,
    UserMeResponse,
)


async def get_user_profile(roll_no: str, db: AsyncSession) -> UserMeResponse:
    async def _fetch(cgisessid: str) -> UserMeResponse:
        account = await fetch_and_parse_account_page(cgisessid, roll_no)
        return UserMeResponse(
            roll_no=roll_no,
            name=account.name,
            email=account.email,
            loan_summary=LoanSummary(
                loan_count=account.loan_count,
                loan_limit=account.loan_limit,
            ),
            checked_out_books=[
                CheckedOutBook(
                    biblio_id=book.biblio_id,
                    title=book.title,
                    author=book.author,
                    due_date=book.due_date,
                )
                for book in account.checked_out_books
            ],
        )

    return await call_with_koha_retry(roll_no, db, _fetch)


async def get_fines(roll_no: str, db: AsyncSession) -> FinesResponse:
    async def _fetch(cgisessid: str) -> FinesResponse:
        account = await fetch_and_parse_charges_page(cgisessid, roll_no)
        return FinesResponse(outstanding_fine=account.outstanding_fine)

    return await call_with_koha_retry(roll_no, db, _fetch)


async def get_fines_history(roll_no: str, db: AsyncSession) -> FineHistoryResponse:
    """Return only actual fines (amount > 0)."""
    async def _fetch(cgisessid: str) -> FineHistoryResponse:
        account = await fetch_and_parse_charges_page(cgisessid, roll_no)
        return FineHistoryResponse(
            items=[
                FineHistoryItem(
                    amount=item.amount,
                    date=item.date,
                    status=item.status,
                )
                for item in account.fine_history
                if item.amount > 0
            ],
        )

    return await call_with_koha_retry(roll_no, db, _fetch)


async def get_account_activity(roll_no: str, db: AsyncSession) -> AccountActivityResponse:
    """Return all account transactions including zero-amount (returns, payments)."""
    async def _fetch(cgisessid: str) -> AccountActivityResponse:
        account = await fetch_and_parse_charges_page(cgisessid, roll_no)
        return AccountActivityResponse(
            items=[
                FineHistoryItem(
                    amount=item.amount,
                    date=item.date,
                    status=item.status,
                )
                for item in account.fine_history
            ],
        )

    return await call_with_koha_retry(roll_no, db, _fetch)


async def get_book_status(
    roll_no: str, biblio_id: int, db: AsyncSession
) -> BookStatusResponse:
    async def _fetch(cgisessid: str) -> BookStatusResponse:
        account = await fetch_and_parse_account_page(cgisessid, roll_no)
        borrowed = any(book.biblio_id == biblio_id for book in account.checked_out_books)
        return BookStatusResponse(borrowed_by_current_user=borrowed)

    return await call_with_koha_retry(roll_no, db, _fetch)
