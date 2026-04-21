from __future__ import annotations

import re
from datetime import date, timedelta

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "F&B": [
        "makan", "minum", "kopi", "cafe", "resto", "restoran", "warung", "bakso",
        "soto", "nasi", "ayam", "burger", "pizza", "snack", "jajan", "boba",
        "tea", "lunch", "dinner", "breakfast", "sarapan", "mie", "sate",
        "martabak", "indomie", "geprek", "pecel", "gado", "minuman", "makanan",
    ],
    "Transport": [
        "grab", "gojek", "bensin", "parkir", "tol", "bus", "kereta", "ojek",
        "taxi", "bbm", "angkot", "commuter", "busway", "transjakarta", "damri",
        "motor", "mobil", "perjalanan", "tiket",
    ],
    "Belanja": [
        "beli", "shopee", "tokopedia", "indomaret", "alfamart", "supermarket",
        "minimarket", "mall", "toko", "laundry", "baju", "celana", "sepatu",
        "tas", "elektronik",
    ],
    "Hiburan": [
        "netflix", "spotify", "bioskop", "game", "cinema", "youtube", "main",
        "nonton", "hiburan", "steam", "disney", "hbo",
    ],
    "Tagihan": [
        "listrik", "air", "internet", "pulsa", "cicilan", "kost", "sewa",
        "wifi", "token", "indihome", "telkom", "tagihan", "iuran",
    ],
    "Kesehatan": [
        "obat", "dokter", "apotek", "rumah sakit", "vitamin", "klinik", "rs",
        "periksa", "konsultasi", "medikal",
    ],
}


def _parse_nominal(text: str) -> int | None:
    t = text.lower().replace(",", ".")

    # 1.5jt / 1jt
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:jt|juta)", t)
    if m:
        return int(float(m.group(1)) * 1_000_000)

    # 35rb / 35ribu / 35k
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:rb|ribu|k\b)", t)
    if m:
        return int(float(m.group(1)) * 1_000)

    # 35.000 or 35,000 (thousand-separated)
    m = re.search(r"\b(\d{1,3}(?:[.,]\d{3})+)\b", t)
    if m:
        return int(re.sub(r"[.,]", "", m.group(1)))

    # plain integer >= 100
    m = re.search(r"\b(\d{3,})\b", t)
    if m:
        return int(m.group(1))

    return None


def _parse_kategori(text: str) -> str:
    t = text.lower()
    for kategori, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in t:
                return kategori
    return "Lainnya"


def _parse_tanggal(text: str) -> str:
    t = text.lower()
    today = date.today()
    if "kemarin" in t:
        return (today - timedelta(days=1)).isoformat()
    if "2 hari lalu" in t or "dua hari lalu" in t:
        return (today - timedelta(days=2)).isoformat()
    return today.isoformat()


def parse_expense(text: str) -> dict | None:
    nominal = _parse_nominal(text)
    if nominal is None or nominal <= 0:
        return None
    return {
        "nominal": nominal,
        "kategori": _parse_kategori(text),
        "deskripsi": text.strip()[:100],
        "tanggal": _parse_tanggal(text),
    }
