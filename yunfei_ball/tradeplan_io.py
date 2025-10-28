import os
import json
import time
from contextlib import contextmanager
from filelock import FileLock

# 配置：保证这些目录存在（相对于 yunfei_ball 文件夹）
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__)))
TRADEPLAN_DIR = os.path.join(BASE_DIR, 'trade_plan')         # per-strategy files root (yunfei_ball/trade_plan)
PROCESSED_DIR = os.path.join(TRADEPLAN_DIR, 'processed')

os.makedirs(TRADEPLAN_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)

def atomic_write_json(path: str, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def read_json(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

@contextmanager
def file_lock_for(path, timeout=10):
    """
    给一个文件路径创建 file-based lock（使用 filelock 库）
    用法:
        with file_lock_for(lockfile):
            do_stuff()
    """
    lock_path = path + '.lock'
    lock = FileLock(lock_path, timeout=timeout)
    lock.acquire()
    try:
        yield
    finally:
        lock.release()

def list_strategy_files(batch: str = None, account_id: str = None, setting_dir=None):
    """
    列出 trade_plan 目录下所有未处理的策略文件（可按 batch/account 过滤）
    注意：setting_dir 为绝对或相对路径（若 None，使用 TRADEPLAN_DIR）
    """
    dir_to_search = setting_dir if setting_dir else TRADEPLAN_DIR
    files = []
    try:
        for fn in os.listdir(dir_to_search):
            if not fn.endswith('.json'):
                continue
            # 排除 final/merged 文件（文件名中包含 'final' 或 'merged'）
            if 'final' in fn or 'merged' in fn:
                continue
            if fn.startswith('yunfei_trade_plan_draft_batch'):
                if batch and f"batch{batch}" not in fn:
                    continue
                if account_id and account_id not in fn:
                    continue
                files.append(os.path.join(dir_to_search, fn))
    except Exception:
        pass
    files.sort()
    return files

def mark_processed(path: str):
    basename = os.path.basename(path)
    dst = os.path.join(PROCESSED_DIR, basename)
    # 用 os.replace 保证原子移动（同盘）
    os.replace(path, dst)
    return dst