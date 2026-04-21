import logging
from datetime import date, timedelta
from functools import wraps

from telegram import Update
from telegram.ext import ContextTypes

from bot import gemini_service, notion_service
from bot.parser import parse_expense
from config import config

logger = logging.getLogger(__name__)


def _fmt_rupiah(amount: int) -> str:
    return f"Rp{amount:,}".replace(",", ".")


def _fmt_report(expenses: list[dict], title: str, period: str) -> str:
    if not expenses:
        return f"📭 Tidak ada pengeluaran untuk {period}."

    total = sum(e["nominal"] for e in expenses)
    by_cat = notion_service.aggregate_by_category(expenses)

    lines = [f"📊 *{title}*", f"Periode: {period}", f"", f"Total: *{_fmt_rupiah(total)}*", "", "Breakdown:"]
    for cat, amount in by_cat.items():
        pct = round(amount / total * 100)
        lines.append(f"  • {cat}: {_fmt_rupiah(amount)} ({pct}%)")

    return "\n".join(lines)


def whitelist_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != config.TELEGRAM_USER_ID:
            await update.message.reply_text("⛔ Maaf, bot ini bersifat private.")
            return
        return await func(update, context)
    return wrapper


@whitelist_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 *Halo! Saya CatatBot.*\n\n"
        "Catat pengeluaran kamu cukup dengan kirim pesan biasa. Contoh:\n\n"
        "  • `makan siang padang 35rb`\n"
        "  • `grab ke kantor 25000`\n"
        "  • `bayar listrik 150rb`\n"
        "  • `kemarin nonton bioskop 75k`\n\n"
        "*Commands:*\n"
        "  /rekap — rekap minggu berjalan\n"
        "  /hari\\_ini — pengeluaran hari ini\n"
        "  /bulan\\_ini — rekap bulan berjalan\n\n"
        "Laporan mingguan otomatis dikirim setiap Minggu pukul 20.00 WIB. 🗓"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


@whitelist_only
async def handle_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()

    # Try Gemini first, fallback to rule-based
    parsed = await gemini_service.parse_expense(text)
    if parsed is None:
        parsed = parse_expense(text)

    if parsed is None:
        await update.message.reply_text(
            "❓ Maaf, saya tidak bisa membaca pengeluarannya.\n"
            "Coba format seperti: `makan siang 35rb` atau `grab 25000`",
            parse_mode="Markdown",
        )
        return

    nominal = parsed["nominal"]
    kategori = parsed["kategori"]
    deskripsi = parsed["deskripsi"]
    tanggal = parsed["tanggal"]

    saved = await notion_service.save_expense(nominal, kategori, deskripsi, tanggal)

    if saved:
        await update.message.reply_text(
            f"✅ *{deskripsi}* — {_fmt_rupiah(nominal)} [{kategori}]",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "❌ Gagal menyimpan ke Notion. Silakan coba lagi.",
        )


@whitelist_only
async def rekap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    expenses = await notion_service.get_expenses(monday.isoformat(), today.isoformat())
    period = f"{monday.strftime('%d %b')} – {today.strftime('%d %b %Y')}"
    await update.message.reply_text(
        _fmt_report(expenses, "Rekap Minggu Ini", period),
        parse_mode="Markdown",
    )


@whitelist_only
async def hari_ini(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = date.today().isoformat()
    expenses = await notion_service.get_expenses(today, today)

    if not expenses:
        await update.message.reply_text("📭 Belum ada pengeluaran hari ini.")
        return

    total = sum(e["nominal"] for e in expenses)
    lines = [f"📋 *Pengeluaran Hari Ini*", ""]
    for e in expenses:
        lines.append(f"  • {e['deskripsi']} — {_fmt_rupiah(e['nominal'])} [{e['kategori']}]")
    lines += ["", f"Total: *{_fmt_rupiah(total)}*"]

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@whitelist_only
async def bulan_ini(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = date.today()
    first_day = today.replace(day=1)
    expenses = await notion_service.get_expenses(first_day.isoformat(), today.isoformat())
    period = today.strftime("%B %Y")
    await update.message.reply_text(
        _fmt_report(expenses, "Rekap Bulan Ini", period),
        parse_mode="Markdown",
    )
