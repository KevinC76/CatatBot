from __future__ import annotations

import re
from datetime import date, timedelta

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "F&B": [
        "makan", "minum", "kopi", "cafe", "resto", "restoran", "warung", "bakso",
        "soto", "nasi", "ayam", "burger", "pizza", "snack", "jajan", "boba",
        "tea", "teh", "lunch", "dinner", "breakfast", "sarapan", "mie", "sate",
        "martabak", "indomie", "geprek", "pecel", "gado", "minuman", "makanan",
        "es ", "susu", "roti",
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

# Patterns that represent an amount — used to strip from description
_AMOUNT_PATTERNS = [
    r"\d+(?:[.,]\d+)?\s*(?:jt|juta)",
    r"\d+(?:[.,]\d+)?\s*(?:rb|ribu|k)\b",
    r"\b\d{1,3}(?:[.,]\d{3})+\b",
    r"\b\d{4,}\b",
]
_AMOUNT_RE = re.compile("|".join(_AMOUNT_PATTERNS), re.IGNORECASE)


def _parse_nominal(text: str) -> int | None:
    t = text.lower()

    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:jt|juta)", t)
    if m:
        return int(float(m.group(1).replace(",", ".")) * 1_000_000)

    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:rb|ribu|k)\b", t)
    if m:
        return int(float(m.group(1).replace(",", ".")) * 1_000)

    m = re.search(r"\b(\d{1,3}(?:[.,]\d{3})+)\b", t)
    if m:
        return int(re.sub(r"[.,]", "", m.group(1)))

    m = re.search(r"\b(\d{3,})\b", t)
    if m:
        return int(m.group(1))

    return None


def _clean_description(text: str) -> str:
    cleaned = _AMOUNT_RE.sub("", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,")
    return cleaned[:80] if cleaned else text.strip()[:80]


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


def _parse_single(text: str, tanggal: str) -> dict | None:
    nominal = _parse_nominal(text)
    if nominal is None or nominal <= 0:
        return None
    return {
        "nominal": nominal,
        "kategori": _parse_kategori(text),
        "deskripsi": _clean_description(text),
        "tanggal": tanggal,
    }


def parse_expenses(text: str) -> list[dict]:
    tanggal = _parse_tanggal(text)

    # Split on comma or "dan" to detect multiple items
    parts = re.split(r",\s*|\bdan\b", text, flags=re.IGNORECASE)

    if len(parts) > 1:
        results = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            item = _parse_single(part, tanggal)
            if item:
                results.append(item)
        if results:
            return results

    # Single item fallback
    item = _parse_single(text, tanggal)
    return [item] if item else []
