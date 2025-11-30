"""
BetterForward - A Telegram bot for forwarding messages with topic support.
Entry point for the application.
"""

from src.bot import TGBot
from src.config import args, logger, _

if __name__ == "__main__":
    if not args.token or not args.group_id:
        logger.error(_("Token or group ID is empty"))
        exit(1)
    try:
        bot = TGBot(
            args.token,
            args.group_id,
            num_workers=args.workers,
            ai_api_key=args.ai_api_key or None,
            ai_api_base=args.ai_api_base or None,
            ai_model=args.ai_model,
        )
    except KeyboardInterrupt:
        logger.info(_("Exiting..."))
        exit(0)
