# Stage 2C — Branch Assortment + Initial Inventory

Stage 2C is the first checkpoint that joins the two large data domains built earlier:

```text
Stage 2A pharmacy network
        +
Stage 2B canonical drug catalog
        -> branch assortment
        -> initial inventory
        -> reorder policies
        -> batch / expiry rows
```

## Important data-truth rule

The Stage 2B catalog is sourced from the official U.S. openFDA NDC Directory, while the
Stage 2A pharmacy network is a synthetic Egyptian network. Therefore Stage 2C **does not**
claim that these NDC products are registered, priced, stocked, or sold in Egypt.

Every exported inventory row is explicitly marked:

```text
mapping_status = synthetic_cross_market_mapping
source_market = US
simulation_market = EG
```

No prices are generated in Stage 2C. A market-local pricing source or an explicitly
synthetic pricing model must be introduced in a later stage.

## Constraints enforced

- selected SKUs never exceed a branch's `assortment_capacity_skus`
- total initial stock units never exceed `storage_capacity_units`
- every branch/product pair is unique
- every inventory row has a valid reorder point and target level
- one to three simulated batches are generated per stocked SKU
- batch quantities sum exactly to the parent inventory on-hand quantity
- generated batches expire after the simulation reference date
- fixed seeds reproduce the same network and inventory

## Output files

`run_stage2c_inventory.py` writes:

- `branch_inventory.csv`
- `inventory_batches.csv`
- `branch_assortment_summary.csv`
- `inventory_summary.json`

These outputs are deliberately flat and inspectable in Excel before a database or
streaming layer is introduced.

## Memory / scale note

A real 9,000+ SKU catalog multiplied across hundreds or thousands of branches creates
millions of branch-product and batch rows. Stage 2C currently uses an in-memory generator
so the local learning checkpoint should start with 25 branches, then 50/100 as the machine
allows. Before the 1,000-branch inventory run is treated as an acceptance target, the
export path will be changed to streaming/chunked persistence so RAM does not scale with
the entire generated dataset.
