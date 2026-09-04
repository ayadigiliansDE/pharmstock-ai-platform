"""Completed sale and stock-receipt transaction contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

MoneyAmount = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=4)]
ShortReference = Annotated[str, Field(min_length=1, max_length=120)]


class SaleChannel(StrEnum):
    """Channel through which a completed customer sale was fulfilled."""

    IN_STORE = "in_store"
    DELIVERY = "delivery"
    CLICK_AND_COLLECT = "click_and_collect"
    ONLINE_FULFILLMENT = "online_fulfillment"


class SaleLine(BaseModel):
    """One canonical product line in a completed sale."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: UUID
    quantity: int = Field(gt=0, le=1_000_000)
    unit_price: MoneyAmount
    discount_amount: MoneyAmount = Decimal("0")

    @computed_field
    @property
    def gross_amount(self) -> Decimal:
        return self.unit_price * self.quantity

    @computed_field
    @property
    def net_amount(self) -> Decimal:
        return self.gross_amount - self.discount_amount

    @model_validator(mode="after")
    def discount_cannot_exceed_gross(self) -> SaleLine:
        if self.discount_amount > self.gross_amount:
            raise ValueError("discount_amount cannot exceed gross line amount")
        return self


class Sale(BaseModel):
    """A completed pharmacy sale transaction.

    Duplicate product IDs are rejected so one product has one canonical line per
    transaction. POS source adapters can aggregate source lines before validation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    sale_id: UUID = Field(default_factory=uuid4)
    branch_id: UUID
    occurred_at: AwareDatetime
    channel: SaleChannel
    currency_code: str = Field(default="EGP", min_length=3, max_length=3)
    line_items: tuple[SaleLine, ...] = Field(min_length=1, max_length=10_000)
    source_reference: ShortReference | None = None
    idempotency_key: ShortReference | None = None

    @field_validator("currency_code")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized.isalpha():
            raise ValueError("currency_code must be a three-letter alphabetic code")
        return normalized

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @field_validator("line_items")
    @classmethod
    def require_unique_products(cls, lines: tuple[SaleLine, ...]) -> tuple[SaleLine, ...]:
        product_ids = [line.product_id for line in lines]
        if len(set(product_ids)) != len(product_ids):
            raise ValueError("sale line_items must contain each product_id at most once")
        return lines

    @computed_field
    @property
    def total_quantity(self) -> int:
        return sum(line.quantity for line in self.line_items)

    @computed_field
    @property
    def gross_amount(self) -> Decimal:
        return sum((line.gross_amount for line in self.line_items), start=Decimal("0"))

    @computed_field
    @property
    def discount_amount(self) -> Decimal:
        return sum((line.discount_amount for line in self.line_items), start=Decimal("0"))

    @computed_field
    @property
    def net_amount(self) -> Decimal:
        return self.gross_amount - self.discount_amount


class RestockLine(BaseModel):
    """One product/batch received into a pharmacy branch."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    product_id: UUID
    quantity: int = Field(gt=0, le=100_000_000)
    unit_cost: MoneyAmount
    batch_number: str = Field(min_length=1, max_length=120)
    expires_on: date

    @computed_field
    @property
    def line_cost(self) -> Decimal:
        return self.unit_cost * self.quantity


class RestockReceipt(BaseModel):
    """A completed physical receipt of stock at a pharmacy branch.

    This is deliberately a goods-receipt contract, not a purchase order. Future
    procurement stages can create orders before stock physically arrives.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    restock_id: UUID = Field(default_factory=uuid4)
    branch_id: UUID
    received_at: AwareDatetime
    currency_code: str = Field(default="EGP", min_length=3, max_length=3)
    line_items: tuple[RestockLine, ...] = Field(min_length=1, max_length=50_000)
    supplier_reference: ShortReference | None = None
    purchase_order_reference: ShortReference | None = None
    source_reference: ShortReference | None = None
    idempotency_key: ShortReference | None = None

    @field_validator("currency_code")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized.isalpha():
            raise ValueError("currency_code must be a three-letter alphabetic code")
        return normalized

    @field_validator("received_at")
    @classmethod
    def normalize_received_at(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_batches_and_expiry(self) -> RestockReceipt:
        keys = [(line.product_id, line.batch_number.casefold()) for line in self.line_items]
        if len(set(keys)) != len(keys):
            raise ValueError(
                "restock line_items must contain each product_id/batch_number at most once"
            )

        received_date = self.received_at.date()
        expired = [line for line in self.line_items if line.expires_on <= received_date]
        if expired:
            raise ValueError("restock cannot receive an already expired batch")
        return self

    @computed_field
    @property
    def total_quantity(self) -> int:
        return sum(line.quantity for line in self.line_items)

    @computed_field
    @property
    def total_cost(self) -> Decimal:
        return sum((line.line_cost for line in self.line_items), start=Decimal("0"))
