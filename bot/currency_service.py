from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

_rate_cache: dict[str, tuple[float, datetime]] = {}
_CACHE_TTL = timedelta(hours=1)

# Symbol → currency code
_SYMBOL_MAP: dict[str, str] = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
}

# ISO codes supported
_CODES: set[str] = {
    "USD", "EUR", "GBP", "JPY", "SGD", "MYR",
    "AUD", "CNY", "KRW", "THB", "SAR", "AED",
}

# Name patterns (longest first for priority matching)
_NAME_PATTERNS: list[tuple[str, str]] = [
    (r"us\s*dollar", "USD"),
    (r"american\s*dollar", "USD"),
    (r"dollar", "USD"),
    (r"pound\s*sterling", "GBP"),
    (r"pound", "GBP"),
    (r"euro", "EUR"),
    (r"yen", "JPY"),
    (r"jen", "JPY"),
    (r"singapore\s*dollar", "SGD"),
    (r"sing\s*dollar", "SGD"),
    (r"ringgit\s*malaysia", "MYR"),
    (r"ringgit", "MYR"),
    (r"korean\s*won", "KRW"),
    (r"won", "KRW"),
    (r"thai\s*baht", "THB"),
    (r"baht", "THB"),
    (r"renminbi", "CNY"),
    (r"yuan", "CNY"),
    (r"australian\s*dollar", "AUD"),
    (r"aussie", "AUD"),
    (r"dirham", "AED"),
    (r"riyal", "SAR"),
]

_NUM = r"(\d+(?:[.,]\d+)?)"


def detect_foreign_currency(text: str) -> tuple[str | None, float | None]:
    """
    Detect a foreign (non-IDR) currency and amount in text.
    Returns (currency_code, original_amount) or (None, None).
    """
    t = text.strip()

    # Symbol before number: $10, €5.50
    m = re.search(rf"([$€£¥])\s*{_NUM}", t)
    if m:
        currency = _SYMBOL_MAP.get(m.group(1))
        if currency:
            return currency, float(m.group(2).replace(",", "."))

    # Number + ISO code: 10 USD, 100JPY, 10usd
    code_pattern = "|".join(_CODES)
    m = re.search(rf"{_NUM}\s*({code_pattern})\b", t, re.IGNORECASE)
    if m:
        return m.group(2).upper(), float(m.group(1).replace(",", "."))

    # Number + currency name: 10 dollar, 100 yen, 10 US dollar
    for pattern, code in _NAME_PATTERNS:
        m = re.search(rf"{_NUM}\s+{pattern}s?\b", t, re.IGNORECASE)
        if m:
            return code, float(m.group(1).replace(",", "."))

    return None, None


async def get_idr_rate(currency: str) -> float | None:
    """Return how many IDR equals 1 unit of `currency`. Uses cache (1h TTL)."""
    if currency == "IDR":
        return 1.0

    cached = _rate_cache.get(currency)
    if cached and datetime.now() - cached[1] < _CACHE_TTL:
        return cached[0]

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"https://open.er-api.com/v6/latest/{currency}",
                headers={"Accept": "application/json"},
            )
            data = resp.json()
            if data.get("result") == "success":
                rate = float(data["rates"]["IDR"])
                _rate_cache[currency] = (rate, datetime.now())
                logger.info("Rate fetched: 1 %s = %.2f IDR", currency, rate)
                return rate
    except Exception as e:
        logger.warning("Currency API error (%s): %s", currency, e)

    # Stale cache fallback
    if currency in _rate_cache:
        logger.warning("Using stale rate cache for %s", currency)
        return _rate_cache[currency][0]

    return None


async def convert_to_idr(currency: str, amount: float) -> tuple[int, float] | tuple[None, None]:
    """Convert `amount` in `currency` to IDR. Returns (idr_int, rate) or (None, None)."""
    rate = await get_idr_rate(currency)
    if rate is None:
        return None, None
    return round(amount * rate), rate
