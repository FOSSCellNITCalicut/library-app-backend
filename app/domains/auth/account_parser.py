import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class CheckedOutBook:
    biblio_id: int
    title: str
    author: str
    due_date: str
    issue_id: int = 0
    renewals_allowed: int = 0
    renewals_remaining: int = 0


@dataclass
class FineHistoryItem:
    amount: float
    date: str
    status: str


@dataclass
class HoldItem:
    """
    One row from the patron's "Holds" tab on opac-user.pl, plus the csrf_token
    scoped to that specific row's cancel form -- Koha generates a fresh token
    per form (Koha.GenerateCSRF), not one shared per page, so it has to be
    read out of the same <form> as the matching reserve_id rather than reused
    across rows.
    """
    reserve_id: str
    biblio_id: int
    title: str = ""
    branch: str = ""
    status: str = ""
    csrf_token: Optional[str] = None


@dataclass
class AccountPageData:
    name: str
    email: Optional[str] = None
    loan_count: int = 0
    loan_limit: int = 0
    checked_out_books: list[CheckedOutBook] = field(default_factory=list)
    outstanding_fine: float = 0.0
    fine_history: list[FineHistoryItem] = field(default_factory=list)
    holds: list[HoldItem] = field(default_factory=list)
    renewal_csrf_token: Optional[str] = None


@dataclass
class PickupBranch:
    code: str
    name: str
    is_default: bool = False


@dataclass
class HoldFormData:
    csrf_token: Optional[str] = None
    branches: list[PickupBranch] = field(default_factory=list)
    unavailable_reason: Optional[str] = None

    @property
    def holdable(self) -> bool:
        return bool(self.csrf_token) and bool(self.branches)


def parse_charges_page(html: str, roll_no: str) -> AccountPageData:
    """
    Parse the Koha OPAC charges page (opac-account.pl).
    Returns AccountPageData with outstanding_fine and fine_history populated.
    Other fields (name, email, checkouts) are left at defaults.
    """
    soup = BeautifulSoup(html, "lxml")
    outstanding_fine = _parse_outstanding_fine(soup, roll_no)
    fine_history = _parse_fine_history(soup, roll_no)
    return AccountPageData(
        name=roll_no,
        outstanding_fine=outstanding_fine,
        fine_history=fine_history,
    )


def parse_account_page(html: str, roll_no: str) -> AccountPageData:
    """
    Parse the authenticated Koha OPAC account page (opac-user.pl).
    Returns an AccountPageData with all extracted fields.
    Logs warnings when expected elements are missing.
    """
    soup = BeautifulSoup(html, "lxml")

    name = _parse_name(soup, roll_no)
    email = _parse_email(soup, roll_no)
    loan_count, loan_limit = _parse_loan_summary(soup, roll_no)
    checked_out_books = _parse_checked_out_books(soup, roll_no)
    outstanding_fine = _parse_outstanding_fine(soup, roll_no)
    fine_history = _parse_fine_history(soup, roll_no)
    holds = _parse_holds(soup, roll_no)
    renewal_csrf_token = _parse_renewal_csrf_token(soup, roll_no)

    return AccountPageData(
        name=name,
        email=email,
        loan_count=loan_count,
        loan_limit=loan_limit,
        checked_out_books=checked_out_books,
        outstanding_fine=outstanding_fine,
        fine_history=fine_history,
        holds=holds,
        renewal_csrf_token=renewal_csrf_token,
    )


def _parse_name(soup: BeautifulSoup, roll_no: str) -> str:
    userlabel = soup.find(class_="userlabel")
    if userlabel:
        text = userlabel.get_text(strip=True)
        text = re.sub(r'^Welcome\s*,?\s*', '', text, flags=re.I).strip()
        if text:
            return text

    for selector in [
        {"id": "logged-in-info-full"},
        {"class": "loggedinusername"},
        {"id": "logged-in-name"},
    ]:
        tag = soup.find(attrs=selector)
        if tag and tag.get_text(strip=True):
            return tag.get_text(strip=True)

    for selector in [
        {"id": "user-info"},
        {"class": "user-info"},
    ]:
        tag = soup.find(attrs=selector)
        if tag:
            text = tag.get_text(" ", strip=True)
            if text:
                return text.split("\n")[0].strip()

    logger.warning("Expected profile element 'display name' missing for roll_no=%s", roll_no)
    return roll_no


def _parse_email(soup: BeautifulSoup, roll_no: str) -> Optional[str]:
    email_selectors = [
        {"id": "user-email"},
        {"class": "user-email"},
    ]
    for selector in email_selectors:
        tag = soup.find(attrs=selector)
        if tag:
            text = tag.get_text(strip=True)
            if text and "@" in text:
                return text

    body_text = soup.get_text()
    email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', body_text)
    if email_match:
        return email_match.group(0)

    logger.warning("Expected profile element 'email' missing for roll_no=%s", roll_no)
    return None


# NITC Central Library borrowing policy (General Books only -- Special
# Collection has separate, shorter quotas this app doesn't model yet).
# Not exposed anywhere in Koha's OPAC HTML, so it can't be scraped -- this is
# the published policy table, keyed by the roll number's category prefix.
# Source: NITC library "Borrowing Limit" policy page (confirmed by team,
# 2026-06). Update here if the library changes circulation policy.
_LOAN_LIMIT_BY_ROLL_PREFIX = {
    "B": 8,   # UG Students (GEN)
    "M": 10,  # PG Students (GEN)
    "P": 10,  # PhD (Full Time/Part Time)
}
_DEFAULT_LOAN_LIMIT = 8  # fallback for roll numbers that don't match B/M/P (e.g. staff logins)


def _loan_limit_for_roll_no(roll_no: str) -> int:
    prefix = roll_no[:1].upper() if roll_no else ""
    return _LOAN_LIMIT_BY_ROLL_PREFIX.get(prefix, _DEFAULT_LOAN_LIMIT)


def _parse_loan_summary(soup: BeautifulSoup, roll_no: str) -> tuple[int, int]:
    loan_count = 0
    loan_limit = 0

    summary_selectors = [
        {"id": "checkoutst-summary"},
        {"class": "checkout-summary"},
        {"id": "issues-summary"},
    ]
    for selector in summary_selectors:
        tag = soup.find(attrs=selector)
        if tag:
            text = tag.get_text(strip=True)
            numbers = re.findall(r'\d+', text)
            if len(numbers) >= 1:
                loan_count = int(numbers[0])
            if len(numbers) >= 2:
                loan_limit = int(numbers[1])
            return loan_count, loan_limit or _loan_limit_for_roll_no(roll_no)

    checkout_tab = soup.find(string=re.compile(r'Checked\s*out\s*\((\d+)\)', re.I))
    if checkout_tab:
        match = re.search(r'Checked\s*out\s*\((\d+)\)', checkout_tab, re.I)
        if match:
            loan_count = int(match.group(1))

    if not checkout_tab:
        checkout_table = soup.find("table", id="checkoutst")
        if checkout_table:
            tbody = checkout_table.find("tbody")
            rows = tbody.find_all("tr", recursive=False) if tbody else checkout_table.find_all("tr", recursive=False)
            inferred = len(rows) if rows else 0
            if loan_count == 0:
                loan_count = inferred

    if loan_count == 0:
        logger.warning(
            "Expected profile element 'loan summary' missing for roll_no=%s",
            roll_no,
        )
    return loan_count, loan_limit or _loan_limit_for_roll_no(roll_no)


def _parse_checked_out_books(soup: BeautifulSoup, roll_no: str) -> list[CheckedOutBook]:
    books: list[CheckedOutBook] = []

    checkout_table = soup.find("table", id="checkoutst")
    if checkout_table is None:
        checkout_table = soup.find("table", class_="items_table")
    if checkout_table is None:
        checkout_table = soup.find("table", {"id": re.compile(r"checkout", re.I)})

    if checkout_table is None:
        logger.warning("Expected profile element 'checkouts table' missing for roll_no=%s", roll_no)
        return books

    tbody = checkout_table.find("tbody")
    rows = tbody.find_all("tr") if tbody else checkout_table.find_all("tr")

    for row in rows:
        title_link = row.find("a", href=lambda h: h and "biblionumber=" in h)
        if title_link is None:
            title_link = row.find("a")
        if title_link is None:
            continue

        href = title_link.get("href", "")
        biblio_match = re.search(r'biblionumber=(\d+)', href)
        biblio_id = int(biblio_match.group(1)) if biblio_match else 0

        title = title_link.get_text(strip=True).rstrip(" /")

        author_cells = row.find_all("td")
        author = ""
        due_date = ""
        for cell in author_cells:
            cell_class = " ".join(cell.get("class", []))
            cell_text = cell.get_text(strip=True)
            if "author" in cell_class:
                author = cell_text
            elif "date_due" in cell_class or "due" in cell_class or "date" in cell_class:
                due_date = cell_text
            elif not author and cell is not title_link.parent:
                pass

        if not author:
            author_cell = row.find("td", class_=re.compile(r"author", re.I))
            if author_cell:
                author = author_cell.get_text(strip=True)

        if not due_date:
            due_cell = row.find("td", class_=re.compile(r"due|date_due", re.I))
            if due_cell:
                due_date = due_cell.get_text(strip=True)

        # issue_id: Koha's loan record ID, needed by opac-renew.pl.
        # Primary: checkbox input[name="issue"] in the row (batch renewal form).
        # Secondary: data-issue attribute on the per-item renew link.
        # Tertiary: trailing digits from the <tr id="..."> attribute.
        issue_id = 0
        issue_input = row.find("input", attrs={"name": "issue"})
        if issue_input:
            try:
                issue_id = int(issue_input.get("value", "0"))
            except ValueError:
                pass
        if issue_id == 0:
            renew_link = row.find("a", attrs={"data-op": "cud-renew"})
            if renew_link:
                try:
                    issue_id = int(renew_link.get("data-issue", "0"))
                except ValueError:
                    pass
        if issue_id == 0:
            row_id = row.get("id", "")
            m = re.search(r"(\d+)$", row_id)
            if m:
                try:
                    issue_id = int(m.group(1))
                except ValueError:
                    pass

        # Renewal counts: Koha renders a <span class="renewals"> inside
        # <td class="renew"> with text "X of Y renewals remaining".
        # Fall back to searching the whole row in case NITC's template
        # uses different class names or nesting.
        renewals_allowed = 0
        renewals_remaining = 0
        renew_cell = row.find("td", class_=re.compile(r"renew", re.I))
        renewal_span = (
            renew_cell.find("span", class_=re.compile(r"renewal", re.I))
            if renew_cell else None
        ) or row.find("span", class_=re.compile(r"renewal", re.I))

        if renewal_span:
            text = renewal_span.get_text(strip=True)
            m = re.search(r'(\d+)\s*(?:of|/)\s*(\d+)', text)
            if m:
                renewals_remaining = int(m.group(1))
                renewals_allowed = int(m.group(2))
            else:
                m = re.search(r'(\d+)', text)
                if m:
                    renewals_remaining = int(m.group(1))
        elif renew_cell:
            text = renew_cell.get_text(strip=True)
            m = re.search(r'(\d+)\s*(?:of|/)\s*(\d+)', text)
            if m:
                renewals_remaining = int(m.group(1))
                renewals_allowed = int(m.group(2))

        books.append(CheckedOutBook(
            biblio_id=biblio_id,
            title=title,
            author=author,
            due_date=due_date,
            issue_id=issue_id,
            renewals_allowed=renewals_allowed,
            renewals_remaining=renewals_remaining,
        ))

    if not books:
        logger.warning("Expected profile element 'checkout rows' missing for roll_no=%s", roll_no)

    return books


def _find_fines_table(soup: BeautifulSoup) -> BeautifulSoup | None:
    for selector in [
        {"id": "fines-table"},
        {"id": "account-table"},
        {"class": "fines_table"},
        {"class": "account-table"},
        {"id": re.compile(r"fine|charge", re.I)},
    ]:
        table = soup.find("table", attrs=selector)
        if table:
            return table
    return None


def _build_column_index(table: BeautifulSoup) -> dict[str, int]:
    """
    Read <thead><tr><th> headers and build {normalized_header: index} map.
    Returns empty dict if no <thead> found.
    """
    thead = table.find("thead")
    if thead is None:
        return {}
    header_cells = thead.find_all("th")
    col_map: dict[str, int] = {}
    for idx, th in enumerate(header_cells):
        text = th.get_text(strip=True).lower()
        if "date" in text:
            col_map["date"] = idx
        elif "amount" in text or "fine" in text or "charge" in text or "total" in text:
            col_map["amount"] = idx
        elif "status" in text or "state" in text or "paid" in text:
            col_map["status"] = idx
    return col_map


def _parse_outstanding_fine(soup: BeautifulSoup, roll_no: str) -> float:
    fine_selectors = [
        {"id": "fines-summary"},
        {"class": "fine-summary"},
        {"id": "your-account-fines"},
        {"class": "account-fines"},
    ]
    for selector in fine_selectors:
        tag = soup.find(attrs=selector)
        if tag:
            text = tag.get_text(strip=True)
            match = re.search(
                r'(?:owe|due|outstanding|total|amount)\s*:?\s*(?:rs\.?\s*)?([\d,]+\.?\d*)',
                text, re.I,
            )
            if match:
                try:
                    return float(match.group(1).replace(",", ""))
                except ValueError:
                    pass
            amounts = re.findall(r'\d[\d,.]*', text)
            if amounts:
                try:
                    return float(amounts[0].replace(",", ""))
                except ValueError:
                    pass

    fines_table = _find_fines_table(soup)
    if fines_table:
        col_map = _build_column_index(fines_table)
        amount_idx = col_map.get("amount", 2)
        tbody = fines_table.find("tbody")
        rows = tbody.find_all("tr") if tbody else fines_table.find_all("tr")
        total = 0.0
        for row in rows:
            cells = row.find_all("td")
            if amount_idx < len(cells):
                amount_text = cells[amount_idx].get_text(strip=True)
                amounts = re.findall(r'\d[\d,.]*', amount_text)
                if amounts:
                    try:
                        total += float(amounts[0].replace(",", ""))
                    except ValueError:
                        pass
        if total > 0:
            return total

    logger.warning("Expected profile element 'outstanding fine' missing for roll_no=%s", roll_no)
    return 0.0


def _parse_fine_history(soup: BeautifulSoup, roll_no: str) -> list[FineHistoryItem]:
    items: list[FineHistoryItem] = []

    fines_table = _find_fines_table(soup)
    if fines_table is None:
        logger.warning("Expected profile element 'fine history table' missing for roll_no=%s", roll_no)
        return items

    col_map = _build_column_index(fines_table)
    amount_idx = col_map.get("amount", 2)
    date_idx = col_map.get("date", 1)
    status_idx = col_map.get("status", 3)

    tbody = fines_table.find("tbody")
    rows = tbody.find_all("tr") if tbody else fines_table.find_all("tr")

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < max(amount_idx, date_idx, status_idx) + 1:
            continue

        amount_text = cells[amount_idx].get_text(strip=True)
        amounts = re.findall(r'\d[\d,.]*', amount_text)
        amount = float(amounts[0].replace(",", "")) if amounts else 0.0

        date_text = cells[date_idx].get_text(strip=True)

        status_text = cells[status_idx].get_text(strip=True)

        status = "Unpaid"
        if status_text:
            lower = status_text.lower()
            if "unpaid" in lower or "outstanding" in lower or "open" in lower:
                status = "Unpaid"
            elif "paid" in lower or "completed" in lower or "closed" in lower:
                status = "Paid"
            else:
                status = status_text

        items.append(FineHistoryItem(
            amount=amount,
            date=date_text,
            status=status,
        ))

    if not items:
        logger.warning("Expected profile element 'fine history rows' missing for roll_no=%s", roll_no)

    return items


def _parse_renewal_csrf_token(soup: BeautifulSoup, roll_no: str) -> Optional[str]:
    """Extract the CSRF token from the renewal form (id="renewall") on opac-user.pl."""
    renew_form = soup.find("form", id="renewall")
    if renew_form is None:
        renew_form = soup.find("form", attrs={"action": re.compile(r"opac-renew", re.I)})
    if renew_form:
        token_tag = renew_form.find("input", attrs={"name": "csrf_token"})
        if token_tag:
            return token_tag.get("value")
    logger.info("Renewal form CSRF token not found for roll_no=%s (no checked-out books?)", roll_no)
    return None


def _parse_holds(soup: BeautifulSoup, roll_no: str) -> list[HoldItem]:
    """
    Parse the patron's current holds off opac-user.pl.

    Anchored on each hold's cancel form (id="delete_hold_<reserve_id>")
    rather than the surrounding table, since that form's hidden inputs
    (reserve_id, biblionumber, csrf_token) are exactly what cancel_hold()
    needs and are far more stable than guessing table column order. Title/
    branch/status are read from the enclosing <tr> as best-effort display
    text -- if that lookup fails the hold is still cancellable, just with
    blank labels.
    """
    holds: list[HoldItem] = []

    cancel_forms = soup.find_all("form", id=re.compile(r"^delete_hold_"))
    for form in cancel_forms:
        reserve_id_tag = form.find("input", attrs={"name": "reserve_id"})
        reserve_id = reserve_id_tag.get("value", "").strip() if reserve_id_tag else ""
        if not reserve_id:
            continue

        biblio_tag = form.find("input", attrs={"name": "biblionumber"})
        biblio_id = 0
        if biblio_tag:
            try:
                biblio_id = int(biblio_tag.get("value", "0"))
            except ValueError:
                pass

        token_tag = form.find("input", attrs={"name": "csrf_token"})
        csrf_token = token_tag.get("value") if token_tag else None

        title = ""
        branch = ""
        status = ""
        row = form.find_parent("tr")
        if row:
            title_cell = row.find(attrs={"class": re.compile(r"title", re.I)})
            if title_cell:
                title = title_cell.get_text(strip=True)
            branch_cell = row.find(attrs={"class": re.compile(r"branch", re.I)})
            if branch_cell:
                branch = branch_cell.get_text(strip=True)
            status_cell = row.find(attrs={"class": re.compile(r"status", re.I)})
            if status_cell:
                status = status_cell.get_text(strip=True)

        holds.append(HoldItem(
            reserve_id=reserve_id,
            biblio_id=biblio_id,
            title=title,
            branch=branch,
            status=status,
            csrf_token=csrf_token,
        ))

    # Not a warning -- most patrons have zero active holds most of the time,
    # unlike e.g. loan summary where "missing" usually means a parsing bug.
    if not holds:
        logger.info("No active holds found for roll_no=%s (or holds markup unrecognized)", roll_no)

    return holds


def _extract_hold_unavailable_reason(soup: BeautifulSoup) -> Optional[str]:
    """
    Best-effort extraction of the reason Koha shows when a hold can't be placed.
    Koha renders these as Bootstrap alert divs inside the page body.
    """
    for selector in [".alert-danger", ".alert-warning", ".alert"]:
        el = soup.select_one(selector)
        if el:
            text = re.sub(r'\s+', ' ', el.get_text(separator=" ", strip=True)).strip()
            if text:
                return text[:300]
    return None


def parse_hold_form(html: str, roll_no: str, biblio_id: int) -> HoldFormData:
    """
    Parse Koha's opac-reserve.pl "place a hold" form (GET response).

    Extracts the csrf_token hidden input (required on the confirm POST) and
    the pickup-branch <select> options.
    """
    soup = BeautifulSoup(html, "lxml")

    token_tag = soup.find("input", attrs={"name": "csrf_token"})
    csrf_token = token_tag.get("value") if token_tag else None
    if not csrf_token:
        logger.warning(
            "Expected hold form element 'csrf_token' missing for roll_no=%s biblio_id=%s",
            roll_no, biblio_id,
        )

    branches: list[PickupBranch] = []
    branch_select = soup.find("select", attrs={"name": "branch"})
    if branch_select is None:
        branch_select = soup.find("select", attrs={"id": re.compile(r"branch", re.I)})

    if branch_select:
        for option in branch_select.find_all("option"):
            code = option.get("value", "").strip()
            if not code:
                continue
            branches.append(PickupBranch(
                code=code,
                name=option.get_text(strip=True) or code,
                is_default=option.has_attr("selected"),
            ))

    if not branches:
        logger.warning(
            "Expected hold form element 'pickup branch list' missing for roll_no=%s biblio_id=%s",
            roll_no, biblio_id,
        )

    unavailable_reason: Optional[str] = None
    if not csrf_token or not branches:
        unavailable_reason = _extract_hold_unavailable_reason(soup)

    return HoldFormData(csrf_token=csrf_token, branches=branches, unavailable_reason=unavailable_reason)
