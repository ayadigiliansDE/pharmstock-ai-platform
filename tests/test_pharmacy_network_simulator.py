from collections import Counter

import pytest

from pharmstock.domain import OrganizationType
from pharmstock.simulation import PharmacyNetworkGenerator


def test_generator_creates_requested_branch_count() -> None:
    network = PharmacyNetworkGenerator(seed=7).generate(1_000)

    assert len(network.branches) == 1_000
    assert len(network.organizations) > 0


def test_large_network_covers_all_27_governorates() -> None:
    network = PharmacyNetworkGenerator(seed=7).generate(1_000)

    assert len({branch.location.governorate for branch in network.branches}) == 27


def test_all_branch_and_organization_identifiers_are_unique() -> None:
    network = PharmacyNetworkGenerator(seed=7).generate(1_000)

    assert len({branch.branch_id for branch in network.branches}) == 1_000
    assert len({branch.branch_code for branch in network.branches}) == 1_000
    assert len({org.organization_id for org in network.organizations}) == len(network.organizations)


def test_every_branch_references_a_generated_organization() -> None:
    network = PharmacyNetworkGenerator(seed=7).generate(300)
    organization_ids = {org.organization_id for org in network.organizations}

    assert all(branch.organization_id in organization_ids for branch in network.branches)


def test_same_seed_produces_same_network_identity_and_distribution() -> None:
    left = PharmacyNetworkGenerator(seed=99).generate(250)
    right = PharmacyNetworkGenerator(seed=99).generate(250)

    left_ids = [branch.branch_id for branch in left.branches]
    right_ids = [branch.branch_id for branch in right.branches]
    assert left_ids == right_ids
    assert left.summary() == right.summary()


def test_different_seed_changes_generated_branch_identity() -> None:
    left = PharmacyNetworkGenerator(seed=1).generate(50)
    right = PharmacyNetworkGenerator(seed=2).generate(50)

    left_ids = [branch.branch_id for branch in left.branches]
    right_ids = [branch.branch_id for branch in right.branches]
    assert left_ids != right_ids


def test_inventory_capacity_constraints_are_valid_for_every_generated_branch() -> None:
    network = PharmacyNetworkGenerator(seed=17).generate(1_000)

    for branch in network.branches:
        assert branch.capacity.storage_capacity_units >= branch.capacity.assortment_capacity_skus
        if branch.capacity.cold_chain_supported:
            assert branch.capacity.cold_chain_capacity_units > 0
        else:
            assert branch.capacity.cold_chain_capacity_units == 0


def test_network_contains_multiple_operating_profiles_and_scales() -> None:
    network = PharmacyNetworkGenerator(seed=21).generate(1_000)

    scales = {branch.scale for branch in network.branches}
    service_mode_sets = {branch.operating_profile.service_modes for branch in network.branches}

    assert len(scales) >= 3
    assert len(service_mode_sets) >= 3


def test_invalid_branch_count_is_rejected() -> None:
    with pytest.raises(ValueError):
        PharmacyNetworkGenerator().generate(0)


def test_independent_organizations_have_one_branch() -> None:
    network = PharmacyNetworkGenerator(seed=123).generate(1_000)
    counts = Counter(branch.organization_id for branch in network.branches)

    independent_ids = {
        org.organization_id
        for org in network.organizations
        if org.organization_type is OrganizationType.INDEPENDENT
    }
    assert independent_ids
    assert all(counts[org_id] == 1 for org_id in independent_ids)
