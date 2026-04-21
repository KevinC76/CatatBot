import logging
from datetime import date, timedelta

from telegram.ext import Application

from bot import notion_service
from config import config

logger = logging.getLogger(__name__)


def _fmt_rupiah(amount: int) -> str:
    return f"Rp{amount:,}".replace(",", ".")


async def send_weekly_report(context) -> None:
    today = date.today()
    week_ago = today - timedelta(days=6)
    expenses = await notion_service.get_expenses(week_ago.isoformat(), today.isoformat())

    if not expenses:
        text = "📭 Tidak ada pengeluaran minggu ini."
    else:
        total = sum(e["nominal"] for e in expenses)
        by_cat = notion_service.aggregate_by_category(expenses)
        period = f"{week_ago.strftime('%d %b')} – {today.strftime('%d %b %Y')}"

        lines = [
            "📊 *Laporan Mingguan*",
            f"Periode: {period}",
            "",
            f"Total: *{_fmt_rupiah(total)}*",
            "",
            "Breakdown:",
        ]
        for cat, amount in by_cat.items():
            pct = round(amount / total * 100)
            lines.append(f"  • {cat}: {_fmt_rupiah(amount)} ({pct}%)")

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
    # Every Sunday at 20:00 WIB
    # In python-telegram-bot, days=(0,) means Sunday
    app.job_queue.run_daily(
        send_weekly_report,
        time=datetime.time(hour=20, minute=0, tzinfo=wib),
        days=(0,),
        name="weekly_report",
    )
    logger.info("Weekly report scheduler set: Sunday 20:00 WIB")
