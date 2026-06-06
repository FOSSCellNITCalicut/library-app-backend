import re


class MarcParser:
    def _find_marc_fields(self, fields: list, tag: str) -> list[dict | str]:
        """
        Returns ALL matching MARC fields for a tag. Example: tag=653 -> multiple category fields
        """
        matches = []

        for field in fields:
            if not isinstance(field, dict):
                continue
            value = field.get(tag)
            
            if value:
                matches.append(value)
        
        return matches
    
    def _marc_subfields(self, field_data: dict | None, code: str) -> list[str]:
        if not field_data:
            return []

        results = []

        subfields = field_data.get("subfields", [])

        for sub in subfields:
            if not isinstance(sub, dict):
                continue
            
            value = sub.get(code)
            if value:
                cleaned = str(value).strip()
                if cleaned:
                    results.append(cleaned)
        
        return results
    
    def _dedupe(self, values: list[str]) -> list[str]:
        """Remove duplicates while preserving order"""
        return list(dict.fromkeys(values))
    
    def _first_subfield(self, field: dict | None, code: str) -> str | None:
        subfields = self._marc_subfields(field, code)
        return subfields[0] if subfields else None
    
    def _parse_year(self, text: str | None) -> int | None:
        if not text:
            return None

        match = re.search(r"(18|19|20)\d{2}", text)

        if match:
            return int(match.group())

        return None
    
    def _extract_year(self, fields: list) -> int | None:
        """
        Prefer:
            260$c
            264$c
        Fallback:
            008 positions 7-10
        """
        # Try 264$c
        field_264 = self._find_marc_fields(fields, "264")
        value = self._first_subfield(field_264[0], "c") if field_264 else None
        year = self._parse_year(value)

        if year:
            return year

        # Try 260$c
        field_260 = self._find_marc_fields(fields, "260")
        value = self._first_subfield(field_260[0], "c") if field_260 else None
        year = self._parse_year(value)

        if year:
            return year

        # Fallback to 008 fixed field
        field_008 = self._find_marc_fields(fields, "008")
        if field_008:
            raw = field_008[0]

            if isinstance(raw, str) and len(raw) >= 11:
                year_str = raw[7:11]

                if year_str.isdigit():
                    return int(year_str)

        return None
    
    def _clean_title(self, title: str | None) -> str | None:
        if not title:
            return None
        
        # Remove trailing slash + trailing punctuation
        title = re.sub(r"\s*/\s*$", "", title)
        return title.strip(" /:;,")
    
    def _clean_isbn(self, isbn: str | None) -> str | None:
        if not isbn:
            return None

        # Remove qualifiers like:
        # "9781234567890 (pbk.)"
        isbn = isbn.split(" ")[0]

        # Keep digits/X only
        isbn = re.sub(r"[^0-9Xx]", "", isbn)

        return isbn or None
    
    def _clean_text(self, text: str | None) -> str | None:
        if not text:
            return None

        return re.sub(r"[ /:;,]+$", "", text.strip())

    def parse_marc_to_dict(self, marc_data: dict) -> dict:
        if not isinstance(marc_data, dict):
            return {}
        
        fields = marc_data.get("fields") or []

        # Title
        title_field = self._find_marc_fields(fields, "245")
        title = self._first_subfield(title_field[0], 'a') if title_field else None
        cleaned_title = self._clean_title(title)
        
        # Author
        authors = []

        for tag in ["100", "110", "111", "700", "710", "711"]:
            for field in self._find_marc_fields(fields, tag):
                authors.extend(self._marc_subfields(field, "a"))

        authors = self._dedupe(authors)

        # ISBN - can be multiple
        isbns = []

        for field in self._find_marc_fields(fields, "020"):
            for isbn in self._marc_subfields(field, "a"):
                cleaned = self._clean_isbn(isbn)

                if cleaned:
                    isbns.append(cleaned)

        isbns = self._dedupe(isbns)

        # Publisher
        publisher = None

        for tag in ["264", "260"]:
            matched = self._find_marc_fields(fields, tag)

            if matched:
                publisher = self._first_subfield(matched[0], "b")

                if publisher:
                    publisher = self._clean_text(publisher)
                    break

        # Categories - can be multiple
        categories = []

        for field in self._find_marc_fields(fields, "653"):
            for category in self._marc_subfields(field, "a"):
                cleaned = self._clean_text(category)

                if cleaned:
                    categories.append(cleaned)

        categories = self._dedupe(categories)

        # Year
        published_year = self._extract_year(fields)

        return {
            "title": cleaned_title,
            "authors": authors or None,
            "isbns": isbns or None,
            "publisher": publisher,
            "categories": categories or None,
            "year": published_year,
        }
    
marc_parser = MarcParser()

if __name__ == "__main__":
    parser = MarcParser()
    result = parser.parse_marc_to_dict(
        {
            "fields": [
            { "008": "160708s1960    xxu           000 0 eng d" },
            { "082": { "ind1": " ", "ind2": " ", "subfields": [ { "a": "510:620" } ] } },
            { "100": { "ind1": " ", "ind2": " ", "subfields": [ { "a": "Natarajan, S." } ] } },
            { "245": { "ind1": " ", "ind2": " ", "subfields": [
                { "a": "Mathematics for the engineering course /" },
                { "c": " by S. Natarajan" }
            ]}},
            { "260": { "ind1": " ", "ind2": " ", "subfields": [
                { "a": "Madras :" },
                { "b": "S.Viswanathan, " },
                { "c": "1960." }
            ]}},
            { "300": { "ind1": " ", "ind2": " ", "subfields": [ { "a": "4,582p" } ] } },
            { "365": { "ind1": " ", "ind2": " ", "subfields": [ { "b": "Rs.8" } ] } },
            { "653": { "ind1": " ", "ind2": " ", "subfields": [ { "a": "Engineering" } ] } },
            { "653": { "ind1": " ", "ind2": " ", "subfields": [ { "a": "Mathematics" } ] } },
            { "999": { "ind1": " ", "ind2": " ", "subfields": [ { "c": "897" }, { "d": "897" } ] } }
            ]
        }
    )

    print(result)
