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


@dataclass
class FineHistoryItem:
    amount: float
    date: str
    status: str


@dataclass
class AccountPageData:
    name: str
    email: Optional[str] = None
    loan_count: int = 0
    loan_limit: int = 0
    checked_out_books: list[CheckedOutBook] = field(default_factory=list)
    outstanding_fine: float = 0.0
    fine_history: list[FineHistoryItem] = field(default_factory=list)


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

    return AccountPageData(
        name=name,
        email=email,
        loan_count=loan_count,
        loan_limit=loan_limit,
        checked_out_books=checked_out_books,
        outstanding_fine=outstanding_fine,
        fine_history=fine_history,
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
            return loan_count, loan_limit

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

    if loan_count == 0 and loan_limit == 0:
        logger.warning(
            "Expected profile element 'loan summary' missing for roll_no=%s",
            roll_no,
        )
    return loan_count, loan_limit


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
        title_link = row.find("a", href=lambda h: h and "biblionumber=" in h) if row.find("a") else None
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

        books.append(CheckedOutBook(
            biblio_id=biblio_id,
            title=title,
            author=author,
            due_date=due_date,
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
