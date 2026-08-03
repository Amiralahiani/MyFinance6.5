"""Create and persist regression cases only after a confirmed business defect."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from myfinance_autotest.models import (
    CriticDecision,
    DeterministicValidationResult,
    FailureCategory,
    RegressionCase,
    TestCase,
)

_BUSINESS_FAILURES = {
    FailureCategory.WRONG_BANK,
    FailureCategory.WRONG_YEAR,
    FailureCategory.WRONG_UNIT,
    FailureCategory.UNSUPPORTED_VALUE,
    FailureCategory.SOURCE_MISMATCH,
    FailureCategory.ARITHMETIC_ERROR,
    FailureCategory.CONTEXT_LOSS,
    FailureCategory.CHANNEL_DIVERGENCE,
    FailureCategory.CONTRACT_VIOLATION,
    FailureCategory.PERSONAL_DATA_SCOPE,
    FailureCategory.UNSUPPORTED_COMPARISON,
    FailureCategory.UNSUPPORTED_CONVERSION,
}


def regression_from_confirmed_defect(
    test_case: TestCase,
    validation: DeterministicValidationResult,
    critic: CriticDecision,
) -> RegressionCase | None:
    """Create a replayable regression candidate only when evidence is sufficient."""

    evidence = validation.grounding.evidence if validation.grounding else []
    category = next(
        (item for item in validation.failure_categories if item in _BUSINESS_FAILURES),
        None,
    )
    if not (critic.create_regression_test and critic.verdict_confirmed and category):
        return None
    duplicate_key = "|".join(
        [
            test_case.bank_id or "unknown-bank",
            str(test_case.reporting_year or "unknown-year"),
            test_case.metric_id or "unknown-metric",
            category.value,
        ]
    )
    return RegressionCase(
        regression_id=f"REG-{test_case.test_id}-{category.value}",
        source_test_id=test_case.test_id,
        created_at=datetime.now(UTC),
        test_case=test_case,
        failure_category=category,
        evidence=evidence,
        success_criteria=(
            [
                "Le validateur déterministe ne détecte plus cette catégorie d’anomalie.",
                "La réponse reste reliée au même fait auto-validé et à sa preuve PDF.",
            ]
            if evidence
            else [
                "La réponse respecte le contrat de sûreté de ce scénario.",
                "La réponse ne fournit aucune valeur ou affirmation interdite.",
            ]
        ),
        duplicate_key=duplicate_key,
    )


@dataclass(frozen=True)
class RegressionRegistration:
    regression: RegressionCase
    created: bool
    path: Path


class RegressionRegistry:
    """Small atomic JSON registry, intentionally independent from an LLM."""

    def __init__(self, root: Path) -> None:
        self.path = root / "regressions.json"

    def _read(self) -> list[RegressionCase]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return [RegressionCase.model_validate(item) for item in payload]

    def register(self, regression: RegressionCase) -> RegressionRegistration:
        existing = self._read()
        duplicate = next((item for item in existing if item.duplicate_key == regression.duplicate_key), None)
        if duplicate is not None:
            return RegressionRegistration(regression=duplicate, created=False, path=self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        updated = [*existing, regression]
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps([item.model_dump(mode="json") for item in updated], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return RegressionRegistration(regression=regression, created=True, path=self.path)
