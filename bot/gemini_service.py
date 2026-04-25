from __future__ import annotations

import asyncio
import io
import json
import logging
import re
from datetime import date, timedelta

import google.generativeai as genai
import PIL.Image

from config import config

logger = logging.getLogger(__name__)

genai.configure(api_key=config.GEMINI_API_KEY)
_model = genai.GenerativeModel("gemini-2.0-flash")

# ── Shared helpers ────────────────────────────────────────────────────────────

_VALID_EXPENSE_CATS = {"F&B", "Transport", "Belanja", "Hiburan", "Tagihan", "Kesehatan", "Lainnya"}
_VALID_INCOME_CATS  = {"Gaji", "Freelance", "Investasi", "Transfer", "Cashback", "Bonus", "Lainnya"}
_VALID_CURRENCIES   = {"IDR", "USD", "EUR", "GBP", "JPY", "SGD", "MYR", "AUD", "CNY", "KRW", "THB", "SAR", "AED"}


def _clean_json(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _validate_item(item: dict, today: str) -> dict | None:
    try:
        tipe = item.get("tipe", "Pengeluaran")
        if tipe not in ("Pengeluaran", "Pemasukan"):
            tipe = "Pengeluaran"

        mata_uang = str(item.get("mata_uang", "IDR")).upper()
        if mata_uang not in _VALID_CURRENCIES:
            mata_uang = "IDR"

        nominal_asli = item.get("nominal_asli")
        nominal      = item.get("nominal")

        if mata_uang == "IDR":
            nominal = int(nominal or 0)
            if nominal <= 0:
                return None
            nominal_asli = float(nominal)
        else:
            # Foreign currency — nominal filled later by currency_service
            nominal_asli = float(nominal_asli or nominal or 0)
            if nominal_asli <= 0:
                return None
            nominal = 0  # placeholder

        valid_cats = _VALID_INCOME_CATS if tipe == "Pemasukan" else _VALID_EXPENSE_CATS
        kategori = item.get("kategori", "Lainnya")
        if kategori not in valid_cats:
            kategori = "Lainnya"

        return {
            "nominal":      nominal,
            "nominal_asli": nominal_asli,
            "mata_uang":    mata_uang,
            "tipe":         tipe,
            "kategori":     kategori,
            "deskripsi":    str(item.get("deskripsi", ""))[:80].strip(),
            "tanggal":      str(item.get("tanggal", today)),
        }
    except (ValueError, TypeError):
        return None


# ── Text parsing ──────────────────────────────────────────────────────────────

_TEXT_PROMPT = """Kamu adalah parser transaksi keuangan pribadi berbahasa Indonesia.

Ekstrak SEMUA transaksi dari pesan berikut. Kembalikan JSON array (selalu array).

Tanggal hari ini: {today} | Kemarin: {yesterday}

=== TIPE TRANSAKSI ===
- "Pengeluaran" (default): beli, bayar, makan, minum, keluar, habis, dll
- "Pemasukan": gaji, gajian, terima, dapat, income, masuk, cashback, refund,
  bonus, fee, honor, dapet, profit, hasil, transferan masuk, freelance, dll

=== KATEGORI ===
Pengeluaran : F&B | Transport | Belanja | Hiburan | Tagihan | Kesehatan | Lainnya
Pemasukan   : Gaji | Freelance | Investasi | Transfer | Cashback | Bonus | Lainnya

=== MATA UANG ===
Deteksi simbol ($→USD, €→EUR, £→GBP, ¥→JPY) atau kode (USD, EUR, JPY, SGD, MYR,
GBP, AUD, CNY, KRW, THB, SAR, AED) atau nama (dollar, euro, yen, ringgit, dll).
- IDR atau tidak disebutkan → "mata_uang":"IDR", "nominal_asli": sama dgn nominal
- Asing → "mata_uang":"USD", "nominal_asli":<nilai asli>, "nominal": null

=== ATURAN NOMINAL (IDR) ===
35rb/35ribu=35000 | 35k=35000 | 1.5jt=1500000 | 35.000=35000

=== ATURAN DESKRIPSI ===
Nama barang/jasa SAJA tanpa nominal dan tanpa satuan. Title Case. Maks 60 karakter.

=== ATURAN TANGGAL ===
"kemarin"={yesterday} | "tadi"/tidak disebutkan={today} | Format: YYYY-MM-DD

Kembalikan JSON array:
[{{
  "nominal": <integer IDR atau null jika mata uang asing>,
  "nominal_asli": <float nilai asli>,
  "mata_uang": "<IDR atau kode 3 huruf>",
  "tipe": "<Pengeluaran|Pemasukan>",
  "kategori": "<kategori sesuai tipe>",
  "deskripsi": "<nama tanpa nominal>",
  "tanggal": "<YYYY-MM-DD>"
}}]

Jika tidak ada transaksi yang bisa diekstrak → kembalikan: []
"""


async def parse_expenses(text: str) -> list[dict]:
    today     = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    prompt    = _TEXT_PROMPT.format(today=today, yesterday=yesterday)

    try:
        response = await asyncio.to_thread(_model.generate_content, [prompt, text])
        result   = json.loads(_clean_json(response.text))
        if not isinstance(result, list):
            return []
        return [v for v in (_validate_item(i, today) for i in result) if v]
    except Exception as e:
        logger.warning("Gemini text parse failed: %s", e)
        return []


# ── Receipt photo parsing ─────────────────────────────────────────────────────

_PHOTO_PROMPT = """Kamu adalah AI yang membaca struk/nota belanja dari foto.

Baca struk dalam gambar dan ekstrak SETIAP item pengeluaran yang tercantum.
Jika struk memiliki total/subtotal, abaikan — ambil item individual saja.

Tanggal hari ini: {today}

Deteksi mata uang dari simbol/tulisan di struk.
Jika struk bukan IDR, isi "mata_uang" dengan kode ISO 3 huruf dan "nominal" dengan null.

Kembalikan JSON array:
[{{
  "nominal": <integer IDR atau null jika bukan IDR>,
  "nominal_asli": <float nilai di struk>,
  "mata_uang": "<IDR atau kode 3 huruf>",
  "kategori": "<F&B|Transport|Belanja|Hiburan|Tagihan|Kesehatan|Lainnya>",
  "deskripsi": "<nama item, maks 60 karakter, Title Case>",
  "tanggal": "<YYYY-MM-DD dari struk, atau {today} jika tidak ada>"
}}]

Jika gambar bukan struk / tidak terbaca → kembalikan: []
"""


async def parse_receipt_photo(image_bytes: bytes) -> list[dict]:
    today  = date.today().isoformat()
    prompt = _PHOTO_PROMPT.format(today=today)

    try:
        img      = PIL.Image.open(io.BytesIO(image_bytes))
        response = await asyncio.to_thread(_model.generate_content, [prompt, img])
        result   = json.loads(_clean_json(response.text))
        if not isinstance(result, list):
            return []
        # Receipt items are always Pengeluaran
        for item in result:
            item.setdefault("tipe", "Pengeluaran")
        return [v for v in (_validate_item(i, today) for i in result) if v]
    except Exception as e:
        logger.warning("Gemini Vision parse failed: %s", e)
        return []
