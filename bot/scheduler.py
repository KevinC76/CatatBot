from __future__ import annotations

import logging
from datetime import date, timedelta

from telegram.ext import Application

from bot import notion_service
from config import config

logger = logging.getLogger(__name__)


def _fmt_rupiah(amount: int) -> str:
    return f"Rp{amount:,}".replace(",", ".")


async def send_weekly_report(context) -> None:
    today    = date.today()
    week_ago = today - timedelta(days=6)
    all_tx   = await notion_service.get_expenses(week_ago.isoformat(), today.isoformat())

    out, inc  = notion_service.split_by_tipe(all_tx)
    total_out = sum(e["nominal"] for e in out)
    total_in  = sum(e["nominal"] for e in inc)
    net       = total_in - total_out
    period    = f"{week_ago.strftime('%d %b')} – {today.strftime('%d %b %Y')}"

    if not all_tx:
        text = f"📭 Tidak ada transaksi minggu ini ({period})."
    else:
        net_str = f"+{_fmt_rupiah(net)}" if net >= 0 else f"-{_fmt_rupiah(abs(net))}"
        lines = [
            "📊 *Laporan Mingguan*",
            f"Periode: {period}",
            "",
        ]

        if inc:
            lines.append(f"💰 *Pemasukan: {_fmt_rupiah(total_in)}*")
            for cat, amt in notion_service.aggregate_by_category(inc).items():
                lines.append(f"  • {cat}: {_fmt_rupiah(amt)}")
            lines.append("")

        if out:
            lines.append(f"💸 *Pengeluaran: {_fmt_rupiah(total_out)}*")
            for cat, amt in notion_service.aggregate_by_category(out).items():
                pct = round(amt / total_out * 100)
                lines.append(f"  • {cat}: {_fmt_rupiah(amt)} ({pct}%)")
            lines.append("")

        lines.append(f"{'📈' if net >= 0 else '📉'} *Net: {net_str}*")
        text = "\n".join(lines)

    await context.bot.send_message(
        chat_id=config.TELEGRAM_USER_ID,
        text=text,
        parse_mode="Markdown",
    )


def setup_scheduler(app: Application) -> None:
    import datetime
    import pytz

    wib = pytz.timezone("Asia/Jakarta")
    app.job_queue.run_daily(
        send_weekly_report,
        time=datetime.time(hour=20, minute=0, tzinfo=wib),
        days=(0,),
        name="weekly_report",
    )
    logger.info("Scheduler set: weekly report every Sunday 20:00 WIB")
