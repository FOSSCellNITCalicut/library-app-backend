from app.domains.auth.account_parser import parse_account_page


def _make_koha_account_html(
    name="Adarsh P A",
    email="adarsh_b240119cs@nitc.ac.in",
    loan_count=3,
    loan_limit=8,
    books=None,
    outstanding_fine=150.0,
    fine_history=None,
):
    books = books or []
    fine_history = fine_history or []
    book_rows = ""
    for i, book in enumerate(books):
        book_rows += f"""
          <tr>
            <td class="title">
              <a href="/cgi-bin/koha/opac-detail.pl?biblionumber={book['biblio_id']}">{book['title']} /</a>
            </td>
            <td class="author">{book['author']}</td>
            <td class="date_due">{book['due_date']}</td>
          </tr>"""

    fine_rows = ""
    for item in fine_history:
        fine_rows += f"""
          <tr>
            <td>Late return fine</td>
            <td>{item['date']}</td>
            <td>Rs. {item['amount']:.2f}</td>
            <td>{item['status']}</td>
          </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><title>Your Account</title></head>
<body>
  <span class="userlabel">Welcome,       {name}</span>
  <span class="loggedinusername">Your account</span>

  <div id="user-email">{email}</div>

  <span id="checkoutst-summary">You have {loan_count} items currently checked out of a total limit of {loan_limit}.</span>

  <span id="fines-summary">You owe Rs. {outstanding_fine:.0f}.00 in fines.</span>

  <table id="checkoutst">
    <thead>
      <tr>
        <th>Title</th>
        <th>Author</th>
        <th>Due date</th>
      </tr>
    </thead>
    <tbody>
      {book_rows}
    </tbody>
  </table>

  <table id="fines-table">
    <thead>
      <tr>
        <th>Description</th>
        <th>Date</th>
        <th>Amount</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody>
      {fine_rows}
    </tbody>
  </table>
</body>
</html>"""


class TestParseAccountPage:
    def test_full_account_with_checkouts_and_fines(self):
        html = _make_koha_account_html(
            name="Adarsh P A",
            email="adarsh_b240119cs@nitc.ac.in",
            loan_count=3,
            loan_limit=8,
            books=[
                {"biblio_id": 12345, "title": "Operating System Concepts", "author": "Silberschatz", "due_date": "22/06/2026"},
                {"biblio_id": 67890, "title": "Data Structures", "author": "Mark Allen Weiss", "due_date": "25/06/2026"},
            ],
            outstanding_fine=150.0,
            fine_history=[
                {"amount": 50.0, "date": "10/01/2026", "status": "Paid"},
                {"amount": 100.0, "date": "01/05/2026", "status": "Unpaid"},
            ],
        )
        result = parse_account_page(html, "B240119CS")

        assert result.name == "Adarsh P A"
        assert result.email == "adarsh_b240119cs@nitc.ac.in"
        assert result.loan_count == 3
        assert result.loan_limit == 8
        assert len(result.checked_out_books) == 2
        assert result.checked_out_books[0].biblio_id == 12345
        assert result.checked_out_books[0].title == "Operating System Concepts"
        assert result.checked_out_books[0].author == "Silberschatz"
        assert result.checked_out_books[0].due_date == "22/06/2026"
        assert result.checked_out_books[1].biblio_id == 67890
        assert result.outstanding_fine == 150.0
        assert len(result.fine_history) == 2
        assert result.fine_history[0].amount == 50.0
        assert result.fine_history[0].status == "Paid"
        assert result.fine_history[1].amount == 100.0
        assert result.fine_history[1].status == "Unpaid"

    def test_account_without_checked_out_books(self):
        html = _make_koha_account_html(
            name="Test User",
            loan_count=0,
            loan_limit=8,
            books=[],
        )
        result = parse_account_page(html, "B240000CS")

        assert result.name == "Test User"
        assert len(result.checked_out_books) == 0
        assert result.loan_count == 0
        assert result.loan_limit == 8

    def test_account_without_fines(self):
        html = _make_koha_account_html(
            name="No Fines User",
            loan_count=1,
            loan_limit=8,
            books=[
                {"biblio_id": 111, "title": "Some Book", "author": "Author", "due_date": "30/06/2026"},
            ],
            outstanding_fine=0.0,
            fine_history=[],
        )
        result = parse_account_page(html, "B240001CS")

        assert result.outstanding_fine == 0.0
        assert len(result.fine_history) == 0
        assert len(result.checked_out_books) == 1

    def test_book_status_borrowed(self):
        html = _make_koha_account_html(
            books=[
                {"biblio_id": 12345, "title": "Operating System Concepts", "author": "Silberschatz", "due_date": "22/06/2026"},
            ],
        )
        result = parse_account_page(html, "B240119CS")
        biblio_ids = [b.biblio_id for b in result.checked_out_books]
        assert 12345 in biblio_ids
        assert 99999 not in biblio_ids

    def test_book_status_not_borrowed(self):
        html = _make_koha_account_html(
            books=[
                {"biblio_id": 12345, "title": "Operating System Concepts", "author": "Silberschatz", "due_date": "22/06/2026"},
            ],
        )
        result = parse_account_page(html, "B240119CS")
        biblio_ids = [b.biblio_id for b in result.checked_out_books]
        assert 99999 not in biblio_ids

    def test_name_fallback_to_roll_no_when_missing(self):
        html = """<html><body><p>Some random page without user info</p></body></html>"""
        result = parse_account_page(html, "B240999CS")
        assert result.name == "B240999CS"

    def test_email_none_when_missing(self):
        html = """<html><body><div id="logged-in-info-full">Test User</div></body></html>"""
        result = parse_account_page(html, "B240999CS")
        assert result.email is None

    def test_loan_summary_zero_when_missing(self):
        html = """<html><body><div id="logged-in-info-full">Test User</div></body></html>"""
        result = parse_account_page(html, "B240999CS")
        assert result.loan_count == 0
        assert result.loan_limit == 0

    def test_outstanding_fine_zero_when_missing(self):
        html = """<html><body><div id="logged-in-info-full">Test User</div></body></html>"""
        result = parse_account_page(html, "B240999CS")
        assert result.outstanding_fine == 0.0

    def test_fine_history_empty_when_missing(self):
        html = """<html><body><div id="logged-in-info-full">Test User</div></body></html>"""
        result = parse_account_page(html, "B240999CS")
        assert result.fine_history == []

    def test_fine_history_with_paid_status(self):
        html = _make_koha_account_html(
            fine_history=[
                {"amount": 25.0, "date": "15/03/2026", "status": "paid"},
            ],
        )
        result = parse_account_page(html, "B240119CS")
        assert len(result.fine_history) == 1
        assert result.fine_history[0].status == "Paid"

    def test_checkout_table_title_strips_trailing_slash(self):
        html = _make_koha_account_html(
            books=[
                {"biblio_id": 1, "title": "Book Title /", "author": "Author", "due_date": "01/01/2026"},
            ],
        )
        result = parse_account_page(html, "B240119CS")
        assert result.checked_out_books[0].title == "Book Title"

    def test_name_from_userlabel_with_welcome_prefix(self):
        html = """<html><body><span class="userlabel">Welcome,       SARANG . T</span></body></html>"""
        result = parse_account_page(html, "B251194EC")
        assert result.name == "SARANG . T"

    def test_strips_title_slash_with_spaces(self):
        html = """<!DOCTYPE html>
<html><body>
<div id="logged-in-info-full">Test User</div>
<table id="checkoutst">
<tbody>
<tr>
  <td class="title"><a href="/cgi-bin/koha/opac-detail.pl?biblionumber=42">My Book  /  </a></td>
  <td class="author">Auth</td>
  <td class="date_due">01/01/2026</td>
</tr>
</tbody>
</table>
</body></html>"""
        result = parse_account_page(html, "B240119CS")
        assert result.checked_out_books[0].title == "My Book"
