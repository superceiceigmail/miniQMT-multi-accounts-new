import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional, Iterable

DEFAULT_FMT = "%(asctime)s - %(levelname)s - %(message)s"
DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"

def ensure_utf8_stdio():
    """
    尝试将 stdout/stderr 切到 utf-8，避免控制台编码报错。
    在不支持的环境下静默跳过。
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        try:
            import io
            if hasattr(sys.stdout, "buffer"):
                sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
            if hasattr(sys.stderr, "buffer"):
                sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
        except Exception:
            pass

def setup_logging(
    log_dir: str = "./zz_log",
    level: int = logging.INFO,
    console: bool = True,
    file: bool = True,
    filename_pattern: str = "log_%Y%m%d.log",
    fmt: str = DEFAULT_FMT,
    datefmt: str = DEFAULT_DATEFMT,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 7,
) -> logging.Logger:
    """
    初始化根日志。若已初始化过不会重复添加 handler。
    返回 root logger。
    """
    root = logging.getLogger()
    root.setLevel(level)

    # 避免重复添加 handler
    if root.handlers:
        return root

    formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)

    if file:
        os.makedirs(log_dir, exist_ok=True)
        # 按日期命名
        from datetime import datetime
        filename = datetime.now().strftime(filename_pattern)
        file_path = os.path.join(log_dir, filename)
        fh = RotatingFileHandler(file_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(formatter)
        root.addHandler(fh)

    if console:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(level)
        ch.setFormatter(formatter)
        root.addHandler(ch)

    # 降低第三方库噪音（可按需调整）
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    return root

class LogCollector:
    """
    用于同时写日志并收集文本（便于 Gradio/GUI 一并展示）。
    """
    def __init__(self, prefix_lines: Optional[Iterable[str]] = None):
        self.lines = []
        if prefix_lines:
            self.lines.extend(prefix_lines)

    def append(self, msg: str):
        self.lines.append(msg)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

def emit(logger: logging.Logger, msg: str, level: str = "info", collector: Optional[LogCollector] = None):
    """
    统一日志输出。level 支持 info/warning/error/debug。
    若传入 collector，则同时收集文本。
    """
    lvl = level.lower()
    if lvl == "error":
        logger.error(msg)
    elif lvl == "warning":
        logger.warning(msg)
    elif lvl == "debug":
        logger.debug(msg)
    else:
        logger.info(msg)

    if collector is not None:
        collector.append(msg)

def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    获取模块 logger（模块内建议 get_logger(__name__)）。
    """
    return logging.getLogger(name if name else __name__)