from __future__ import annotations

import io
import logging
from datetime import date, timedelta
from functools import wraps

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot import currency_service, gemini_service, notion_service
from bot.parser import parse_expenses
from config import config

logger = logging.getLogger(__name__)


# ── Formatting helpers ────────────────────────────────────────────────────────

def _fmt_rupiah(amount: int) -> str:
    return f"Rp{amount:,}".replace(",", ".")


def _fmt_item_confirm(item: dict) -> str:
    emoji = "💰" if item.get("tipe") == "Pemasukan" else "✅"
    desc  = item["deskripsi"]
    cat   = item["kategori"]
    tipe  = item.get("tipe", "Pengeluaran")

    if item.get("mata_uang", "IDR") != "IDR":
        currency = item["mata_uang"]
        asli     = item["nominal_asli"]
        idr      = item["nominal"]
        kurs     = int(item.get("kurs", 0))
        return (
            f"{emoji} *{desc}* — {currency} {asli:g} → {_fmt_rupiah(idr)}"
            f" (kurs {_fmt_rupiah(kurs)}) [{cat}] [{tipe}]"
        )
    return f"{emoji} *{desc}* — {_fmt_rupiah(item['nominal'])} [{cat}] [{tipe}]"


def _fmt_report(
    pengeluaran: list[dict],
    pemasukan: list[dict],
    title: str,
    period: str,
) -> str:
    total_out = sum(e["nominal"] for e in pengeluaran)
    total_in  = sum(e["nominal"] for e in pemasukan)
    net       = total_in - total_out

    if not pengeluaran and not pemasukan:
        return f"📭 Tidak ada transaksi untuk {period}."

    lines = [f"📊 *{title}*", f"Periode: {period}", ""]

    if pemasukan:
        lines += [f"💰 *Pemasukan: {_fmt_rupiah(total_in)}*"]
        by_cat = notion_service.aggregate_by_category(pemasukan)
        for cat, amt in by_cat.items():
            lines.append(f"  • {cat}: {_fmt_rupiah(amt)}")
        lines.append("")

    if pengeluaran:
        lines += [f"💸 *Pengeluaran: {_fmt_rupiah(total_out)}*"]
        by_cat = notion_service.aggregate_by_category(pengeluaran)
        for cat, amt in by_cat.items():
            pct = round(amt / total_out * 100)
            lines.append(f"  • {cat}: {_fmt_rupiah(amt)} ({pct}%)")
        lines.append("")

    net_str = f"+{_fmt_rupiah(net)}" if net >= 0 else f"-{_fmt_rupiah(abs(net))}"
    lines.append(f"{'📈' if net >= 0 else '📉'} *Net: {net_str}*")
    return "\n".join(lines)


# ── Whitelist decorator ───────────────────────────────────────────────────────

def whitelist_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id != config.TELEGRAM_USER_ID:
            if update.message:
                await update.message.reply_text("⛔ Maaf, bot ini bersifat private.")
            return
        return await func(update, context)
    return wrapper


# ── Currency conversion helper ────────────────────────────────────────────────

async def _resolve_currency(items: list[dict], update: Update) -> list[dict] | None:
    """Convert foreign currency items to IDR in-place. Returns None on failure."""
    for item in items:
        if item.get("mata_uang", "IDR") != "IDR" and item.get("nominal_asli"):
            idr, rate = await currency_service.convert_to_idr(
                item["mata_uang"], item["nominal_asli"]
            )
            if idr is None:
                await update.message.reply_text(
                    f"⚠️ Gagal mengambil kurs *{item['mata_uang']}*. "
                    "Coba lagi atau ketik nominalnya dalam Rupiah.",
                    parse_mode="Markdown",
                )
                return None
            item["nominal"] = idr
            item["kurs"]    = rate
    return items


# ── Command: /start ───────────────────────────────────────────────────────────

@whitelist_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 *Halo! Saya CatatBot.*\n\n"
        "Catat pengeluaran atau pemasukan cukup dengan pesan biasa:\n\n"
        "  • `makan siang padang 35rb`\n"
        "  • `grab ke kantor 25000`\n"
        "  • `gajian bulan ini 5jt` 💰\n"
        "  • `nasi padang 25000, es teh 5000`\n"
        "  • `$10 dinner` 🌏\n"
        "  • `100 yen oleh-oleh` 🌏\n\n"
        "📸 *Kirim foto struk* → AI baca otomatis!\n\n"
        "*Commands:*\n"
        "  /rekap — pengeluaran minggu ini\n"
        "  /hari\\_ini — transaksi hari ini\n"
        "  /bulan\\_ini — rekap bulan berjalan\n"
        "  /saldo — net cashflow bulan ini 💰\n"
        "  /pemasukan — rekap pemasukan bulan ini\n\n"
        "Laporan mingguan otomatis tiap Minggu 20.00 WIB 🗓"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ── Message: expense/income text ─────────────────────────────────────────────

@whitelist_only
async def handle_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()

    items = await gemini_service.parse_expenses(text)
    if not items:
        items = parse_expenses(text)

    if not items:
        await update.message.reply_text(
            "❓ Maaf, tidak bisa membaca transaksinya.\n"
            "Coba format seperti: `makan siang 35rb` atau `gajian 5jt`",
            parse_mode="Markdown",
        )
        return

    items = await _resolve_currency(items, update)
    if items is None:
        return

    lines = []
    for item in items:
        saved = await notion_service.save_expense(
            nominal=item["nominal"],
            kategori=item["kategori"],
            deskripsi=item["deskripsi"],
            tanggal=item["tanggal"],
            tipe=item.get("tipe", "Pengeluaran"),
            mata_uang=item.get("mata_uang", "IDR"),
            nominal_asli=item.get("nominal_asli"),
            kurs=item.get("kurs"),
        )
        if saved:
            lines.append(_fmt_item_confirm(item))
        else:
            lines.append(f"❌ Gagal simpan: {item['deskripsi']}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── Message: photo (struk) ────────────────────────────────────────────────────

@whitelist_only
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("📸 Membaca struk, tunggu sebentar...")

    photo    = update.message.photo[-1]
    file     = await context.bot.get_file(photo.file_id)
    buf      = io.BytesIO()
    await file.download_to_memory(buf)
    img_bytes = buf.getvalue()

    items = await gemini_service.parse_receipt_photo(img_bytes)

    if not items:
        await update.message.reply_text(
            "😕 Struk tidak terbaca.\n"
            "Pastikan foto jelas dan tidak buram, atau ketik manual."
        )
        return

    items = await _resolve_currency(items, update)
    if items is None:
        return

    total = sum(i["nominal"] for i in items)
    lines = ["📋 *Struk terdeteksi:*", ""]
    for item in items:
        if item.get("mata_uang", "IDR") != "IDR":
            lines.append(
                f"• {item['deskripsi']} — {item['mata_uang']} {item['nominal_asli']:g}"
                f" → {_fmt_rupiah(item['nominal'])} [{item['kategori']}]"
            )
        else:
            lines.append(f"• {item['deskripsi']} — {_fmt_rupiah(item['nominal'])} [{item['kategori']}]")
    lines += ["", f"*Total: {_fmt_rupiah(total)}*", "", "Simpan semua ke Notion?"]

    context.user_data["pending_receipt"] = items

    keyboard = [[
        InlineKeyboardButton("✅ Simpan", callback_data="receipt_save"),
        InlineKeyboardButton("❌ Batal",  callback_data="receipt_cancel"),
    ]]
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@whitelist_only
async def handle_receipt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "receipt_save":
        items = context.user_data.pop("pending_receipt", [])
        if not items:
            await query.edit_message_text("⚠️ Data struk sudah tidak tersedia.")
            return

        saved = 0
        for item in items:
            ok = await notion_service.save_expense(
                nominal=item["nominal"],
                kategori=item["kategori"],
                deskripsi=item["deskripsi"],
                tanggal=item["tanggal"],
                tipe=item.get("tipe", "Pengeluaran"),
                mata_uang=item.get("mata_uang", "IDR"),
                nominal_asli=item.get("nominal_asli"),
                kurs=item.get("kurs"),
            )
            if ok:
                saved += 1

        total = saved
        await query.edit_message_text(f"✅ {total} item berhasil disimpan ke Notion.")

    elif query.data == "receipt_cancel":
        context.user_data.pop("pending_receipt", None)
        await query.edit_message_text("❌ Batal. Struk tidak disimpan.")


# ── Commands: rekap, hari_ini, bulan_ini ─────────────────────────────────────

@whitelist_only
async def rekap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today  = date.today()
    monday = today - timedelta(days=today.weekday())
    all_tx = await notion_service.get_expenses(monday.isoformat(), today.isoformat())
    out, inc = notion_service.split_by_tipe(all_tx)
    period = f"{monday.strftime('%d %b')} – {today.strftime('%d %b %Y')}"
    await update.message.reply_text(
        _fmt_report(out, inc, "Rekap Minggu Ini", period), parse_mode="Markdown"
    )


@whitelist_only
async def hari_ini(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today  = date.today().isoformat()
    all_tx = await notion_service.get_expenses(today, today)

    if not all_tx:
        await update.message.reply_text("📭 Belum ada transaksi hari ini.")
        return

    out, inc = notion_service.split_by_tipe(all_tx)
    total_out = sum(e["nominal"] for e in out)
    total_in  = sum(e["nominal"] for e in inc)

    lines = ["📋 *Transaksi Hari Ini*", ""]
    for e in inc:
        lines.append(f"  💰 {e['deskripsi']} — {_fmt_rupiah(e['nominal'])} [{e['kategori']}]")
    for e in out:
        lines.append(f"  💸 {e['deskripsi']} — {_fmt_rupiah(e['nominal'])} [{e['kategori']}]")

    lines.append("")
    if inc:
        lines.append(f"Pemasukan: *{_fmt_rupiah(total_in)}*")
    if out:
        lines.append(f"Pengeluaran: *{_fmt_rupiah(total_out)}*")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@whitelist_only
async def bulan_ini(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today     = date.today()
    first_day = today.replace(day=1)
    all_tx    = await notion_service.get_expenses(first_day.isoformat(), today.isoformat())
    out, inc  = notion_service.split_by_tipe(all_tx)
    period    = today.strftime("%B %Y")
    await update.message.reply_text(
        _fmt_report(out, inc, "Rekap Bulan Ini", period), parse_mode="Markdown"
    )


# ── Command: /saldo ───────────────────────────────────────────────────────────

@whitelist_only
async def saldo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today     = date.today()
    first_day = today.replace(day=1)
    all_tx    = await notion_service.get_expenses(first_day.isoformat(), today.isoformat())
    out, inc  = notion_service.split_by_tipe(all_tx)

    total_out = sum(e["nominal"] for e in out)
    total_in  = sum(e["nominal"] for e in inc)
    net       = total_in - total_out
    net_str   = f"+{_fmt_rupiah(net)}" if net >= 0 else f"-{_fmt_rupiah(abs(net))}"

    lines = [
        f"💳 *Saldo Bulan Ini* ({today.strftime('%B %Y')})",
        "",
        f"💰 Pemasukan  : *{_fmt_rupiah(total_in)}*",
        f"💸 Pengeluaran: *{_fmt_rupiah(total_out)}*",
        "──────────────",
        f"{'📈' if net >= 0 else '📉'} Net Cashflow : *{net_str}*",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── Command: /pemasukan ───────────────────────────────────────────────────────

@whitelist_only
async def pemasukan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today     = date.today()
    first_day = today.replace(day=1)
    all_tx    = await notion_service.get_expenses(first_day.isoformat(), today.isoformat())
    _, inc    = notion_service.split_by_tipe(all_tx)

    if not inc:
        await update.message.reply_text("📭 Belum ada pemasukan bulan ini.")
        return

    total  = sum(e["nominal"] for e in inc)
    by_cat = notion_service.aggregate_by_category(inc)

    lines = [f"💰 *Pemasukan {today.strftime('%B %Y')}*", ""]
    for cat, amt in by_cat.items():
        lines.append(f"  • {cat}: {_fmt_rupiah(amt)}")
    lines += ["", f"Total: *{_fmt_rupiah(total)}*"]

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
