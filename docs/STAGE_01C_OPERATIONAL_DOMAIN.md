# Stage 1C — Inventory, Sale, Restock and Domain Events

## Goal

Stage 1C is the first checkpoint where PharmStock models changing operational state instead of master data only.

The core flow is now:

```text
Pharmacy Branch + Product
          |
          v
     InventoryItem
       /       \
    Sale      RestockReceipt
      |             |
      v             v
 StockMovement   StockMovement
      \             /
       \           /
        +--> Domain Events
```

Kafka is still deliberately absent. The business rules and event contracts must be valid before a transport technology is introduced.

## 1. InventoryItem

`InventoryItem` is the current branch-product inventory snapshot. It contains:

- immutable inventory item UUID
- branch UUID
- product UUID
- physical on-hand quantity
- reserved quantity
- reorder policy
- optimistic version number
- last update timestamp

`available_quantity` is derived as:

```text
on_hand_quantity - reserved_quantity
```

A new sale cannot consume reserved stock.

Inventory objects are immutable. A stock-changing operation returns a **new snapshot** rather than mutating the existing object.

## 2. ReorderPolicy

Each branch-product inventory item can have its own policy:

```text
reorder_point
      |
      v
available stock falls to/below threshold
      |
      v
target_stock_level
```

The domain calculates `recommended_reorder_quantity` from the current available stock.

A reorder event is considered newly triggered only when a transition crosses from healthy inventory into reorder-required inventory. This prevents emitting a new alert for every later sale while the item remains below the threshold.

## 3. StockMovement

Every physical stock change produces an immutable audit record with:

- movement UUID
- branch and product UUIDs
- movement reason
- signed quantity delta
- on-hand before/after values
- reserved before/after values
- resulting inventory version
- source transaction reference
- timezone-aware occurrence timestamp

The movement contract validates the arithmetic itself:

```text
on_hand_before + quantity_delta == on_hand_after
```

This prevents internally inconsistent movement records from entering the future event pipeline.

The movement type vocabulary already reserves canonical reasons such as sale, restock, return, transfer, expiry, damage and adjustment. Stage 1C actively implements sale and restock transitions; the other reasons are prepared for later workflows.

## 4. Sale

`Sale` represents a **completed** sale transaction, not a cart or pending checkout.

A sale contains:

- sale UUID
- pharmacy branch UUID
- timezone-aware occurrence time
- sales channel
- ISO-style three-letter currency code
- one or more product lines
- optional source reference
- optional idempotency key

Each `SaleLine` contains product UUID, positive quantity, Decimal unit price and optional Decimal discount.

Money uses `Decimal`, not binary floating point, so financial values are not corrupted by floating-point rounding behavior.

Duplicate product IDs are rejected inside a canonical sale. A future POS source adapter can aggregate source rows before creating the domain transaction.

## 5. RestockReceipt

`RestockReceipt` represents stock that has **physically arrived** at a branch. It is not a purchase order.

A restock line includes:

- product UUID
- received quantity
- Decimal unit cost
- batch number
- expiry date

Already-expired batches are rejected. Duplicate product/batch pairs in one receipt are also rejected.

Keeping batch and expiry information at the transaction boundary is essential for a pharmacy platform. Stage 2 will add lot-aware stock allocation/FEFO simulation so expiry-sensitive sales can consume the correct batches.

## 6. Versioned Domain Events

Stage 1C introduces transport-independent events:

```text
sale.recorded              v1.0
restock.received           v1.0
inventory.stock_changed    v1.0
inventory.reorder_required v1.0
```

Each event has a common envelope:

- event UUID
- event type
- schema version
- aggregate type and ID
- occurred timestamp
- recorded timestamp
- correlation ID
- optional causation ID
- typed payload

The event schema version is independent of the Python package version. This matters later because Kafka consumers may upgrade on a different schedule from the producer application.

## 7. Correlation and causation

One business action can create several related events.

Example:

```text
SaleRecordedEvent
  correlation_id = Sale ID
        |
        | causation_id
        v
StockChangedEvent
        |
        | causation_id
        v
ReorderRequiredEvent
```

All events keep the same correlation ID so one complete business flow can be traced through logs, Kafka, Spark and the warehouse later.

## 8. Idempotency and concurrency

The contracts already expose two production concepts before persistence exists:

- **idempotency key** on external sale/restock transactions
- **inventory version** for future optimistic-concurrency checks

Uniqueness and compare-and-swap enforcement belong to a repository/database layer and are intentionally not faked inside an in-memory Pydantic model.

## 9. What Stage 1C deliberately does not do yet

- publish to Kafka
- persist inventory to a database
- guarantee a multi-line transaction atomically across database rows
- allocate sale quantities across pharmaceutical batches using FEFO
- create purchase orders or supplier master data
- enforce branch physical capacity during a restock
- calculate demand forecasts

Those rules need application/persistence context rather than being hidden in transport-independent value contracts.

## 10. Files introduced

- `src/pharmstock/domain/inventory.py`
- `src/pharmstock/domain/transactions.py`
- `src/pharmstock/domain/events.py`
- `tests/test_inventory_domain.py`
- `tests/test_transaction_domain.py`
- `tests/test_event_contracts.py`
- `scripts/demo_stage1c_flow.py`

The public domain exports and project version were updated for the Stage 1C checkpoint.
