# Stage 1A — Product Domain Model

## Goal

Replace the original demo assumption of a tiny hard-coded drug list with a product-master contract that can hold hundreds, thousands, or tens of thousands of records from external authoritative sources.

Stage 1A does **not** download a drug registry yet. It defines the stable contract that every future source adapter must map into.

## Why this comes before a drug-data importer

External sources use different schemas. For example, one registry may identify a product by a national registration number, another by NDC, and another by RxCUI. If source-specific JSON is allowed to spread through the application, Kafka, Spark, dbt and Power BI become tightly coupled to one provider.

V2 therefore uses this flow:

```text
Authoritative source record
        |
        v
Source-specific adapter            <- later stage
        |
        v
Canonical Product model            <- Stage 1A
        |
        +--> simulator
        +--> events
        +--> warehouse dimensions
        +--> ML features
        +--> Power BI product dimension
```

## Product fields

The canonical Product contains:

- an internal UUID
- display / brand / generic names
- dosage form
- one or more administration routes
- one or more active ingredients
- source-preserved strength text
- package description
- manufacturer
- prescription/OTC status
- regulatory status
- two-letter market code
- cross-registry identifiers (RxCUI, NDC, GTIN, local registration number)
- source provenance

## Important boundary decisions

The Product model intentionally does **not** contain:

- stock quantity — belongs to Inventory
- pharmacy-specific selling price — belongs to Pricing / transaction facts
- units sold — belongs to Sale events
- reorder threshold — belongs to a pharmacy inventory policy
- demand forecast — belongs to ML output

This avoids mixing master data with fast-changing operational state.

## Why `strength_text` is text

Real pharmaceutical sources represent strength in many forms: `500 mg`, `250 mg/5 mL`, ratios, salts and combination products. Stage 1A preserves the authoritative source text rather than prematurely converting every product into one numeric representation. A normalized analytics representation can be added later while retaining the original value.

## Why the model is immutable

Validated domain records are frozen. Updating a product means producing a new validated record/version rather than silently mutating a product that may already have been used in an event.

## Stage 1A acceptance

- Product package imports successfully.
- Invalid country codes are rejected.
- At least one active ingredient is required.
- At least one external registry identifier is required.
- Combination medicines are supported.
- GTIN accepts digits only.
- Domain records are immutable after validation.
