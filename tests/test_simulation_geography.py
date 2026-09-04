from pharmstock.simulation import (
    CAPMAS_POPULATION_2024_TOTAL,
    EGYPT_GOVERNORATES,
    validate_governorate_reference,
)


def test_capmas_reference_has_all_27_governorates_and_expected_total() -> None:
    validate_governorate_reference()

    assert len(EGYPT_GOVERNORATES) == 27
    assert sum(item.population_2024 for item in EGYPT_GOVERNORATES) == CAPMAS_POPULATION_2024_TOTAL
    assert len({item.code for item in EGYPT_GOVERNORATES}) == 27
