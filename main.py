#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重构后的 main.py（修复了 args 使用的语法错误）
- 清理重复 imports
- 把调度注册数据化、封装为 helper
- 优化 can_directly_buy 为布尔返回值
- 对需要最新数据的任务在任务内部重新查询（避免使用过时 snapshot）
- 兼顾原有功能与可维护性
"""

import os
import sys
import signal
import json
import time
import logging
import traceback
from collections import defaultdict
from datetime import datetime

import psutil
import argparse

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# 项目内模块
from utils.log_utils import ensure_utf8_stdio, setup_logging
from utils.config_loader import load_json_file
from utils.stock_data_loader import load_stock_code_maps
from utils.asset_helpers import positions_to_dict
from preprocessing.qmt_connector import ensure_qmt_and_connect
from preprocessing.trade_time_checker import check_trade_times
from preprocessing.qmt_daily_restart_checker import check_and_restart
from processor.trade_plan_execution import execute_trade_plan
from processor.position_connector import print_positions
from processor.asset_connector import print_account_asset
from processor.order_cancel_tool import cancel_orders
from processor.orders_reorder_tool import reorder_orders
from processor.trade_plan_generation import print_trade_plan as generate_trade_plan_final_func
from utils.git_push_tool import push_project_to_github
from utils.stock_code_mapper import generate_reverse_mapping
from xtquant import xtdata
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount
from yunfei_ball.yunfei_connect_follow import fetch_and_check_batch_with_trade_plan, INPUT_JSON

# ========== 配置 ==========
YUNFEI_SCHEDULE_TIMES = [
    "14:52:00",
    "13:00:05",
    "14:31:20",
    "14:51:25",
]

AUTO_BUY_511880_TIME = (9, 33, 0)
AUTO_SELL_511880_TIME = (14, 56, 0)

ACCOUNT_CONFIG_MAP = {
    "shu": "core_parameters/account/8886006288.json",
    "mama": "core_parameters/account/mama.json",
    # 更多账户...
}

# ========== 回调 ==========
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


# ========== 控制台流过滤器 ==========
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


# ========== 其他 helper ==========
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


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--account', required=True, help='账户别名或ID')
    return parser.parse_args()


def handle_exit(signum, frame):
    logging.info(f"收到终止信号({signum})，主进程pid={os.getpid()} 开始清理子进程")
    try:
        parent = psutil.Process(os.getpid())
        children = parent.children(recursive=True)
        for child in children:
            logging.info(f"终止子进程 {child.pid} {child.name()}")
            try:
                child.terminate()
            except Exception:
                pass
        gone, alive = psutil.wait_procs(children, timeout=5)
        for p in alive:
            logging.warning(f"强制kill未退出的进程 {p.pid} {p.name()}")
            try:
                p.kill()
            except Exception:
                pass
    except Exception as e:
        logging.error(f"终止子进程异常: {e}")
    logging.info("主进程即将退出。")
    logging.shutdown()
    sys.exit(0)


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


def add_seconds_to_hms(h: int, m: int, s: int, delta: int = 20):
    total = (h * 3600 + m * 60 + s + delta) % (24 * 3600)
    nh = total // 3600
    nm = (total % 3600) // 60
    ns = total % 60
    return nh, nm, ns


def get_can_directly_buy(draft_file_path: str) -> bool:
    try:
        with open(draft_file_path, 'r', encoding='utf-8') as f:
            draft = json.load(f)
        val = draft.get("can_directly_buy", False)
        # 支持布尔或中文 "是"/"否" 或字符串
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.strip().lower() in ("是", "yes", "true", "1", "y")
        return False
    except Exception as e:
        logging.error(f"读取 can_directly_buy 失败: {e}")
        return False


# ========== 调度 helper ==========
def _parse_hms(time_str: str):
    try:
        h, m, s = map(int, time_str.split(":"))
    except Exception:
        raise ValueError(f"时间格式错误: {time_str}")
    return h, m, s


def add_cron_job(scheduler: BackgroundScheduler, func, time_str: str, args=None, job_id: str = None, replace_existing=True):
    h, m, s = _parse_hms(time_str)
    # 修复：不要使用 starred expression，传入 tuple 或 list 即可
    scheduler.add_job(func, trigger=CronTrigger(hour=h, minute=m, second=s), args=tuple(args or []), id=job_id, replace_existing=replace_existing)
    logging.info(f"已添加定时任务: {job_id} @ {time_str}")


def add_multiple_cron_jobs(scheduler: BackgroundScheduler, jobs: list):
    for j in jobs:
        try:
            add_cron_job(scheduler, j['func'], j['time'], args=j.get('args', []), job_id=j.get('id'))
        except Exception as e:
            logging.error(f"添加任务失败 {j.get('id')} @ {j.get('time')}: {e}")


# ========== 主要任务函数（内部尽量自主获取最新数据） ==========
def cancel_and_reorder_task_factory(xt_trader, account_id, reverse_mapping):
    def task(check_time_label: str = ""):
        try:
            logging.info(f"--- 撤单和重下任务 ({check_time_label}) --- 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            cancel_orders(xt_trader, account_id, reverse_mapping)
            time.sleep(6)
            reorder_orders(xt_trader, account_id, reverse_mapping)
            logging.info("✅ 撤单与重下完成")
        except Exception as e:
            logging.error(f"撤单与重下发生错误: {e}")
    return task


def print_positions_task_factory(xt_trader, account_id, reverse_mapping):
    def task():
        try:
            logging.info(f"--- 定时打印持仓任务 --- 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            account_asset_info = print_account_asset(xt_trader, account_id)
            positions = print_positions(xt_trader, account_id, reverse_mapping, account_asset_info)
            logging.info(f"持仓信息: {positions}")
        except Exception as e:
            logging.error(f"打印持仓失败: {e}")
    return task


def buy_all_funds_to_511880_factory(xt_trader, account_id):
    def task():
        logging.info(f"--- 自动买入银华日利 --- 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            account = StockAccount(account_id)
            account_info = xt_trader.query_stock_asset(account)
            available_cash = float(getattr(account_info, "m_dCash", 0.0))
            if available_cash <= 100:
                logging.info("可用资金太少，不进行买入。")
                return
            from xtquant.xttype import _XTCONST_
            tick = xtdata.get_full_tick(["511880.SH"])["511880.SH"]
            price = tick.get("lastPrice") or (tick.get("askPrice") or [None])[0]
            if not price or price <= 0:
                logging.error("无法获取511880.SH买入价格！")
                return
            board_lot = 100
            volume = int(available_cash // price // board_lot) * board_lot
            logging.info(f"买入银华日利时：可用资金={available_cash}，价格={price}，最小单位={board_lot}，实际买入量={volume}")
            if volume <= 0:
                logging.info("资金不足以买入最小单位，跳过。")
                return
            async_seq = xt_trader.order_stock_async(
                account, "511880.SH", _XTCONST_.STOCK_BUY, volume, _XTCONST_.FIX_PRICE, price, "auto_yinhuarili", "511880.SH"
            )
            logging.info(f"已委托买入银华日利 {volume} 股，单价 {price}，异步号 {async_seq}")
        except Exception as e:
            logging.error(f"买入511880异常: {e}")
    return task


def sell_all_511880_factory(xt_trader, account_id):
    def task():
        logging.info(f"--- 自动卖出银华日利 --- 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            account = StockAccount(account_id)
            positions = xt_trader.query_stock_positions(account)
            pos = None
            for p in positions:
                if getattr(p, "stock_code", "") == "511880.SH":
                    pos = p
                    break
            if not pos or int(getattr(pos, "m_nCanUseVolume", 0)) <= 0:
                logging.info("未持有银华日利或无可卖数量，跳过。")
                return
            can_sell = int(getattr(pos, "m_nCanUseVolume", 0))
            from xtquant.xttype import _XTCONST_
            tick = xtdata.get_full_tick(["511880.SH"])["511880.SH"]
            price = tick.get("lastPrice") or (tick.get("bidPrice") or [None])[0]
            board_lot = 100
            volume = (can_sell // board_lot) * board_lot
            if volume <= 0:
                logging.info("银华日利可卖数量不足最小单位，跳过。")
                return
            async_seq = xt_trader.order_stock_async(
                account, "511880.SH", _XTCONST_.STOCK_SELL, volume, _XTCONST_.FIX_PRICE, price, "auto_yinhuarili", "511880.SH"
            )
            logging.info(f"已委托卖出银华日利 {volume} 股，单价 {price}，异步号 {async_seq}")
        except Exception as e:
            logging.error(f"卖出511880异常: {e}")
    return task


def sell_execution_task_factory(xt_trader, account_id, trade_plan_file, draft_file_path):
    def task():
        logging.info(f"--- 卖出任务 --- 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            can_directly_buy = get_can_directly_buy(draft_file_path)
            trade_plan = load_trade_plan(trade_plan_file)
            if not trade_plan:
                logging.error("交易计划加载失败，跳过本次执行。")
                return
            account = StockAccount(account_id)
            execute_trade_plan(xt_trader, account, trade_plan, action='sell')
            logging.info("✅ 卖出任务执行成功")
            if can_directly_buy:
                logging.info("can_directly_buy=True，卖出时同时买入")
                execute_trade_plan(xt_trader, account, trade_plan, action='buy')
                logging.info("✅ 卖出时已同步买入")
        except Exception as e:
            logging.error(f"卖出任务执行失败: {e}")
    return task


def buy_execution_task_factory(xt_trader, account_id, trade_plan_file, draft_file_path):
    def task():
        logging.info(f"--- 买入任务 --- 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            can_directly_buy = get_can_directly_buy(draft_file_path)
            if can_directly_buy:
                logging.info("can_directly_buy=True，买入任务跳过")
                return
            trade_plan = load_trade_plan(trade_plan_file)
            if not trade_plan:
                logging.error("交易计划加载失败，跳过本次执行。")
                return
            account = StockAccount(account_id)
            execute_trade_plan(xt_trader, account, trade_plan, action='buy')
            logging.info("✅ 买入任务执行成功")
        except Exception as e:
            logging.error(f"买入任务执行失败: {e}")
    return task


# ========== 云飞相关 ==========
def load_yunfei_configs():
    try:
        with open(INPUT_JSON, 'r', encoding='utf-8') as f:
            strategy_cfgs = json.load(f)
        batch_groups = defaultdict(list)
        for cfg in strategy_cfgs:
            batch = cfg.get("交易批次", 1)
            batch_groups[batch].append(cfg)
        return {b: clist for b, clist in batch_groups.items()}
    except Exception as e:
        logging.error(f"无法加载云飞配置 allocation.json: {e}")
        return {}


def add_yunfei_jobs(scheduler: BackgroundScheduler, xt_trader, config, account_asset_info_snapshot, positions_snapshot, account):
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
        # 直接传入需要的引用（在同一进程内运行），把 generate_trade_plan_final_func 传入做为回调
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
                generate_trade_plan_final_func,
                xt_trader,
                account
            ],
            id=job_id,
            replace_existing=True
        )
        logging.info(f"已添加 云飞跟投任务: 批次{idx} @ {tstr}，策略：{[c.get('策略名称') for c in batch_cfgs]}")


# ========== 主入口 ==========
def main():
    ensure_utf8_stdio()
    install_console_stream_filters()

    try:
        args = parse_args()
        account_name = args.account
    except SystemExit:
        raise
    except Exception as e:
        print("解析参数失败:", e)
        raise

    if not check_duplicate_instance('main.py', account_name):
        print(f"账户[{account_name}]已有实例运行，退出")
        sys.exit(0)

    setup_logging(console=True, file=True, account_name=account_name)

    # 全局日志过滤（屏蔽底层 BSON 报错噪声）
    try:
        suppress_env = os.environ.get("SUPPRESS_BSON_ERRORS", "1").lower()
        suppress_enabled = suppress_env not in ("0", "false", "no")
        if suppress_enabled:
            class SubstringFilter(logging.Filter):
                def __init__(self, banned_substrings):
                    super().__init__()
                    self.banned = banned_substrings

                def filter(self, record):
                    try:
                        msg = record.getMessage()
                    except Exception:
                        return True
                    if not msg:
                        return True
                    lower_msg = msg.lower()
                    for b in self.banned:
                        if b in lower_msg:
                            return False
                    return True

            banned_list = [
                "get bson value error",
                "bad lexical cast"
            ]
            f = SubstringFilter([s.lower() for s in banned_list])
            root_logger = logging.getLogger()
            root_logger.addFilter(f)
            for h in root_logger.handlers:
                h.addFilter(f)
            logging.info("已启用 BSON 错误消息过滤器 (SUPPRESS_BSON_ERRORS=1)。")
        else:
            logging.info("未启用 BSON 错误消息过滤器 (SUPPRESS_BSON_ERRORS=0)。")
    except Exception as e:
        logging.error(f"设置日志过滤器时出错: {e}")

    logging.info("===============程序开始执行================")
    logging.info(f"sys.argv = {sys.argv}")
    logging.info(f"账户参数解析成功: {account_name}")

    config_path = ACCOUNT_CONFIG_MAP.get(account_name)
    if not config_path:
        logging.error("找不到账户配置，退出")
        return

    try:
        config = load_json_file(config_path)
        logging.info(f"账户配置加载成功: {config_path}")
    except Exception as e:
        logging.error(f"加载 config_path 出错：{e}")
        logging.error(traceback.format_exc())
        return

    logging.info(
        f"账户号: {config.get('account_id')} 卖出时间: {config.get('sell_time')} 买入时间: {config.get('buy_time')} 首次检查: {config.get('check_time_first')} 二次检查: {config.get('check_time_second')}"
    )

    path_qmt = config['path_qmt']
    session_id = config['session_id']
    account_id = config['account_id']
    sell_time = config['sell_time']
    buy_time = config['buy_time']
    check_time_first = config['check_time_first']
    check_time_second = config['check_time_second']

    # 检查交易时间合理性（仅打印）
    trade_times = [sell_time, check_time_first, buy_time, check_time_second]
    ok, checked_times, msg_list = check_trade_times(trade_times)
    for msg in msg_list:
        logging.error(msg)

    trade_plan_draft_file_path = 'tradeplan/trade_plan_draft.json'
    trade_date = datetime.now().strftime('%Y-%m-%d')
    trade_plan_file = f'./tradeplan/final/trade_plan_final_{account_id}_{trade_date.replace("-", "")}.json'

    # 初始化 xt_trader
    xt_trader = XtQuantTrader(path_qmt, session_id)
    callback = MyXtQuantTraderCallback()
    xt_trader.register_callback(callback)
    xt_trader.start()
    account = StockAccount(account_id)

    # 检查 miniQMT 并保证连接
    check_and_restart(config_path)
    ensure_qmt_and_connect(config_path, xt_trader, logger=logging)

    # 加载股票代码并生成 reverse mapping
    try:
        _, _, reverse_mapping = load_stock_code_maps()
        logging.info("股票代码加载成功，并生成 reverse_mapping")
    except Exception as e:
        logging.error(f"加载股票代码失败: {e}")
        xt_trader.stop()
        return

    # 初始资产/持仓快照（用于生成交易计划）
    account_asset_info = print_account_asset(xt_trader, account_id)
    positions = print_positions(xt_trader, account_id, reverse_mapping, account_asset_info)
    positions_dict = positions_to_dict(positions)

    # 生成最终交易计划（覆盖或创建文件）
    generate_trade_plan_final_func(
        config=config,
        account_asset_info=account_asset_info,
        positions=positions_dict,
        trade_date=trade_date,
        setting_file_path=trade_plan_draft_file_path,
        trade_plan_file=trade_plan_file
    )

    time.sleep(2)
    logging.info("布置定时任务")
    scheduler = BackgroundScheduler()

    # 统一使用 factory 生成任务，避免重复创建逻辑
    # 1) 卖出任务
    sell_task = sell_execution_task_factory(xt_trader, account_id, trade_plan_file, trade_plan_draft_file_path)
    add_cron_job(scheduler, sell_task, sell_time, job_id="sell_execution_task")

    # 2) 买入任务
    buy_task = buy_execution_task_factory(xt_trader, account_id, trade_plan_file, trade_plan_draft_file_path)
    add_cron_job(scheduler, buy_task, buy_time, job_id="buy_execution_task")

    # 3) 撤单与重下任务集合（数据驱动）
    cancel_times = [check_time_first, check_time_second, "13:00:03"]
    # 追加自动 511880 买入/卖出后的检查会在后面添加
    cancel_jobs = []
    for idx, t in enumerate(cancel_times, 1):
        cancel_jobs.append({
            "func": cancel_and_reorder_task_factory(xt_trader, account_id, reverse_mapping),
            "time": t,
            "id": f"cancel_and_reorder_task_{idx}"
        })
    add_multiple_cron_jobs(scheduler, cancel_jobs)

    # 4) 定时打印持仓
    print_jobs = [
        {"func": print_positions_task_factory(xt_trader, account_id, reverse_mapping), "time": "09:35:00", "id": "print_positions_task_0935"},
        {"func": print_positions_task_factory(xt_trader, account_id, reverse_mapping), "time": "14:57:00", "id": "print_positions_task_1457"}
    ]
    add_multiple_cron_jobs(scheduler, print_jobs)

    # 5) 银华日利自动交易及后续检查
    buy_h, buy_m, buy_s = AUTO_BUY_511880_TIME
    buy_511880_job = buy_all_funds_to_511880_factory(xt_trader, account_id)
    add_cron_job(scheduler, buy_511880_job, f"{buy_h:02d}:{buy_m:02d}:{buy_s:02d}", job_id="auto_buy_511880")

    chk_buy_h, chk_buy_m, chk_buy_s = add_seconds_to_hms(buy_h, buy_m, buy_s, 20)
    add_cron_job(
        scheduler,
        cancel_and_reorder_task_factory(xt_trader, account_id, reverse_mapping),
        f"{chk_buy_h:02d}:{chk_buy_m:02d}:{chk_buy_s:02d}",
        job_id="check_after_511880_buy"
    )

    sell_h, sell_m, sell_s = AUTO_SELL_511880_TIME
    sell_511880_job = sell_all_511880_factory(xt_trader, account_id)
    add_cron_job(scheduler, sell_511880_job, f"{sell_h:02d}:{sell_m:02d}:{sell_s:02d}", job_id="auto_sell_511880")

    chk_sell_h, chk_sell_m, chk_sell_s = add_seconds_to_hms(sell_h, sell_m, sell_s, 20)
    add_cron_job(
        scheduler,
        cancel_and_reorder_task_factory(xt_trader, account_id, reverse_mapping),
        f"{chk_sell_h:02d}:{chk_sell_m:02d}:{chk_sell_s:02d}",
        job_id="check_after_511880_sell"
    )

    # 6) miniQMT-frontend 自动推送 GitHub
    # 使用 lambda 延迟执行 push_project_to_github；这里传入 lambda 作为待调度的 callable
    add_cron_job(
        scheduler,
        lambda path=r"C:\Users\ceicei\PycharmProjects\miniQMT-frontend": push_project_to_github(path),
        "09:36:00",
        job_id="push_miniQMT_frontend_to_github"
    )

    # 7) 云飞跟投任务（使用当前快照）
    add_yunfei_jobs(scheduler, xt_trader, config, account_asset_info, positions_dict, account)

    scheduler.start()

    # 信号注册
    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGINT, handle_exit)
    try:
        signal.signal(signal.SIGBREAK, handle_exit)
    except AttributeError:
        pass

    try:
        while True:
            time.sleep(5)
    except (KeyboardInterrupt, SystemExit):
        logging.info("程序被手动终止。")
    finally:
        try:
            scheduler.shutdown()
        except Exception:
            pass
        try:
            xt_trader.stop()
        except Exception:
            pass
        logging.info("交易线程已停止。")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        err_txt = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
        logging.error(err_txt)
        raise