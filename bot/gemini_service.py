from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date

import google.generativeai as genai

from config import config

logger = logging.getLogger(__name__)

genai.configure(api_key=config.GEMINI_API_KEY)
_model = genai.GenerativeModel("gemini-2.0-flash")

_PROMPT_TEMPLATE = """Kamu adalah parser pengeluaran untuk bot pencatat keuangan pribadi berbahasa Indonesia.

Ekstrak informasi pengeluaran dari pesan berikut dan kembalikan HANYA JSON valid.

Kategori yang tersedia: F&B, Transport, Belanja, Hiburan, Tagihan, Kesehatan, Lainnya

Tanggal hari ini: {today}

Pesan user: "{message}"

Aturan konversi nominal:
- 35rb / 35ribu = 35000
- 35k = 35000
- 1.5jt / 1,5jt = 1500000
- 35.000 atau 35,000 = 35000
- Selalu dalam Rupiah (IDR), tanpa desimal

Aturan tanggal:
- "kemarin" = {yesterday}
- "tadi" / tidak disebutkan = {today}
- Gunakan format YYYY-MM-DD

Kembalikan JSON:
{{
  "nominal": <integer>,
  "kategori": "<salah satu kategori di atas>",
  "deskripsi": "<deskripsi singkat pengeluaran, maks 80 karakter>",
  "tanggal": "<YYYY-MM-DD>"
}}

Jika tidak bisa mengekstrak nominal yang valid, kembalikan: {{"error": "cannot_parse"}}
"""


def _clean_json(text: str) -> str:
    text = text.strip()
    # strip markdown code blocks
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


async def parse_expense(text: str) -> dict | None:
    today = date.today().isoformat()
    from datetime import timedelta
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    prompt = _PROMPT_TEMPLATE.format(message=text, today=today, yesterday=yesterday)

    try:
        response = await asyncio.to_thread(_model.generate_content, prompt)
        raw = _clean_json(response.text)
        result = json.loads(raw)

        if "error" in result:
            return None

        # Validate required fields
        nominal = int(result.get("nominal", 0))
        if nominal <= 0:
            return None

        valid_categories = {"F&B", "Transport", "Belanja", "Hiburan", "Tagihan", "Kesehatan", "Lainnya"}
        kategori = result.get("kategori", "Lainnya")
        if kategori not in valid_categories:
            kategori = "Lainnya"

        return {
            "nominal": nominal,
            "kategori": kategori,
            "deskripsi": str(result.get("deskripsi", text.strip()))[:100],
            "tanggal": str(result.get("tanggal", today)),
        }

    except Exception as e:
        logger.warning("Gemini parse failed: %s", e)
        return None
