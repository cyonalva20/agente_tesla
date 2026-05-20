import logging
import os
from logging.handlers import RotatingFileHandler

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

_FMT = "%(asctime)s | %(levelname)-5s | %(message)s"
_DATE = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(f"tesla.{name}")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    fmt = logging.Formatter(_FMT, _DATE)

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    fh = RotatingFileHandler(
        os.path.join(_LOG_DIR, "agente_tesla.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger
