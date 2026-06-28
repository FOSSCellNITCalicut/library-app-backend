import dataclasses
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache as _cache
from app.domains.auth.account_parser import (
    AccountPageData,
    CheckedOutBook as _ParsedBook,
    FineHistoryItem as _ParsedFineItem,
    HoldItem as _ParsedHoldItem,
)
from app.domains.auth.service import (
    call_with_koha_retry,
    fetch_and_parse_account_page,
    fetch_and_parse_charges_page,
    fetch_and_parse_hold_form,
)
from app.domains.auth.service import cancel_hold as koha_cancel_hold
from app.domains.auth.service import place_hold as koha_place_hold
from app.domains.auth.service import renew_book as koha_renew_book
from app.domains.users.schemas import (
    AccountActivityResponse,
    BookStatusResponse,
    CancelHoldResponse,
    CheckedOutBook,
    FineHistoryResponse,
    FineHistoryItem,
    FinesResponse,
    HoldFormResponse,
    HoldItem,
    HoldsResponse,
    LoanSummary,
    PickupBranch,
    PlaceHoldResponse,
    RenewBookResponse,
    UserMeResponse,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cache serialization helpers
# ---------------------------------------------------------------------------

def _account_to_dict(account: AccountPageData) -> dict:
    return dataclasses.asdict(account)


def _dict_to_account(data: dict) -> AccountPageData:
    return AccountPageData(
        name=data["name"],
        email=data.get("email"),
        loan_count=data.get("loan_count", 0),
        loan_limit=data.get("loan_limit", 0),
        outstanding_fine=data.get("outstanding_fine", 0.0),
        renewal_csrf_token=data.get("renewal_csrf_token"),
        checked_out_books=[_ParsedBook(**b) for b in data.get("checked_out_books", [])],
        fine_history=[_ParsedFineItem(**f) for f in data.get("fine_history", [])],
        holds=[_ParsedHoldItem(**h) for h in data.get("holds", [])],
    )


async def _store_account_cache(roll_no: str, account: AccountPageData) -> None:
    await _cache.set_json(_cache.account_key(roll_no), _account_to_dict(account), _cache.ACCOUNT_TTL)
    biblio_ids = [str(b.biblio_id) for b in account.checked_out_books]
    if biblio_ids:
        await _cache.sadd_with_ttl(_cache.borrowed_set_key(roll_no), biblio_ids, _cache.ACCOUNT_TTL)
    else:
        # No books checked out -- delete any stale set so sismember returns None
        # and falls through to the account cache rather than returning a false negative.
        await _cache.delete(_cache.borrowed_set_key(roll_no))


async def _get_account_cache(roll_no: str) -> AccountPageData | None:
    data = await _cache.get_json(_cache.account_key(roll_no))
    if data is None:
        return None
    try:
        return _dict_to_account(data)
    except Exception as e:
        logger.warning("Corrupt account cache for roll_no=%s, discarding: %s", roll_no, e)
        return None


async def _store_charges_cache(roll_no: str, account: AccountPageData) -> None:
    await _cache.set_json(_cache.charges_key(roll_no), _account_to_dict(account), _cache.CHARGES_TTL)


async def _get_charges_cache(roll_no: str) -> AccountPageData | None:
    data = await _cache.get_json(_cache.charges_key(roll_no))
    if data is None:
        return None
    try:
        return _dict_to_account(data)
    except Exception as e:
        logger.warning("Corrupt charges cache for roll_no=%s, discarding: %s", roll_no, e)
        return None


async def _invalidate_user_cache(roll_no: str) -> None:
    await _cache.delete(
        _cache.account_key(roll_no),
        _cache.charges_key(roll_no),
        _cache.borrowed_set_key(roll_no),
    )


# ---------------------------------------------------------------------------
# Response builders (shared between cache-hit and Koha-scrape paths)
# ---------------------------------------------------------------------------

def _build_user_me_response(roll_no: str, account: AccountPageData) -> UserMeResponse:
    return UserMeResponse(
        roll_no=roll_no,
        name=account.name,
        email=account.email,
        loan_summary=LoanSummary(loan_count=account.loan_count, loan_limit=account.loan_limit),
        checked_out_books=[
            CheckedOutBook(
                biblio_id=b.biblio_id,
                issue_id=b.issue_id,
                title=b.title,
                author=b.author,
                due_date=b.due_date,
                renewals_allowed=b.renewals_allowed,
                renewals_remaining=b.renewals_remaining,
            )
            for b in account.checked_out_books
        ],
    )


def _build_book_status(account: AccountPageData, biblio_id: int) -> BookStatusResponse:
    match = next((b for b in account.checked_out_books if b.biblio_id == biblio_id), None)
    if match is None:
        return BookStatusResponse(borrowed_by_current_user=False)
    return BookStatusResponse(
        borrowed_by_current_user=True,
        issue_id=match.issue_id,
        renewals_allowed=match.renewals_allowed,
        renewals_remaining=match.renewals_remaining,
    )


def _build_holds_response(account: AccountPageData) -> HoldsResponse:
    return HoldsResponse(
        items=[
            HoldItem(
                reserve_id=h.reserve_id,
                biblio_id=h.biblio_id,
                title=h.title,
                branch=h.branch,
                status=h.status,
            )
            for h in account.holds
        ]
    )


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------

async def get_user_profile(roll_no: str, db: AsyncSession) -> UserMeResponse:
    cached = await _get_account_cache(roll_no)
    if cached is not None:
        return _build_user_me_response(roll_no, cached)

    async def _fetch(cgisessid: str) -> UserMeResponse:
        account = await fetch_and_parse_account_page(cgisessid, roll_no)
        await _store_account_cache(roll_no, account)
        return _build_user_me_response(roll_no, account)

    return await call_with_koha_retry(roll_no, db, _fetch)


async def get_fines(roll_no: str, db: AsyncSession) -> FinesResponse:
    cached = await _get_charges_cache(roll_no)
    if cached is not None:
        return FinesResponse(outstanding_fine=cached.outstanding_fine)

    async def _fetch(cgisessid: str) -> FinesResponse:
        account = await fetch_and_parse_charges_page(cgisessid, roll_no)
        await _store_charges_cache(roll_no, account)
        return FinesResponse(outstanding_fine=account.outstanding_fine)

    return await call_with_koha_retry(roll_no, db, _fetch)


async def get_fines_history(roll_no: str, db: AsyncSession) -> FineHistoryResponse:
    cached = await _get_charges_cache(roll_no)
    if cached is not None:
        return FineHistoryResponse(
            items=[
                FineHistoryItem(amount=i.amount, date=i.date, status=i.status)
                for i in cached.fine_history
                if i.amount > 0
            ]
        )

    async def _fetch(cgisessid: str) -> FineHistoryResponse:
        account = await fetch_and_parse_charges_page(cgisessid, roll_no)
        await _store_charges_cache(roll_no, account)
        return FineHistoryResponse(
            items=[
                FineHistoryItem(amount=i.amount, date=i.date, status=i.status)
                for i in account.fine_history
                if i.amount > 0
            ]
        )

    return await call_with_koha_retry(roll_no, db, _fetch)


async def get_account_activity(roll_no: str, db: AsyncSession) -> AccountActivityResponse:
    cached = await _get_charges_cache(roll_no)
    if cached is not None:
        return AccountActivityResponse(
            items=[
                FineHistoryItem(amount=i.amount, date=i.date, status=i.status)
                for i in cached.fine_history
            ]
        )

    async def _fetch(cgisessid: str) -> AccountActivityResponse:
        account = await fetch_and_parse_charges_page(cgisessid, roll_no)
        await _store_charges_cache(roll_no, account)
        return AccountActivityResponse(
            items=[
                FineHistoryItem(amount=i.amount, date=i.date, status=i.status)
                for i in account.fine_history
            ]
        )

    return await call_with_koha_retry(roll_no, db, _fetch)


async def get_book_status(roll_no: str, biblio_id: int, db: AsyncSession) -> BookStatusResponse:
    # Fast negative path: O(1) Redis set check avoids deserializing the full
    # account JSON when the user simply hasn't borrowed this book.
    in_set = await _cache.sismember(_cache.borrowed_set_key(roll_no), str(biblio_id))
    if in_set is False:
        return BookStatusResponse(borrowed_by_current_user=False)

    # Account cache path (in_set is True or set is absent).
    cached = await _get_account_cache(roll_no)
    if cached is not None:
        return _build_book_status(cached, biblio_id)

    # Slow path: scrape Koha and populate both caches.
    async def _fetch(cgisessid: str) -> BookStatusResponse:
        account = await fetch_and_parse_account_page(cgisessid, roll_no)
        await _store_account_cache(roll_no, account)
        return _build_book_status(account, biblio_id)

    return await call_with_koha_retry(roll_no, db, _fetch)


async def get_hold_form(roll_no: str, biblio_id: int, db: AsyncSession) -> HoldFormResponse:
    async def _fetch(cgisessid: str) -> HoldFormResponse:
        form = await fetch_and_parse_hold_form(cgisessid, roll_no, biblio_id)
        return HoldFormResponse(
            biblio_id=biblio_id,
            holdable=form.holdable,
            branches=[
                PickupBranch(code=b.code, name=b.name, is_default=b.is_default)
                for b in form.branches
            ],
        )

    return await call_with_koha_retry(roll_no, db, _fetch)


async def place_hold(
    roll_no: str, biblio_id: int, branch_code: str, db: AsyncSession
) -> PlaceHoldResponse:
    async def _place(cgisessid: str) -> PlaceHoldResponse:
        # Use cached account for the duplicate-hold check; scrape if cache is cold.
        account = await _get_account_cache(roll_no)
        if account is None:
            account = await fetch_and_parse_account_page(cgisessid, roll_no)
            await _store_account_cache(roll_no, account)

        if any(h.biblio_id == biblio_id for h in account.holds):
            return PlaceHoldResponse(
                success=False,
                message="You already have an active hold on this item.",
            )

        success, message = await koha_place_hold(cgisessid, roll_no, biblio_id, branch_code)
        if success:
            await _invalidate_user_cache(roll_no)
        return PlaceHoldResponse(success=success, message=message)

    return await call_with_koha_retry(roll_no, db, _place)


async def get_holds(roll_no: str, db: AsyncSession) -> HoldsResponse:
    cached = await _get_account_cache(roll_no)
    if cached is not None:
        return _build_holds_response(cached)

    async def _fetch(cgisessid: str) -> HoldsResponse:
        account = await fetch_and_parse_account_page(cgisessid, roll_no)
        await _store_account_cache(roll_no, account)
        return _build_holds_response(account)

    return await call_with_koha_retry(roll_no, db, _fetch)


async def renew_book(roll_no: str, issue_id: int, db: AsyncSession) -> RenewBookResponse:
    async def _renew(cgisessid: str) -> RenewBookResponse:
        success, message = await koha_renew_book(cgisessid, roll_no, issue_id)
        if success:
            await _invalidate_user_cache(roll_no)
        return RenewBookResponse(success=success, message=message)

    return await call_with_koha_retry(roll_no, db, _renew)


async def cancel_hold(roll_no: str, reserve_id: str, db: AsyncSession) -> CancelHoldResponse:
    async def _cancel(cgisessid: str) -> CancelHoldResponse:
        success, message = await koha_cancel_hold(cgisessid, roll_no, reserve_id)
        if success:
            await _invalidate_user_cache(roll_no)
        return CancelHoldResponse(success=success, message=message)

    return await call_with_koha_retry(roll_no, db, _cancel)
