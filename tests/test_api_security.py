from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from src.api import security


def test_api_key_is_optional_in_development(monkeypatch):
    monkeypatch.setattr(security, "API_KEY", None)
    monkeypatch.setattr(security, "ORBIT_ENV", "development")

    assert security.require_api_key(credentials=None) is None


def test_api_key_is_required_when_configured(monkeypatch):
    monkeypatch.setattr(security, "API_KEY", "test-secret")
    monkeypatch.setattr(security, "ORBIT_ENV", "production")

    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials="test-secret",
    )
    assert security.require_api_key(credentials=credentials) is None


def test_invalid_api_key_is_rejected(monkeypatch):
    monkeypatch.setattr(security, "API_KEY", "test-secret")
    monkeypatch.setattr(security, "ORBIT_ENV", "production")

    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials="wrong-secret",
    )
    try:
        security.require_api_key(credentials=credentials)
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("Invalid API key was accepted")


def test_production_requires_api_key(monkeypatch):
    monkeypatch.setattr(security, "API_KEY", None)
    monkeypatch.setattr(security, "ORBIT_ENV", "production")

    try:
        security.validate_production_configuration()
    except RuntimeError as exc:
        assert "ORBIT_API_KEY" in str(exc)
    else:
        raise AssertionError("Production configuration should fail closed")
