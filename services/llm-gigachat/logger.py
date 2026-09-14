"""
Настройка логирования: в файл + в консоль, с ротацией по дням.
"""
import logging
import logging.handlers
from pathlib import Path

from config import settings


def setup_logging() -> logging.Logger:
    log_path = Path(__file__).parent / settings.log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())

    # Избегаем дублирования хендлеров при повторном вызове (например, при reload)
    if root.handlers:
        for h in list(root.handlers):
            root.removeHandler(h)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Файл с ротацией: один файл в день, храним 7 дней
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_path, when="midnight", backupCount=7, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # Консоль
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    root.addHandler(console_handler)

    return logging.getLogger("agent")


logger = setup_logging()