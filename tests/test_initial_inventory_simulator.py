from datetime import date
from uuid import UUID

from pharmstock.domain import (
    ActiveIngredient,
    PrescriptionStatus,
    Product,
    ProductIdentifiers,
    ProductSource,
    RegulatoryStatus,
)
from pharmstock.simulation import InitialInventoryGenerator, PharmacyNetworkGenerator


def build_products(count: int = 120) -> list[Product]:
    products = []
    for i in range(count):
        products.append(
            Product(
                product_id=UUID(int=i + 1),
                display_name=f"Medicine {i:04d}",
                generic_name=f"Ingredient {i:04d}",
                dosage_form="TABLET" if i % 3 else "INJECTION",
                active_ingredients=(
                    ActiveIngredient(name=f"Ingredient {i:04d}", strength_text="10 mg"),
                ),
                prescription_status=PrescriptionStatus.PRESCRIPTION,
                regulatory_status=RegulatoryStatus.ACTIVE,
                market_code="US",
                identifiers=ProductIdentifiers(ndc_package_code=f"00001-{i:04d}-01"),
                source=ProductSource(system="test", record_id=str(i)),
            )
        )
    return products


def generate(branches: int = 8, products: int = 120):
    network = PharmacyNetworkGenerator(seed=7).generate(branches)
    generated = InitialInventoryGenerator(
        seed=7, reference_date=date(2026, 8, 22)
    ).generate(network=network, products=build_products(products))
    return network, generated


def test_inventory_is_generated_for_every_branch() -> None:
    network, generated = generate()
    assert len(generated.branch_summaries) == len(network.branches)
    assert {row.branch_id for row in generated.branch_summaries} == {
        str(branch.branch_id) for branch in network.branches
    }


def test_no_duplicate_branch_product_pairs() -> None:
    _, generated = generate()
    pairs = [(row.branch_id, row.product_id) for row in generated.inventory_rows]
    assert len(pairs) == len(set(pairs))


def test_assortment_never_exceeds_branch_capacity_or_catalog() -> None:
    _, generated = generate(products=75)
    assert all(
        row.generated_assortment_skus <= min(row.assortment_capacity_skus, 75)
        for row in generated.branch_summaries
    )


def test_batch_quantities_sum_to_inventory_on_hand() -> None:
    _, generated = generate()
    batch_totals: dict[tuple[str, str], int] = {}
    for batch in generated.batch_rows:
        key = (batch.branch_id, batch.product_id)
        batch_totals[key] = batch_totals.get(key, 0) + batch.on_hand_quantity
    assert all(
        batch_totals[(row.branch_id, row.product_id)] == row.on_hand_quantity
        for row in generated.inventory_rows
    )


def test_every_batch_expires_after_reference_date() -> None:
    _, generated = generate()
    assert all(
        date.fromisoformat(row.expires_on) > date(2026, 8, 22)
        for row in generated.batch_rows
    )


def test_reorder_policy_is_valid_for_every_inventory_row() -> None:
    _, generated = generate()
    assert all(row.target_stock_level > row.reorder_point >= 1 for row in generated.inventory_rows)


def test_same_seed_is_reproducible() -> None:
    _, left = generate()
    _, right = generate()
    assert left.inventory_rows == right.inventory_rows
    assert left.batch_rows == right.batch_rows


def test_mapping_is_explicitly_cross_market_and_not_priced() -> None:
    _, generated = generate()
    assert generated.summary()["mapping_status"] == "synthetic_cross_market_mapping"
    assert generated.summary()["prices_generated"] is False
    assert all(row.source_market == "US" for row in generated.inventory_rows)
    assert all(row.simulation_market == "EG" for row in generated.inventory_rows)


def test_total_initial_stock_never_exceeds_branch_storage_capacity() -> None:
    network, generated = generate(branches=25, products=300)
    capacity_by_branch = {
        str(branch.branch_id): branch.capacity.storage_capacity_units for branch in network.branches
    }
    assert all(
        row.generated_stock_units <= capacity_by_branch[row.branch_id]
        for row in generated.branch_summaries
    )
    assert all(row.storage_utilization_pct <= 100 for row in generated.branch_summaries)
