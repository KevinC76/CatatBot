from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, timedelta

import google.generativeai as genai

from config import config

logger = logging.getLogger(__name__)

genai.configure(api_key=config.GEMINI_API_KEY)
_model = genai.GenerativeModel("gemini-2.0-flash")

_PROMPT_TEMPLATE = """Kamu adalah parser pengeluaran untuk bot pencatat keuangan pribadi berbahasa Indonesia.

Ekstrak SEMUA pengeluaran dari pesan berikut. Jika ada beberapa pengeluaran dalam satu pesan, kembalikan semuanya.

Kategori yang tersedia: F&B, Transport, Belanja, Hiburan, Tagihan, Kesehatan, Lainnya

Tanggal hari ini: {today}

Pesan user: "{message}"

Aturan konversi nominal:
- 35rb / 35ribu = 35000
- 35k = 35000
- 1.5jt / 1,5jt = 1500000
- 35.000 atau 35,000 = 35000
- Selalu dalam Rupiah (IDR), tanpa desimal

Aturan deskripsi:
- Tulis nama barang/jasa saja, TANPA nominal dan TANPA satuan (rb/k/jt)
- Contoh: "nasi padang 25k" → deskripsi = "Nasi padang"
- Contoh: "grab ke kantor 15rb" → deskripsi = "Grab ke kantor"
- Maksimal 60 karakter, gunakan Title Case

Aturan tanggal:
- "kemarin" = {yesterday}
- "tadi" / tidak disebutkan = {today}
- Gunakan format YYYY-MM-DD

Kembalikan JSON array (selalu array, meski hanya 1 item):
[
  {{
    "nominal": <integer>,
    "kategori": "<salah satu kategori di atas>",
    "deskripsi": "<nama barang/jasa saja, tanpa nominal>",
    "tanggal": "<YYYY-MM-DD>"
  }}
]

Jika tidak ada pengeluaran yang bisa diekstrak, kembalikan: []
"""


def _clean_json(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


_VALID_CATEGORIES = {"F&B", "Transport", "Belanja", "Hiburan", "Tagihan", "Kesehatan", "Lainnya"}


def _validate_item(item: dict, today: str) -> dict | None:
    try:
        nominal = int(item.get("nominal", 0))
        if nominal <= 0:
            return None
        kategori = item.get("kategori", "Lainnya")
        if kategori not in _VALID_CATEGORIES:
            kategori = "Lainnya"
        return {
            "nominal": nominal,
            "kategori": kategori,
            "deskripsi": str(item.get("deskripsi", ""))[:80].strip(),
            "tanggal": str(item.get("tanggal", today)),
        }
    except (ValueError, TypeError):
        return None


async def parse_expenses(text: str) -> list[dict]:
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    prompt = _PROMPT_TEMPLATE.format(message=text, today=today, yesterday=yesterday)

    try:
        response = await asyncio.to_thread(_model.generate_content, prompt)
        raw = _clean_json(response.text)
        result = json.loads(raw)

        if not isinstance(result, list):
            return []

        validated = [_validate_item(item, today) for item in result]
        return [item for item in validated if item is not None]

    except Exception as e:
        logger.warning("Gemini parse failed: %s", e)
        return []
