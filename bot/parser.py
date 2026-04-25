from __future__ import annotations

import re
from datetime import date, timedelta

from bot.currency_service import detect_foreign_currency

# ── Expense categories ────────────────────────────────────────────────────────

EXPENSE_CATEGORY_KEYWORDS: dict[str, list[str]] = {
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

# ── Income categories ─────────────────────────────────────────────────────────

INCOME_KEYWORDS: frozenset[str] = frozenset({
    "gaji", "gajian", "terima", "dapat", "income", "masuk", "cashback",
    "refund", "bonus", "fee", "honor", "dapet", "profit", "hasil",
    "transferan", "kiriman", "freelance", "dividend", "dividen", "thr",
    "pemasukan", "pendapatan", "bayaran", "dibayar",
})

INCOME_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Gaji":      ["gaji", "gajian", "salary", "upah", "thr"],
    "Freelance": ["freelance", "project", "fee", "honor", "jasa", "klien", "bayaran"],
    "Investasi": ["dividen", "dividend", "investasi", "return", "profit", "saham", "reksa"],
    "Cashback":  ["cashback", "refund", "cashback"],
    "Bonus":     ["bonus", "incentive", "reward"],
    "Transfer":  ["transfer", "transferan", "kiriman", "terima", "dapat", "dapet"],
}

# ── Amount patterns ───────────────────────────────────────────────────────────

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


def _detect_tipe(text: str) -> str:
    t = text.lower()
    for kw in INCOME_KEYWORDS:
        if kw in t:
            return "Pemasukan"
    return "Pengeluaran"


def _detect_kategori(text: str, tipe: str) -> str:
    t = text.lower()
    if tipe == "Pemasukan":
        for kategori, keywords in INCOME_CATEGORY_KEYWORDS.items():
            if any(kw in t for kw in keywords):
                return kategori
        return "Lainnya"
    for kategori, keywords in EXPENSE_CATEGORY_KEYWORDS.items():
        if any(kw in t for kw in keywords):
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
    # Check for foreign currency first
    currency, foreign_amount = detect_foreign_currency(text)

    if currency:
        tipe     = _detect_tipe(text)
        deskripsi = _clean_description(text)
        return {
            "nominal":      0,           # filled by currency_service later
            "nominal_asli": foreign_amount,
            "mata_uang":    currency,
            "tipe":         tipe,
            "kategori":     _detect_kategori(text, tipe),
            "deskripsi":    deskripsi,
            "tanggal":      tanggal,
        }

    nominal = _parse_nominal(text)
    if nominal is None or nominal <= 0:
        return None

    tipe = _detect_tipe(text)
    return {
        "nominal":      nominal,
        "nominal_asli": float(nominal),
        "mata_uang":    "IDR",
        "tipe":         tipe,
        "kategori":     _detect_kategori(text, tipe),
        "deskripsi":    _clean_description(text),
        "tanggal":      tanggal,
    }


def parse_expenses(text: str) -> list[dict]:
    tanggal = _parse_tanggal(text)

    # Try splitting on comma or "dan"
    parts = re.split(r",\s*|\bdan\b", text, flags=re.IGNORECASE)
    if len(parts) > 1:
        results = [_parse_single(p.strip(), tanggal) for p in parts if p.strip()]
        results = [r for r in results if r]
        if results:
            return results

    item = _parse_single(text, tanggal)
    return [item] if item else []
