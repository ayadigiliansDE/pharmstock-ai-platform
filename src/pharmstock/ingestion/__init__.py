"""External data ingestion adapters."""

from pharmstock.ingestion.egypt_market_drugs import (
    EgyptMarketDrugError,
    EgyptMarketIngestionReport,
    EgyptMarketProduct,
    RejectedEgyptMarketRow,
    ingest_egypt_market_csv,
    normalize_egypt_market_row,
)
from pharmstock.ingestion.openfda_ndc import (
    CatalogIngestionReport,
    OpenFdaCatalogIngestor,
    OpenFdaError,
    OpenFdaNdcClient,
    OpenFdaPage,
    RejectedSourceRecord,
    normalize_openfda_ndc_record,
)

__all__ = [
    "CatalogIngestionReport",
    "EgyptMarketDrugError",
    "EgyptMarketIngestionReport",
    "EgyptMarketProduct",
    "OpenFdaCatalogIngestor",
    "OpenFdaError",
    "OpenFdaNdcClient",
    "OpenFdaPage",
    "RejectedEgyptMarketRow",
    "RejectedSourceRecord",
    "ingest_egypt_market_csv",
    "normalize_egypt_market_row",
    "normalize_openfda_ndc_record",
]
