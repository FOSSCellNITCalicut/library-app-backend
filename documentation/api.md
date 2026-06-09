## Background

We have these two things to use:

- REST API that returns JSON, we can use it for book details and availability
- A search endpoint that returns XML, use this to search for books

The general flow is:

1. Search → get a list of internal book IDs (`biblionumber`)
2. Use those IDs to fetch book details and availability from the REST API
3. Use the ISBN from step 2 to fetch cover images and descriptions from Google Books

## The Two Library Branches

1. LIB
2. MAT
These IDs appear in the availability responses to tell you which branch has a copy of a book.

## 1. Search

```
GET https://opac.nitc.ac.in/cgi-bin/koha/opac-search.pl?q=SEARCH_TERM&format=rss2
```

Replace `SEARCH_TERM` with whatever the user types. 

### Extra parameters you can add

1. `idx` - Search by a specific field instead of everything 
    eg: `kw` (keyword), `ti` (title), `au` (author), `isbn` 
2. `count` - How many results per page 
    eg: `count=20` 
3. `offset` - Which result to start from (for pagination)
    eg: `offset=20` for page 2 
4. `sort_by` - How to sort results 
    eg: `relevance`, `title_az`, `pubdate_desc`

Example with parameters:
```
https://opac.nitc.ac.in/cgi-bin/koha/opac-search.pl?q=python&format=rss2&count=20&offset=0&sort_by=relevance
```

### Result

The response is XML. Here is an example:

```xml
<rss version="2.0">
  <channel>
    <opensearch:totalResults>57</opensearch:totalResults>
    <opensearch:startIndex>0</opensearch:startIndex>
    <opensearch:itemsPerPage>20</opensearch:itemsPerPage>

    <item>
      <title>Head First Python: A Learner's Guide to the Fundamentals of Python Programming/</title>
      <dc:identifier>ISBN:9789355422484</dc:identifier>
      <link>https://opac.nitc.ac.in/cgi-bin/koha/opac-detail.pl?biblionumber=74466</link>
      <description>
        <p>By Barry, Paul. Sebastopol: O' REILLY, 2023 . xxxix,623p. 9789355422484</p>
      </description>
    </item>

    <item>
      <title>Mastering Object-Oriented Python</title>
      <dc:identifier>ISBN:</dc:identifier>
      <link>https://opac.nitc.ac.in/cgi-bin/koha/opac-detail.pl?biblionumber=72816</link>
      <description>
        <p>By Lott, S. F.. Packt Publishing Ltd.</p>
      </description>
    </item>

  </channel>
</rss>
```

### NOTES

1. `itemsPerPage` : Default is 20 
2. `<dc:identifier>` : ISBN (**Can be empty**) 
3. `<link>` : URL to the book's detail page, Contains the `biblionumber`
4. `<description>` : Author, publisher, city, year, page count in string, better to get cleaner metadata from somewhere else 


The `biblionumber` is found in the `<link>` field:

```
https://opac.nitc.ac.in/cgi-bin/koha/opac-detail.pl?biblionumber=74466
                                                                  ^^^^^
                                                            this is the biblionumber
```

### When ISBN is empty

Some books in the system don't have an ISBN recorded. Example from the response:

```xml
<dc:identifier>ISBN:</dc:identifier>   ← empty, nothing after the colon
```

In this case we can just use google books to search using title and author.

## 2. Book Metadata

Once you have a `biblionumber` from search, you can get the full book record.

```
GET https://opac.nitc.ac.in/api/v1/public/biblios/{biblionumber}
Headers: Accept: application/marc-in-json
```

Example:
```
GET https://opac.nitc.ac.in/api/v1/public/biblios/897
Headers: Accept: application/marc-in-json
```

Have to include the `Accept: application/marc-in-json` header, otherwise you get a different format.

### Result
Here is a real respons(book 897):

```json
{
  "leader": "00403nam a2200157Ia 4500",
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
```

### MARC field number translation table

This is how you read the response. Each number maps to a real piece of information:

| Field number | What it contains | Subfield to use | Example value |
|---|---|---|---|
| `020` | ISBN | `a` | `9789355422484` |
| `082` | Call number (shelf location code) | `a` | `510:620` |
| `100` | Author | `a` | `Natarajan, S.` |
| `245` | Title | `a` | `Mathematics for the engineering course /` |
| `260` | Publication info | `a` = city, `b` = publisher, `c` = year | `Madras`, `S.Viswanathan`, `1960` |
| `300` | Physical description / page count | `a` | `4,582p` |
| `365` | Price | `b` | `Rs.8` |
| `653` | Subject / keywords | `a` | `Engineering`, `Mathematics` |
| `008` | Coded data — year is at characters 7–10 | — | `1960` is at position 7 in the string |

> **Note:** Field `020` (ISBN) will be missing for older books that were catalogued before ISBNs were common. Always check if it exists before using it.

> **Note:** The `245` title field often has a trailing ` /` — strip it when displaying.

---

## 3. Book Availability

```
GET https://opac.nitc.ac.in/api/v1/public/biblios/{biblionumber}/items
```

Example:
```
GET https://opac.nitc.ac.in/api/v1/public/biblios/897/items
```

No special headers needed.

### Result

You get a JSON array. Each object in the array is one **physical copy** of the book. If the library has 3 copies, you get 3 objects.

Real response from the NITC library:

```json
[
  {
    "item_id": 12709,
    "biblio_id": 897,
    "callnumber": "510:620 NAT.1-2",
    "checked_out_date": null,
    "home_library_id": "LIB",
    "holding_library_id": "LIB",
    "damaged_status": 0,
    "lost_status": 0,
    "not_for_loan_status": 0,
    "withdrawn": 0,
    "effective_item_type_id": "GEN",
    "acquisition_date": "2016-07-08",
    "serial_issue_number": "vol. 1 part 2",
    "copy_number": null,
    "location": null,
    "public_notes": null,
    "restricted_status": null,
    "external_id": "1"
  }
]
```

### What each field means

| Field | What it means | How to use it |
|---|---|---|
| `item_id` | Unique ID for this specific physical copy | Use this if you need to renew or place a hold |
| `biblio_id` | The book's `biblionumber` | Confirms which book this copy belongs to |
| `callnumber` | The shelf location code — used to physically find the book | Display this to the user |
| `checked_out_date` | When this copy was borrowed | **If `null` → book is on the shelf. If a date → book is checked out** |
| `home_library_id` | Which branch this copy belongs to | Either `LIB` or `MAT` |
| `holding_library_id` | Which branch currently has it | Usually same as `home_library_id` |
| `damaged_status` | Whether the book is damaged | `0` = fine, anything else = damaged |
| `lost_status` | Whether the book is lost | `0` = not lost |
| `not_for_loan_status` | Whether it can be borrowed | `0` = can borrow, `1` = reference only (can't take home) |
| `withdrawn` | Whether the book has been removed from circulation | `0` = still active |
| `acquisition_date` | When the library bought this copy | Mostly for internal use |
| `serial_issue_number` | Volume or part number for multi-volume books | Display if present, e.g. `vol. 1 part 2` |

### How to determine if a book is available

A copy is available to borrow if **all** of these are true:

```
checked_out_date    == null
lost_status         == 0
damaged_status      == 0
not_for_loan_status == 0
withdrawn           == 0
```

If any one of these fails, that copy is not available.

---

## 4. Browse Items (Full Collection)

To show all books in the library without a specific search term, use the items endpoint directly.

```
GET https://opac.nitc.ac.in/api/v1/public/items?_per_page=20&_page=1
```

### Parameters

| Parameter | What it does | Example |
|---|---|---|
| `_per_page` | How many results per page | `_per_page=20` |
| `_page` | Which page to load | `_page=2` |
| `home_library_id` | Filter by branch | `home_library_id=LIB` or `home_library_id=MAT` |

Example — browse only the Maths Department Library, 20 items at a time:
```
GET https://opac.nitc.ac.in/api/v1/public/items?_per_page=20&_page=1&home_library_id=MAT
```

### Result

Same format as the availability response — a JSON array of item objects. Each object has the same fields described in the availability table above. You then use the `biblio_id` from each result to fetch the book's title and author from the MARC endpoint.

---

All endpoints are publicly accessible.