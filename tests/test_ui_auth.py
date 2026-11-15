from src.ui.auth import password_matches


def test_ui_password_matches():
    assert password_matches("correct-horse", "correct-horse")


def test_ui_password_rejects_wrong_or_empty_values():
    assert not password_matches("wrong", "correct-horse")
    assert not password_matches("", "correct-horse")
    assert not password_matches("anything", None)
