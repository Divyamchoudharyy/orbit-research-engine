from src.agents.writer import (
    MAX_FINDINGS_CHARS,
    MAX_SOURCES,
    _prepare_findings_text,
    _prepare_sources,
)


def test_prepare_findings_text_stays_within_budget():
    findings = [f"Finding {index}: " + ("evidence " * 500) for index in range(40)]

    prepared = _prepare_findings_text(findings)

    assert len(prepared) <= MAX_FINDINGS_CHARS
    assert "Finding 1" in prepared
    assert "Finding 39" in prepared or "Finding 40" in prepared
    assert "partial" in prepared.lower() or "truncated" in prepared.lower()


def test_prepare_findings_text_handles_empty_and_invalid_items():
    assert _prepare_findings_text([]) == "No research findings were collected."
    assert _prepare_findings_text(["", None, "  "]) == "No research findings were collected."


def test_prepare_findings_text_respects_custom_budget():
    prepared = _prepare_findings_text(["a" * 500], max_chars=100)
    assert len(prepared) <= 100


def test_prepare_sources_deduplicates_filters_and_caps():
    raw = [
        "https://example.com/a",
        "https://example.com/a",
        "javascript:alert(1)",
        "http://example.com/b",
        *[f"https://example.com/{index}" for index in range(100)],
    ]

    sources = _prepare_sources(raw)

    assert sources[0] == "https://example.com/a"
    assert len(sources) <= MAX_SOURCES
    assert len(sources) == len(set(sources))
    assert all(url.startswith(("http://", "https://")) for url in sources)
