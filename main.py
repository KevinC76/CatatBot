from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot.handlers import (
    bulan_ini,
    handle_expense,
    handle_photo,
    handle_receipt_callback,
    hari_ini,
    pemasukan,
    rekap,
    saldo,
    start,
)
from bot.scheduler import send_weekly_report, setup_scheduler
from config import config

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.DEBUG,
)
logger = logging.getLogger(__name__)


def _is_serverless() -> bool:
    return bool(os.getenv("VERCEL") or os.getenv("WEBHOOK_MODE"))


def _register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start",     start))
    application.add_handler(CommandHandler("rekap",     rekap))
    application.add_handler(CommandHandler("hari_ini",  hari_ini))
    application.add_handler(CommandHandler("bulan_ini", bulan_ini))
    application.add_handler(CommandHandler("saldo",     saldo))
    application.add_handler(CommandHandler("pemasukan", pemasukan))
    application.add_handler(CallbackQueryHandler(handle_receipt_callback, pattern="^receipt_"))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_expense))


def _build_ptb_application() -> Application:
    builder = Application.builder().token(config.TELEGRAM_BOT_TOKEN)
    if _is_serverless():
        # No persistent loop on serverless → disable updater + job_queue
        builder = builder.updater(None)
    application = builder.build()
    _register_handlers(application)
    return application


# ── Webhook (Vercel) entry ────────────────────────────────────────────────────

@asynccontextmanager
async def _lifespan(api: FastAPI):
    ptb = _build_ptb_application()
    await ptb.initialize()
    api.state.ptb = ptb
    logger.info("CatatBot webhook initialized")
    try:
        yield
    finally:
        await ptb.shutdown()


app = FastAPI(lifespan=_lifespan)


@app.get("/")
async def health() -> dict:
    return {"status": "ok", "mode": "webhook" if _is_serverless() else "polling"}


@app.post("/api/webhook")
async def telegram_webhook(request: Request) -> dict:
    data = await request.json()
    update = Update.de_json(data, app.state.ptb.bot)
    await app.state.ptb.process_update(update)
    return {"ok": True}


def _check_cron_auth(request: Request) -> None:
    if not config.CRON_SECRET:
        return
    expected = f"Bearer {config.CRON_SECRET}"
    if request.headers.get("authorization") != expected:
        raise HTTPException(status_code=401, detail="unauthorized")


@app.post("/api/cron/weekly")
@app.get("/api/cron/weekly")
async def cron_weekly(request: Request) -> dict:
    _check_cron_auth(request)
    await send_weekly_report(SimpleNamespace(bot=app.state.ptb.bot))
    return {"ok": True}


# ── Polling (local / worker) entry ────────────────────────────────────────────

def main() -> None:
    application = _build_ptb_application()
    setup_scheduler(application)
    logger.info("CatatBot starting (polling)...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
