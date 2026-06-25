import logging
import re

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.domains.opac_home.schemas import (
    BookArrangementEntry,
    BusinessHourEntry,
    NewArrivalSchema,
    OpacHomeResponse,
    QuoteSchema,
)

logger = logging.getLogger(__name__)

_OPAC_HOMEPAGE_URL = settings.KOHA_OPAC_URL
_TIMEOUT = 15.0


async def fetch_homepage_data() -> OpacHomeResponse:
    async with httpx.AsyncClient(follow_redirects=True, timeout=_TIMEOUT) as client:
        resp = await client.get(_OPAC_HOMEPAGE_URL)
        resp.raise_for_status()
        html = resp.text

    soup = BeautifulSoup(html, "lxml")

    quote = _parse_quote(soup)
    business_hours = _parse_business_hours(soup)
    book_arrangement = _parse_book_arrangement(soup)
    new_arrivals = _parse_new_arrivals_carousel(soup)

    return OpacHomeResponse(
        quote=quote,
        business_hours=business_hours,
        book_arrangement=book_arrangement,
        new_arrivals=new_arrivals,
    )


def _parse_quote(soup: BeautifulSoup) -> QuoteSchema | None:
    try:
        quote_div = soup.find("div", id="daily-quote")
        if not quote_div:
            logger.info("Quote of the day section not found")
            return None

        text_el = quote_div.find("span", id="daily-quote-text")
        source_el = quote_div.find("span", id="daily-quote-source")

        text = text_el.get_text(strip=True) if text_el else None
        source = source_el.get_text(strip=True) if source_el else None

        if not text:
            return None

        return QuoteSchema(text=text, source=source)
    except Exception:
        logger.exception("Failed to parse quote of the day")
        return None


def _parse_business_hours(soup: BeautifulSoup) -> list[BusinessHourEntry]:
    entries: list[BusinessHourEntry] = []
    try:
        hours_table = soup.find(
            "table",
            lambda class_list: class_list and "hours" in " ".join(class_list).lower(),
        )
        if not hours_table:
            header = soup.find(
                "th", string=re.compile(r"Library Business Hours", re.I)
            )
            if header:
                hours_table = header.find_parent("table")

        if not hours_table:
            logger.info("Business hours table not found")
            return entries

        for row in hours_table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            area = cells[0].get_text(" ", strip=True)
            schedule = cells[1].get_text(" ", strip=True)
            if area and schedule:
                entries.append(BusinessHourEntry(area=area, schedule=schedule))

        if not entries:
            logger.warning("Business hours table found but no rows parsed")
    except Exception:
        logger.exception("Failed to parse business hours")

    return entries


def _parse_book_arrangement(soup: BeautifulSoup) -> list[BookArrangementEntry]:
    entries: list[BookArrangementEntry] = []
    try:
        stack_box = soup.find("div", class_="stack-box")
        if not stack_box:
            logger.info("Book arrangement section not found")
            return entries

        content_div = stack_box.find("div", class_="stack-content")
        if not content_div:
            return entries

        text = content_div.get_text("\n", strip=True)
        lines = text.split("\n")
        for i, line in enumerate(lines):
            match = re.match(r"\s*(Stack\s+\d+)", line, re.I)
            if match:
                stack = match.group(1).strip()
                range_text = ""
                if i + 1 < len(lines):
                    range_text = lines[i + 1].lstrip(": \t")
                if range_text:
                    entries.append(
                        BookArrangementEntry(stack=stack, call_range=range_text)
                    )

        if not entries:
            logger.warning("Book arrangement box found but no stacks parsed")
    except Exception:
        logger.exception("Failed to parse book arrangement")

    return entries


def _parse_new_arrivals_carousel(soup: BeautifulSoup) -> list[NewArrivalSchema]:
    books: list[NewArrivalSchema] = []
    try:
        carousel = soup.find("div", id="inlibro-carrousel")
        if not carousel:
            logger.info("New arrivals carousel not found")
            return books

        for link in carousel.find_all("a", href=re.compile(r"biblionumber=\d+")):
            match = re.search(r"biblionumber=(\d+)", link["href"])
            if not match:
                continue

            biblio_id = int(match.group(1))
            title = link.get("title", "") or link.get_text(strip=True)

            cover_url = None
            img = link.find("img")
            if img:
                src = img.get("src")
                if src:
                    cover_url = src

            books.append(
                NewArrivalSchema(
                    biblio_id=biblio_id,
                    title=title,
                    cover_url=cover_url,
                )
            )

        if not books:
            logger.warning("New arrivals carousel found but no books parsed")
    except Exception:
        logger.exception("Failed to parse new arrivals carousel")

    return books
