import logging

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from bot.handlers import bulan_ini, handle_expense, hari_ini, rekap, start
from bot.scheduler import setup_scheduler
from config import config

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rekap", rekap))
    app.add_handler(CommandHandler("hari_ini", hari_ini))
    app.add_handler(CommandHandler("bulan_ini", bulan_ini))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_expense))

    setup_scheduler(app)

    logger.info("CatatBot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
