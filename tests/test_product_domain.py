from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from pharmstock.domain import (
    ActiveIngredient,
    PrescriptionStatus,
    Product,
    ProductIdentifiers,
    ProductSource,
    RegulatoryStatus,
)


def build_product(**overrides: object) -> Product:
    payload: dict[str, object] = {
        "display_name": "Amoxicillin 500 mg capsule",
        "generic_name": "Amoxicillin",
        "dosage_form": "Capsule",
        "routes": ("Oral", "oral"),
        "active_ingredients": (
            ActiveIngredient(name="Amoxicillin", strength_text="500 mg"),
        ),
        "package_description": "20 capsules",
        "manufacturer": "Example Manufacturer",
        "prescription_status": PrescriptionStatus.PRESCRIPTION,
        "regulatory_status": RegulatoryStatus.ACTIVE,
        "market_code": "eg",
        "identifiers": ProductIdentifiers(local_registration_number="EDA-TEST-001"),
        "source": ProductSource(
            system="test-fixture",
            record_id="EDA-TEST-001",
            source_updated_at=datetime(2026, 8, 22, tzinfo=UTC),
        ),
    }
    payload.update(overrides)
    return Product.model_validate(payload)


def test_product_normalizes_country_and_routes() -> None:
    product = build_product()

    assert product.market_code == "EG"
    assert product.routes == ("oral",)


def test_combination_product_supports_multiple_active_ingredients() -> None:
    product = build_product(
        display_name="Amoxicillin / Clavulanate",
        active_ingredients=(
            ActiveIngredient(name="Amoxicillin", strength_text="875 mg"),
            ActiveIngredient(name="Clavulanic acid", strength_text="125 mg"),
        ),
    )

    assert len(product.active_ingredients) == 2


def test_product_requires_at_least_one_active_ingredient() -> None:
    with pytest.raises(ValidationError):
        build_product(active_ingredients=())


def test_product_requires_external_identifier() -> None:
    with pytest.raises(ValidationError):
        ProductIdentifiers()


def test_gtin_rejects_non_numeric_values() -> None:
    with pytest.raises(ValidationError):
        ProductIdentifiers(gtin="ABC12345")


def test_product_rejects_invalid_market_code() -> None:
    with pytest.raises(ValidationError):
        build_product(market_code="E1")


def test_product_is_immutable_after_validation() -> None:
    product = build_product()

    with pytest.raises(ValidationError):
        product.display_name = "Changed"  # type: ignore[misc]
