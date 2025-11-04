import logging
import structlog
from optcoin_bot.config import app_config

def configure_logging():
    shared_processors = [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer() if app_config.log_format == "console" else structlog.processors.JSONRenderer(),
    ]

    structlog.configure(
        processors=shared_processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(level=app_config.log_level, handlers=[logging.StreamHandler()])

configure_logging()

def get_logger(name: str, **kwargs):
    logger = structlog.get_logger(name)
    return logger.bind(**kwargs)
