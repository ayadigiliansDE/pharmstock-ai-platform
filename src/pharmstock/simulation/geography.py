"""Egyptian geography seed data used by the synthetic pharmacy-network simulator.

Population values are CAPMAS estimates for 1 January 2024. They are used only as
allocation weights so a large synthetic pharmacy network is distributed across all
27 governorates in a way that is anchored to a real public statistic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EgyptRegion(StrEnum):
    URBAN = "urban_governorates"
    LOWER_EGYPT = "lower_egypt"
    UPPER_EGYPT = "upper_egypt"
    FRONTIER = "frontier_governorates"


@dataclass(frozen=True, slots=True)
class GovernorateProfile:
    code: str
    name_en: str
    name_ar: str
    representative_city: str
    region: EgyptRegion
    population_2024: int
    urban_share_2024: float


# CAPMAS, Population Estimates By Sex & Governorate, 1/1/2024.
# Total in the source table: 105,914,499.
EGYPT_GOVERNORATES: tuple[GovernorateProfile, ...] = (
    GovernorateProfile(
        "CAI",
        "Cairo",
        "القاهرة",
        "Cairo",
        EgyptRegion.URBAN,
        10_299_821,
        1.000,
    ),
    GovernorateProfile(
        "ALX",
        "Alexandria",
        "الإسكندرية",
        "Alexandria",
        EgyptRegion.URBAN,
        5_573_808,
        0.980,
    ),
    GovernorateProfile(
        "PTS",
        "Port Said",
        "بورسعيد",
        "Port Said",
        EgyptRegion.URBAN,
        793_976,
        1.000,
    ),
    GovernorateProfile(
        "SUZ",
        "Suez",
        "السويس",
        "Suez",
        EgyptRegion.URBAN,
        797_045,
        1.000,
    ),
    GovernorateProfile(
        "DAM",
        "Damietta",
        "دمياط",
        "Damietta",
        EgyptRegion.LOWER_EGYPT,
        1_626_063,
        0.405,
    ),
    GovernorateProfile(
        "DKH",
        "Dakahlia",
        "الدقهلية",
        "Mansoura",
        EgyptRegion.LOWER_EGYPT,
        7_086_788,
        0.302,
    ),
    GovernorateProfile(
        "SHR",
        "Sharqia",
        "الشرقية",
        "Zagazig",
        EgyptRegion.LOWER_EGYPT,
        7_961_136,
        0.268,
    ),
    GovernorateProfile(
        "QLB",
        "Qalyubia",
        "القليوبية",
        "Benha",
        EgyptRegion.LOWER_EGYPT,
        6_175_627,
        0.431,
    ),
    GovernorateProfile(
        "KFS",
        "Kafr El Sheikh",
        "كفر الشيخ",
        "Kafr El Sheikh",
        EgyptRegion.LOWER_EGYPT,
        3_740_624,
        0.242,
    ),
    GovernorateProfile(
        "GHR",
        "Gharbia",
        "الغربية",
        "Tanta",
        EgyptRegion.LOWER_EGYPT,
        5_468_353,
        0.306,
    ),
    GovernorateProfile(
        "MNF",
        "Monufia",
        "المنوفية",
        "Shebin El Kom",
        EgyptRegion.LOWER_EGYPT,
        4_767_510,
        0.219,
    ),
    GovernorateProfile(
        "BHR",
        "Beheira",
        "البحيرة",
        "Damanhur",
        EgyptRegion.LOWER_EGYPT,
        6_927_724,
        0.207,
    ),
    GovernorateProfile(
        "ISL",
        "Ismailia",
        "الإسماعيلية",
        "Ismailia",
        EgyptRegion.LOWER_EGYPT,
        1_464_224,
        0.470,
    ),
    GovernorateProfile(
        "GIZ",
        "Giza",
        "الجيزة",
        "Giza",
        EgyptRegion.UPPER_EGYPT,
        9_578_680,
        0.596,
    ),
    GovernorateProfile(
        "BNS",
        "Beni Suef",
        "بني سويف",
        "Beni Suef",
        EgyptRegion.UPPER_EGYPT,
        3_624_142,
        0.254,
    ),
    GovernorateProfile(
        "FYM",
        "Fayoum",
        "الفيوم",
        "Fayoum",
        EgyptRegion.UPPER_EGYPT,
        4_115_608,
        0.228,
    ),
    GovernorateProfile(
        "MNY",
        "Minya",
        "المنيا",
        "Minya",
        EgyptRegion.UPPER_EGYPT,
        6_398_400,
        0.191,
    ),
    GovernorateProfile(
        "AST",
        "Asyut",
        "أسيوط",
        "Asyut",
        EgyptRegion.UPPER_EGYPT,
        5_112_926,
        0.276,
    ),
    GovernorateProfile(
        "SHG",
        "Sohag",
        "سوهاج",
        "Sohag",
        EgyptRegion.UPPER_EGYPT,
        5_783_044,
        0.214,
    ),
    GovernorateProfile(
        "QNA",
        "Qena",
        "قنا",
        "Qena",
        EgyptRegion.UPPER_EGYPT,
        3_674_412,
        0.184,
    ),
    GovernorateProfile(
        "ASN",
        "Aswan",
        "أسوان",
        "Aswan",
        EgyptRegion.UPPER_EGYPT,
        1_670_122,
        0.461,
    ),
    GovernorateProfile(
        "LXR",
        "Luxor",
        "الأقصر",
        "Luxor",
        EgyptRegion.UPPER_EGYPT,
        1_412_746,
        0.428,
    ),
    GovernorateProfile(
        "RDS",
        "Red Sea",
        "البحر الأحمر",
        "Hurghada",
        EgyptRegion.FRONTIER,
        406_195,
        0.969,
    ),
    GovernorateProfile(
        "WAD",
        "New Valley",
        "الوادي الجديد",
        "Kharga",
        EgyptRegion.FRONTIER,
        268_834,
        0.508,
    ),
    GovernorateProfile(
        "MTR",
        "Matrouh",
        "مطروح",
        "Marsa Matrouh",
        EgyptRegion.FRONTIER,
        557_193,
        0.661,
    ),
    GovernorateProfile(
        "NSI",
        "North Sinai",
        "شمال سيناء",
        "Arish",
        EgyptRegion.FRONTIER,
        512_110,
        0.610,
    ),
    GovernorateProfile(
        "SSI",
        "South Sinai",
        "جنوب سيناء",
        "El Tor",
        EgyptRegion.FRONTIER,
        117_388,
        0.562,
    ),
)

CAPMAS_POPULATION_2024_TOTAL = 105_914_499


def validate_governorate_reference() -> None:
    """Fail fast if the embedded reference table is accidentally edited incorrectly."""

    if len(EGYPT_GOVERNORATES) != 27:
        raise RuntimeError("Egypt governorate reference must contain exactly 27 governorates")
    total = sum(item.population_2024 for item in EGYPT_GOVERNORATES)
    if any(not 0.0 <= item.urban_share_2024 <= 1.0 for item in EGYPT_GOVERNORATES):
        raise RuntimeError("urban_share_2024 must be between 0 and 1")
    if total != CAPMAS_POPULATION_2024_TOTAL:
        raise RuntimeError(
            f"CAPMAS population reference total mismatch: {total:,} != "
            f"{CAPMAS_POPULATION_2024_TOTAL:,}"
        )
