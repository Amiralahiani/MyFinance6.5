"""Compare the API answer with the fields visibly rendered by the Web UI."""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath
from typing import Any

from myfinance_autotest.models import (
    CrossChannelResult,
    DeterministicCheck,
    FailureCategory,
    TestCase,
    ToolExecutionResult,
    Verdict,
)


def _compact(value: Any) -> str:
    raw = "" if value is None else str(value)
    normalised = "".join(
        character
        for character in unicodedata.normalize("NFD", raw.lower())
        if unicodedata.category(character) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", "", normalised)


def _numeric(value: Any) -> str:
    return re.sub(r"[^0-9,.-]", "", "" if value is None else str(value)).replace(",", ".")


def _filename(value: Any) -> str:
    raw = "" if value is None else str(value).replace("\\", "/")
    return PurePosixPath(raw).name.lower()


def _check(check_id: str, name: str, expected: Any, actual: Any) -> DeterministicCheck:
    return DeterministicCheck(
        check_id=check_id,
        name=name,
        passed=expected == actual,
        expected=expected,
        actual=actual,
    )


def compare_api_and_web(
    test_case: TestCase,
    api: ToolExecutionResult,
    web: ToolExecutionResult,
) -> CrossChannelResult:
    """Return PASS only when both channels expose the same visible financial proof."""

    api_response = api.response or {}
    web_response = web.response or {}
    checks = [
        _check("cross.api_http", "api_http_status_is_success", 200, api.http_status),
        _check("cross.web_has_response", "web_has_visible_response", True, bool(web.visible_text and web.response)),
        _check("cross.web_console", "web_console_has_no_errors", [], web.console_errors),
        _check("cross.web_network", "web_network_has_no_errors", [], web.network_errors),
        _check("cross.response_type", "response_type_matches", api_response.get("type"), web_response.get("type")),
    ]
    if api_response.get("type") == "numeric" and web_response.get("type") == "numeric":
        checks.extend(
            [
                _check(
                    "cross.value",
                    "numeric_value_matches",
                    _numeric(api_response.get("value")),
                    _numeric(web_response.get("value")),
                ),
                _check(
                    "cross.year",
                    "reporting_year_matches",
                    api_response.get("reporting_year"),
                    web_response.get("reporting_year"),
                ),
                _check(
                    "cross.page",
                    "source_page_matches",
                    api_response.get("page_number"),
                    web_response.get("page_number"),
                ),
                _check(
                    "cross.excerpt",
                    "source_excerpt_matches",
                    _compact(api_response.get("source_excerpt")),
                    _compact(web_response.get("source_excerpt")),
                ),
                _check(
                    "cross.document",
                    "source_document_matches",
                    _filename(api_response.get("source_document")),
                    _filename(web_response.get("source_document")),
                ),
            ]
        )
    failed = [check for check in checks if check.passed is False]
    categories: list[FailureCategory] = []
    if failed:
        if any(check.name.startswith("web_") for check in failed):
            categories.append(FailureCategory.FRONTEND_ERROR)
        if any(check.name not in {"api_http_status_is_success"} for check in failed):
            categories.append(FailureCategory.CHANNEL_DIVERGENCE)
        if any(check.name == "api_http_status_is_success" for check in failed):
            categories.append(FailureCategory.API_ERROR)
    return CrossChannelResult(
        test_id=test_case.test_id,
        verdict=Verdict.FAIL if failed else Verdict.PASS,
        checks=checks,
        failure_categories=list(dict.fromkeys(categories)),
    )
