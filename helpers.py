# helpers.py — 通用 helper 与服务封装（console filter、arg 解析、cron 注册、xt_trader init、信号处理、tradeplan 读写）
import os
import sys
import json
import time
import logging
import argparse
import traceback
from datetime import datetime
import argparse

import psutil
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from processor.asset_connector import print_account_asset as _print_account_asset
from processor.position_connector import print_positions as _print_positions
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from yunfei_ball.yunfei_connect_follow import fetch_and_check_batch_with_trade_plan, INPUT_JSON

# 云飞与自动交易时间常量（可放到 config 文件）
YUNFEI_SCHEDULE_TIMES = [
    "14:52:00",
    "13:00:05",
    "13:31:20",
    "14:51:25",
]
AUTO_BUY_511880_TIME = (9, 33, 0)
AUTO_SELL_511880_TIME = (14, 56, 0)

# ----------------- Console stream filter -----------------
class _FilteredStream:
    def __init__(self, underlying_stream, banned_substrings):
        self._stream = underlying_stream
        self._banned = [s.lower() for s in banned_substrings]
        for attr in ("encoding", "errors", "fileno", "buffer"):
            if hasattr(underlying_stream, attr):
                setattr(self, attr, getattr(underlying_stream, attr))

    def write(self, s):
        try:
            if not s:
                return
            if not isinstance(s, str):
                try:
                    s = s.decode(getattr(self._stream, "encoding", "utf-8") or "utf-8")
                except Exception:
                    return self._stream.write(s)
            lower = s.lower()
            for b in self._banned:
                if b in lower:
                    return
            return self._stream.write(s)
        except Exception:
            try:
                return self._stream.write(s)
            except Exception:
                return

    def writelines(self, lines):
        for ln in lines:
            self.write(ln)

    def flush(self):
        try:
            return self._stream.flush()
        except Exception:
            pass

    def __getattr__(self, item):
        return getattr(self._stream, item)

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--account', required=True, help='账户别名或ID')
    parser.add_argument('--ui-id', required=False, help='来自 GUI 的唯一进程标识（可选）')
    return parser.parse_args()

def install_console_stream_filters():
    try:
        suppress_env = os.environ.get("SUPPRESS_BSON_ERRORS", "1").lower()
        suppress_enabled = suppress_env not in ("0", "false", "no")
        if not suppress_enabled:
            return False
        banned_list = [
            "get bson value error",
            "bad lexical cast"
        ]
        if not isinstance(sys.stdout, _FilteredStream):
            sys.stdout = _FilteredStream(sys.stdout, banned_list)
        if not isinstance(sys.stderr, _FilteredStream):
            sys.stderr = _FilteredStream(sys.stderr, banned_list)
        return True
    except Exception:
        return False

# ----------------- argparse / single instance -----------------
def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--account', required=True, help='账户别名或ID')
    return parser.parse_args()

def check_duplicate_instance(script_name: str, account_name: str) -> bool:
    current_pid = os.getpid()
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            if proc.info['pid'] == current_pid:
                continue
            cmdline_list = proc.info.get('cmdline') or []
            if not isinstance(cmdline_list, (list, tuple)):
                continue
            cmdline = ' '.join(cmdline_list).lower()
            if script_name in cmdline and f"-a {account_name.lower()}" in cmdline:
                return False
        except Exception:
            continue
    return True

# ----------------- XtQuantTrader init / callback -----------------
class MyXtQuantTraderCallback(XtQuantTraderCallback):
    def on_disconnected(self, *args, **kwargs):
        logging.error(f"{datetime.now()} - 连接断开")

    def on_stock_order(self, order):
        logging.info(f"{datetime.now()} - 委托回调: {getattr(order, 'order_remark', order)}")

    def on_stock_trade(self, trade):
        logging.info(
            f"{datetime.now()} - 成交回调: {getattr(trade, 'order_remark', trade)}, 成交价格: {getattr(trade, 'traded_price', '')}, 成交数量: {getattr(trade, 'traded_volume', '')}"
        )

    def on_order_error(self, order_error):
        logging.error(f"{datetime.now()} - 委托报错: {getattr(order_error, 'order_remark', order_error)}, 错误信息: {getattr(order_error, 'error_msg', '')}")

    def on_cancel_error(self, cancel_error):
        logging.error(f"{datetime.now()} - 撤单失败回调")

    def on_order_stock_async_response(self, response):
        logging.info(f"{datetime.now()} - 异步委托回调: {getattr(response, 'order_remark', response)}")

    def on_cancel_order_stock_async_response(self, response):
        logging.info(f"{datetime.now()} - 撤单异步回调")

    def on_account_status(self, status):
        logging.info(f"{datetime.now()} - 账户状态回调")

def init_xt_trader(path_qmt, session_id):
    xt_trader = XtQuantTrader(path_qmt, session_id)
    callback = MyXtQuantTraderCallback()
    xt_trader.register_callback(callback)
    xt_trader.start()
    logging.info("XtQuantTrader 已初始化并启动")
    return xt_trader

# ----------------- cron helpers -----------------
def _parse_hms(time_str: str):
    try:
        h, m, s = map(int, time_str.split(":"))
    except Exception:
        raise ValueError(f"时间格式错误: {time_str}")
    return h, m, s

def create_scheduler():
    return BackgroundScheduler()

def add_cron_job(scheduler: BackgroundScheduler, func, time_str: str, args=None, job_id: str = None, replace_existing=True):
    h, m, s = _parse_hms(time_str)
    scheduler.add_job(func, trigger=CronTrigger(hour=h, minute=m, second=s), args=tuple(args or []), id=job_id, replace_existing=replace_existing)
    logging.info(f"已添加定时任务: {job_id} @ {time_str}")

def add_multiple_cron_jobs(scheduler: BackgroundScheduler, jobs: list):
    for j in jobs:
        try:
            add_cron_job(scheduler, j['func'], j['time'], args=j.get('args', []), job_id=j.get('id'))
        except Exception as e:
            logging.error(f"添加任务失败 {j.get('id')} @ {j.get('time')}: {e}")

# ----------------- trade plan / draft helpers -----------------
def load_trade_plan(file_path):
    abs_path = os.path.abspath(file_path)
    try:
        with open(abs_path, 'r', encoding='utf-8') as f:
            trade_plan = json.load(f)
        logging.info(f"交易计划已从文件 `{abs_path}` 加载")
        return trade_plan
    except Exception as e:
        logging.error(f"无法加载交易计划文件 `{abs_path}`: {e}")
        return None

def get_can_directly_buy(draft_file_path: str) -> bool:
    try:
        with open(draft_file_path, 'r', encoding='utf-8') as f:
            draft = json.load(f)
        val = draft.get("can_directly_buy", False)
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.strip().lower() in ("是", "yes", "true", "1", "y")
        return False
    except Exception as e:
        logging.error(f"读取 can_directly_buy 失败: {e}")
        return False

# ----------------- yunfei helpers -----------------
def load_yunfei_configs():
    try:
        with open(INPUT_JSON, 'r', encoding='utf-8') as f:
            strategy_cfgs = json.load(f)
        batch_groups = {}
        for cfg in strategy_cfgs:
            batch = cfg.get("交易批次", 1)
            batch_groups.setdefault(batch, []).append(cfg)
        return batch_groups
    except Exception as e:
        logging.error(f"无法加载云飞配置 allocation.json: {e}")
        return {}

def add_yunfei_jobs(scheduler: BackgroundScheduler, xt_trader, config, account_asset_info_snapshot, positions_snapshot, account, generate_trade_plan_func=None):
    """
    增加一个可选参数 generate_trade_plan_func（生成最终交易计划的函数），并将其传递给 fetch_and_check_batch_with_trade_plan。
    """
    batch_cfgs_map = load_yunfei_configs()
    if not batch_cfgs_map:
        logging.warning("云飞策略配置为空，跳过云飞跟投任务设置。")
        return

    for idx, tstr in enumerate(YUNFEI_SCHEDULE_TIMES, 1):
        batch_cfgs = batch_cfgs_map.get(idx, [])
        if not batch_cfgs:
            logging.info(f"批次{idx}无策略配置，跳过。")
            continue
        try:
            h, m, s = _parse_hms(tstr)
        except ValueError:
            logging.error(f"时间格式错误: {tstr}，跳过批次{idx}。")
            continue

        job_id = f"yunfei_batch_{idx}_at_{tstr.replace(':', '')}"
        scheduler.add_job(
            fetch_and_check_batch_with_trade_plan,
            trigger=CronTrigger(hour=h, minute=m, second=s),
            args=[
                idx,
                tstr,
                batch_cfgs,
                config,
                account_asset_info_snapshot,
                positions_snapshot,
                # 现在把 generate_trade_plan_func 传进去（可能为 None，但更安全由调用者提供）
                generate_trade_plan_func,
                xt_trader,
                account
            ],
            id=job_id,
            replace_existing=True
        )
        logging.info(f"已添加 云飞跟投任务: 批次{idx} @ {tstr}，策略：{[c.get('策略名称') for c in batch_cfgs]}")

# ----------------- misc helpers -----------------
def add_seconds_to_hms(h: int, m: int, s: int, delta: int = 20):
    total = (h * 3600 + m * 60 + s + delta) % (24 * 3600)
    nh = total // 3600
    nm = (total % 3600) // 60
    ns = total % 60
    return nh, nm, ns

def register_signal_handlers(scheduler, xt_trader):
    import signal
    def handle_exit(signum, frame):
        logging.info(f"收到终止信号({signum})，开始清理")
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            logging.exception("scheduler 关闭异常")
        try:
            xt_trader.stop()
        except Exception:
            logging.exception("xt_trader 停止异常")
        # 尽量清理子进程（参考原实现）
        try:
            parent = psutil.Process(os.getpid())
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except Exception:
                    pass
            gone, alive = psutil.wait_procs(children, timeout=5)
            for p in alive:
                try:
                    p.kill()
                except Exception:
                    pass
        except Exception:
            logging.exception("清理子进程失败")
        logging.info("主进程即将退出。")
        logging.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGINT, handle_exit)
    try:
        signal.signal(signal.SIGBREAK, handle_exit)
    except AttributeError:
        pass

# 代理原来 processor 中的打印函数（为保持 main.py 简洁）
def print_account_asset(xt_trader, account_id):
    return _print_account_asset(xt_trader, account_id)

def print_positions(xt_trader, account_id, reverse_mapping, account_asset_info=None):
    return _print_positions(xt_trader, account_id, reverse_mapping, account_asset_info)