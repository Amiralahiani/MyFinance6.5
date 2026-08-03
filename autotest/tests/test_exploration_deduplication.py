from myfinance_testing_api.main import _is_new_exploration_question


def test_exploration_rejects_exact_and_near_duplicate_questions() -> None:
    previous = ["Quel est le prix du bitcoin chez BIAT en 2025 ?"]

    assert not _is_new_exploration_question("Quel est le prix du Bitcoin de la BIAT pour 2025 ?", previous)
    assert not _is_new_exploration_question("Quel est le prix du bitcoin chez BIAT en 2025 ?", previous)
    assert _is_new_exploration_question("Quelle information officielle existe sur les prêts verts d’Amen Bank ?", previous)
