import pytest

from app.domains.auth.google_oauth import extract_student_roll_no


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("alex_B23CS001@nitc.ac.in", "B23CS001"),
        ("alex.smith_m24ec012@NITC.AC.IN", "M24EC012"),
        ("staff_john@nitc.ac.in", None),
        ("alex_B23CS001@example.com", None),
        ("_B23CS001@nitc.ac.in", None),
        ("alex_@nitc.ac.in", None),
        ("alex_ABC@nitc.ac.in", None),
        ("alex__B23CS001@nitc.ac.in", "B23CS001"),
    ],
)
def test_extract_student_roll_no(email: str, expected: str | None) -> None:
    assert extract_student_roll_no(email) == expected
