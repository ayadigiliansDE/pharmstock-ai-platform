from __future__ import annotations

from typing import Any


OPERATIONAL_KEY = "operational_provenance_class"
REFERENCE_KEY = "reference_provenance_class"
LEGACY_PROVENANCE_KEY = "provenance_class"

SYNTHETIC_OPERATIONAL_CLASSES = frozenset(
    {
        "SYNTHETIC",
        "SYNTHETIC_CALIBRATED",
    }
)

LIVE_OPERATIONAL_CLASSES = frozenset(
    {
        "LIVE_OPERATIONAL",
    }
)


def _walk(value: Any):
    if isinstance(value, dict):
        yield value

        for nested in value.values():
            yield from _walk(nested)

    elif isinstance(value, list):
        for nested in value:
            yield from _walk(nested)


def _normalize(value: Any) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip().upper()

    return normalized or None


def summarize_evidence_provenance(
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    operational: set[str] = set()
    reference: set[str] = set()

    for evidence_item in evidence:
        tool_name = str(
            evidence_item.get("tool") or ""
        ).strip()

        data = evidence_item.get("data")

        for node in _walk(data):
            op_value = _normalize(
                node.get(OPERATIONAL_KEY)
            )
            ref_value = _normalize(
                node.get(REFERENCE_KEY)
            )

            if op_value:
                operational.add(op_value)

            if ref_value:
                reference.add(ref_value)

            # Stage7M demand serving predates the split provenance
            # contract and exposes provenance_class for operational
            # demand observations. Treat it as operational provenance
            # only for the governed demand tool.
            if tool_name == "demand_trend":
                legacy_value = _normalize(
                    node.get(LEGACY_PROVENANCE_KEY)
                )

                if legacy_value:
                    operational.add(legacy_value)

    operational_classes = sorted(operational)
    reference_classes = sorted(reference)

    contains_synthetic_operational_data = bool(
        operational.intersection(
            SYNTHETIC_OPERATIONAL_CLASSES
        )
    )

    contains_live_operational_data = bool(
        operational.intersection(
            LIVE_OPERATIONAL_CLASSES
        )
    )

    if not operational_classes:
        operational_context = "UNKNOWN"

    elif len(operational_classes) > 1:
        operational_context = "MIXED_OPERATIONAL"

    elif contains_synthetic_operational_data:
        operational_context = "SYNTHETIC_OPERATIONAL"

    elif contains_live_operational_data:
        operational_context = "LIVE_OPERATIONAL"

    else:
        operational_context = "OTHER_OPERATIONAL"

    if not reference_classes:
        reference_context = "NONE"

    elif len(reference_classes) > 1:
        reference_context = "MIXED_REFERENCE"

    else:
        reference_context = reference_classes[0]

    safe_to_describe_as_live_operational = (
        operational_context == "LIVE_OPERATIONAL"
        and not contains_synthetic_operational_data
    )

    return {
        "operational_provenance_classes":
            operational_classes,
        "reference_provenance_classes":
            reference_classes,
        "operational_context":
            operational_context,
        "reference_context":
            reference_context,
        "contains_synthetic_operational_data":
            contains_synthetic_operational_data,
        "contains_live_operational_data":
            contains_live_operational_data,
        "safe_to_describe_as_live_operational":
            safe_to_describe_as_live_operational,
        "assistant_disclosure_required":
            contains_synthetic_operational_data,
    }


def build_data_context(
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    provenance = summarize_evidence_provenance(
        evidence
    )

    if provenance[
        "contains_synthetic_operational_data"
    ]:
        disclosure = (
            "Operational evidence is "
            "SYNTHETIC_CALIBRATED and must not be "
            "described as live or real pharmacy operations."
        )

    elif provenance[
        "safe_to_describe_as_live_operational"
    ]:
        disclosure = (
            "Operational evidence is classified as "
            "LIVE_OPERATIONAL."
        )

    else:
        disclosure = (
            "Operational provenance is not sufficient "
            "to describe the evidence as live operations."
        )

    return {
        **provenance,
        "disclosure": disclosure,
    }
