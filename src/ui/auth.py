"""Small shared-password gate for the single-user Streamlit demo."""

import hmac


def password_matches(candidate: str, configured_password: str | None) -> bool:
    """Compare a submitted UI password without timing-sensitive equality."""
    return bool(
        configured_password
        and candidate
        and hmac.compare_digest(candidate, configured_password)
    )
