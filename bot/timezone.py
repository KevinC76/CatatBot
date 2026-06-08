from __future__ import annotations

from datetime import date, datetime

import pytz

WIB = pytz.timezone("Asia/Jakarta")


def today_wib() -> date:
    return datetime.now(WIB).date()
