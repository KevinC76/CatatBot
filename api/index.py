from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request

# Vercel mounts each function file in isolation; ensure the project root
# (which contains `bot/` and `config.py`) is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telegram import Update  # noqa: E402
from telegram.ext import (  # noqa: E402
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot.handlers import (  # noqa: E402
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
from bot.scheduler import send_weekly_report  # noqa: E402
from config import config  # noqa: E402

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def _build_ptb_application() -> Application:
    # Webhook mode: no updater, no job_queue (serverless has no persistent loop)
    application = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .updater(None)
        .build()
    )
    application.add_handler(CommandHandler("start",     start))
    application.add_handler(CommandHandler("rekap",     rekap))
    application.add_handler(CommandHandler("hari_ini",  hari_ini))
    application.add_handler(CommandHandler("bulan_ini", bulan_ini))
    application.add_handler(CommandHandler("saldo",     saldo))
    application.add_handler(CommandHandler("pemasukan", pemasukan))
    application.add_handler(CallbackQueryHandler(handle_receipt_callback, pattern="^receipt_"))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_expense))
    return application


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
    return {"status": "ok", "mode": "webhook"}


@app.post("/api/webhook")
async def telegram_webhook(request: Request) -> dict:
    data = await request.json()
    update = Update.de_json(data, app.state.ptb.bot)
    await app.state.ptb.process_update(update)
    return {"ok": True}


def _check_cron_auth(request: Request) -> None:
    if not config.CRON_SECRET:
        return
    if request.headers.get("authorization") != f"Bearer {config.CRON_SECRET}":
        raise HTTPException(status_code=401, detail="unauthorized")


@app.post("/api/cron/weekly")
@app.get("/api/cron/weekly")
async def cron_weekly(request: Request) -> dict:
    _check_cron_auth(request)
    await send_weekly_report(SimpleNamespace(bot=app.state.ptb.bot))
    return {"ok": True}
