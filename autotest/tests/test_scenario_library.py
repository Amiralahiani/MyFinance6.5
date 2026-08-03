"""The generated library must account for every official report and coverage gap."""

from myfinance_autotest.models import Channel
from myfinance_autotest.models import TestCategory as AutotestCategory
from myfinance_autotest.scenarios.library import build_scenario_library, write_scenario_library


def test_library_covers_all_reports_with_fact_and_cross_channel_scenarios() -> None:
    library = build_scenario_library()

    assert library.report_count == 25
    assert library.auto_validated_fact_scenario_count == 174
    assert library.cross_channel_scenario_count == 25
    assert library.missing_fact_scenario_count == 1
    assert library.behavior_scenario_count == 5
    assert len(library.scenarios) == 205
    assert all(item.cross_channel_scenario_id for item in library.coverage)
    cross_scenarios = [item for item in library.scenarios if item.category is AutotestCategory.CROSS_CHANNEL]
    assert len(cross_scenarios) == 25
    assert all(item.channels == [Channel.API, Channel.WEB] for item in cross_scenarios)
    behavior_scenarios = [item for item in library.scenarios if item.origin == "catalog_behavior_contract"]
    assert {item.test_id for item in behavior_scenarios} == {
        "BEHAVIOR-MISSING-YEAR",
        "BEHAVIOR-UNKNOWN-METRIC",
        "BEHAVIOR-DOCUMENT",
        "BEHAVIOR-CONTEXT",
        "BEHAVIOR-WEB-GREETING",
    }


def test_library_can_be_persisted_as_replayable_json(tmp_path) -> None:
    path = write_scenario_library(build_scenario_library(), tmp_path)

    assert path.exists()
    assert "scenario_library.json" == path.name
