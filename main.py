import logging

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
from bot.scheduler import setup_scheduler
from config import config

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.DEBUG,
)
logger = logging.getLogger(__name__)


def main() -> None:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start",      start))
    app.add_handler(CommandHandler("rekap",      rekap))
    app.add_handler(CommandHandler("hari_ini",   hari_ini))
    app.add_handler(CommandHandler("bulan_ini",  bulan_ini))
    app.add_handler(CommandHandler("saldo",      saldo))
    app.add_handler(CommandHandler("pemasukan",  pemasukan))

    # Inline keyboard callbacks (foto struk confirmation)
    app.add_handler(CallbackQueryHandler(handle_receipt_callback, pattern="^receipt_"))

    # Photo messages (struk)
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # Text messages (expense / income)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_expense))

    setup_scheduler(app)

    logger.info("CatatBot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
