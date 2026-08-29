import logging
import re
from datetime import date

import httpx
from bs4 import BeautifulSoup

from app.domains.opac_home.schemas import (
    BusinessHourEntry,
    NewArrivalSchema,
    OpacHomeResponse,
    QuoteSchema,
)

logger = logging.getLogger(__name__)

_LIB_HOME_URL = "https://library.nitc.ac.in/"
_TIMEOUT = 15.0

_LOCAL_QUOTES: list[dict[str, str | None]] = [
    {"text": "A library is not a luxury but one of the necessities of life.", "source": "Henry Ward Beecher"},
    {"text": "The only thing you absolutely have to know, is the location of the library.", "source": "Albert Einstein"},
    {"text": "I have always imagined that Paradise will be a kind of library.", "source": "Jorge Luis Borges"},
    {"text": "When in doubt, go to the library.", "source": "J.K. Rowling"},
    {"text": "A room without books is like a body without a soul.", "source": "Marcus Tullius Cicero"},
    {"text": "The reading of all good books is like a conversation with the finest minds of past centuries.", "source": "René Descartes"},
    {"text": "Libraries store the energy that fuels the imagination.", "source": "Sidney Sheldon"},
    {"text": "Books are a uniquely portable magic.", "source": "Stephen King"},
    {"text": "There is no friend as loyal as a book.", "source": "Ernest Hemingway"},
    {"text": "The more that you read, the more things you will know.", "source": "Dr. Seuss"},
    {"text": "A reader lives a thousand lives before he dies.", "source": "George R.R. Martin"},
    {"text": "Books are the plane, and the train, and the road.", "source": "Anna Quindlen"},
    {"text": "In the case of good books, the point is not to see how many of them you can get through, but rather how many can get through to you.", "source": "Mortimer J. Adler"},
    {"text": "The library is a gathering pool of narratives and of the people who come to find them.", "source": "Alice Munro"},
    {"text": "Until I feared I would lose it, I never loved to read.", "source": "Harper Lee"},
]


_LIBRARY_HOURS: list[BusinessHourEntry] = [
    BusinessHourEntry(area="Stacks 1", schedule="8:00 AM \u2013 8:00 PM (Mon\u2013Fri), 9:00 AM \u2013 5:30 PM (Sat\u2013Sun)"),
    BusinessHourEntry(area="Stacks 2 & 3", schedule="9:00 AM \u2013 8:00 PM (Mon\u2013Fri), 9:00 AM \u2013 5:30 PM (Sat\u2013Sun)"),
    BusinessHourEntry(area="Digital Library & Reading Space", schedule="8:00 AM \u2013 12:00 AM (Mon\u2013Sun)"),
]


async def fetch_homepage_data() -> OpacHomeResponse:
    new_arrivals = await _fetch_new_arrivals()
    quote = _get_daily_quote()

    return OpacHomeResponse(
        quote=quote,
        business_hours=_LIBRARY_HOURS,
        book_arrangement=[],
        new_arrivals=new_arrivals,
    )


def _get_daily_quote() -> QuoteSchema:
    today = date.today().toordinal()
    quote_data = _LOCAL_QUOTES[today % len(_LOCAL_QUOTES)]
    return QuoteSchema(text=quote_data["text"], source=quote_data.get("source"))


async def _fetch_new_arrivals() -> list[NewArrivalSchema]:
    books: list[NewArrivalSchema] = []
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=_TIMEOUT) as client:
            resp = await client.get(_LIB_HOME_URL)
            resp.raise_for_status()
            html = resp.text

        soup = BeautifulSoup(html, "lxml")

        for link in soup.find_all("a", href=re.compile(r"biblionumber=\d+")):
            match = re.search(r"biblionumber=(\d+)", link["href"])
            if not match:
                continue

            biblio_id = int(match.group(1))

            img = link.find("img")
            if not img:
                continue

            title = img.get("alt", "").strip()
            cover_url = img.get("src")

            if not title:
                continue

            books.append(
                NewArrivalSchema(
                    biblio_id=biblio_id,
                    title=title,
                    cover_url=cover_url,
                )
            )

        if not books:
            logger.warning("No new arrivals found on library.nitc.ac.in")
    except Exception:
        logger.exception("Failed to fetch new arrivals from library.nitc.ac.in")

    return books
