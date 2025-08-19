
import time
import json
import logging
import os
from xtquant import xtdata
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount

from processor.trade_plan_execution import execute_trade_plan
from processor.position_connector import print_positions
from processor.asset_connector import print_account_asset
from processor.order_cancel_tool import cancel_orders
from utils.stock_code_mapper import load_stock_codes, generate_reverse_mapping
from processor.trade_plan_generation import print_trade_plan
from processor.orders_reorder_tool import reorder_orders
from preprocessing.qmt_connector import ensure_qmt_and_connect
from preprocessing.trade_time_checker import check_trade_times
from preprocessing.qmt_daily_restart_checker import check_and_restart
import argparse
import signal
import sys
import psutil

print("main.py really started", flush=True)


# 在任何日志初始化之前，确保标准输出/错误使用 UTF-8，避免编码问题
from utils.log_utils import ensure_utf8_stdio
ensure_utf8_stdio()

# 全局账户名变量，用于日志标识
account_name = None

# ========= 配置：银华日利（511880）自动交易时间 =========
# 只需修改这两个时间（时,分,秒），检查任务会自动在其后20秒触发
AUTO_BUY_511880_TIME = (9, 33, 0)    # 自动买入银华日利时间
AUTO_SELL_511880_TIME = (14, 56, 0)  # 自动卖出银华日利时间


class MyXtQuantTraderCallback(XtQuantTraderCallback):
    def on_disconnected(self):
        logging.error(f"{datetime.now()} - 连接断开")
    def on_stock_order(self, order):
        logging.info(f"{datetime.now()} - 委托回调: {order.order_remark}")
    def on_stock_trade(self, trade):
        logging.info(f"{datetime.now()} - 成交回调: {trade.order_remark}, 成交价格: {trade.traded_price}, 成交数量: {trade.traded_volume}")
    def on_order_error(self, order_error):
        logging.error(f"{datetime.now()} - 委托报错: {order_error.order_remark}, 错误信息: {order_error.error_msg}")
    def on_cancel_error(self, cancel_error):
        logging.error(f"{datetime.now()} - 撤单失败回调")
    def on_order_stock_async_response(self, response):
        logging.info(f"{datetime.now()} - 异步委托回调: {response.order_remark}")
    def on_cancel_order_stock_async_response(self, response):
        logging.info(f"{datetime.now()} - 撤单异步回调")
    def on_account_status(self, status):
        logging.info(f"{datetime.now()} - 账户状态回调")


def setup_logging():
    log_folder = "./zz_log"
    os.makedirs(log_folder, exist_ok=True)
    log_date = datetime.now().strftime('%Y%m%d')
    log_file = os.path.join(log_folder, f"log_{log_date}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, mode='a', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.info("日志记录启动")


def load_trade_plan(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            trade_plan = json.load(f)
        logging.info(f"交易计划已从文件 `{file_path}` 加载: {trade_plan}")
        return trade_plan
    except Exception as e:
        logging.error(f"❌ 无法加载交易计划文件 `{file_path}`: {e}")
        return None


def cancel_and_reorder_task(xt_trader, account_id, reverse_mapping, check_time):
    cancel_orders(xt_trader, account_id, reverse_mapping)
    time.sleep(6)
    reorder_orders(xt_trader, account_id, reverse_mapping)


# 通用：给定时分秒，返回 +delta 秒后的时分秒（处理进位/跨天）
def add_seconds_to_hms(h: int, m: int, s: int, delta: int = 20):
    total = (h * 3600 + m * 60 + s + delta) % (24 * 3600)
    nh = total // 3600
    nm = (total % 3600) // 60
    ns = total % 60
    return nh, nm, ns


def sell_execution_task(xt_trader, account_id, trade_plan_file):
    logging.info(f"\n--- 卖出任务 --- 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
    try:
        trade_plan = load_trade_plan(trade_plan_file)
        if not trade_plan:
            logging.error("❌ 交易计划加载失败，跳过本次执行。")
            return
        account = StockAccount(account_id)
        execute_trade_plan(xt_trader, account, trade_plan, action='sell')
        logging.info("✅ 卖出任务执行成功")
    except Exception as e:
        logging.error(f"❌ 卖出任务执行失败: {e}")


def buy_execution_task(xt_trader, account_id, trade_plan_file):
    logging.info(f"\n--- 买入任务 --- 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
    try:
        trade_plan = load_trade_plan(trade_plan_file)
        if not trade_plan:
            logging.error("❌ 交易计划加载失败，跳过本次执行。")
            return
        account = StockAccount(account_id)
        execute_trade_plan(xt_trader, account, trade_plan, action='buy')
        logging.info("✅ 买入任务执行成功")
    except Exception as e:
        logging.error(f"❌ 买入任务执行失败: {e}")


# 配置账户缩写
ACCOUNT_CONFIG_MAP = {
    "shu": "core_parameters/account/8886006288.json",
    "1234": "core_parameters/account/1234567890.json",
    # 更多账户
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--account', required=True, help='账户别名或ID')
    return parser.parse_args()


def handle_exit(signum, frame):
    global account_name
    logging.info(f"[main.py][账户:{account_name}] 收到终止信号({signum})，主进程pid={os.getpid()} 开始清理子进程")
    logging.info(f"[main.py][账户:{account_name}] 收到终止信号({signum})，主进程pid={os.getpid()} 开始清理子进程")
    try:
        parent = psutil.Process(os.getpid())
        children = parent.children(recursive=True)
        for child in children:
            logging.info(f"[main.py][账户:{account_name}] 终止子进程 {child.pid} {child.name()}")
            logging.info(f"[main.py][账户:{account_name}] 终止子进程 {child.pid} {child.name()}")
            child.terminate()
        gone, alive = psutil.wait_procs(children, timeout=5)
        for p in alive:
            logging.warning(f"[main.py][账户:{account_name}] 强制kill未退出的进程 {p.pid} {p.name()}")
            logging.info(f"[main.py][账户:{account_name}] 强制kill未退出的进程 {p.pid} {p.name()}")
            p.kill()
    except Exception as e:
        logging.error(f"[main.py][账户:{account_name}] 终止子进程异常: {e}")
        logging.info(f"[main.py][账户:{account_name}] 终止子进程异常: {e}")
    logging.info(f"[main.py][账户:{account_name}] 主进程即将退出。")
    logging.info(f"[main.py][账户:{account_name}] 主进程即将退出。")
    logging.shutdown()
    sys.exit(0)


def load_json_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


# 持仓打印任务函数
def print_positions_task(xt_trader, account_id, reverse_mapping, account_asset_info):
    logging.info(f"\n--- 定时打印持仓任务 --- 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
    positions = print_positions(xt_trader, account_id, reverse_mapping, account_asset_info)
    logging.info(f"持仓信息: {positions}")


def buy_all_funds_to_511880(xt_trader, account_id):
    logging.info(f"\n--- 自动买入银华日利 --- 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
    try:
        account = StockAccount(account_id)
        account_info = xt_trader.query_stock_asset(account)
        available_cash = float(getattr(account_info, "m_dCash", 0.0))
        if available_cash <= 100:  # 留一点小余量防止买入失败
            logging.info("可用资金太少，不进行买入。")
            return
        from xtquant.xttype import _XTCONST_
        # 查价格
        tick = xtdata.get_full_tick(["511880.SH"])["511880.SH"]
        price = tick.get("lastPrice") or tick.get("askPrice", [None])[0]
        if not price or price <= 0:
            logging.error("无法获取511880.SH买入价格！")
            return
        detail = xtdata.get_instrument_detail("511880.SH") or {}
        board_lot = 100  # 强制用100做单位
        volume = int(available_cash // price // board_lot) * board_lot
        logging.info(
            f"买入银华日利时：可用资金={available_cash}，价格={price}，最小单位(board_lot)={board_lot}，实际买入量(volume)={volume}")
        if volume <= 0:
            logging.info("资金不足以买入最小单位，跳过。")
            return
        async_seq = xt_trader.order_stock_async(
            account, "511880.SH", _XTCONST_.STOCK_BUY, volume, _XTCONST_.FIX_PRICE, price, "auto_yinhuarili", "511880.SH"
        )
        logging.info(f"已委托买入银华日利 {volume} 股，单价 {price}，异步号 {async_seq}")
    except Exception as e:
        logging.error(f"买入511880异常: {e}")


def sell_all_511880(xt_trader, account_id):
    logging.info(f"\n--- 自动卖出银华日利 --- 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
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
        price = tick.get("lastPrice") or tick.get("bidPrice", [None])[0]
        detail = xtdata.get_instrument_detail("511880.SH") or {}
        board_lot = int(detail.get("MinVolume", 10))
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


def main():
    # 日志启动
    setup_logging()
    print("=== print test ===", flush=True)
    logging.info("this is a logging.info test")
    logging.info("")
    logging.info("================================ 启动代码 ================================")
    args = parse_args()
    global account_name
    account_name = args.account
    config_path = ACCOUNT_CONFIG_MAP.get(account_name)
    if not config_path:
        logging.info(f"找不到账户 {account_name} 的配置文件")
        logging.error(f"[main.py][账户:{account_name}] 找不到账户配置文件")
        return
    config = load_json_file(config_path)
    # 打印账户信息
    logging.info("开始读取账户信息")
    logging.info(f"  账户号     : {config['account_id']}")
    logging.info(f"  卖出时间    : {config['sell_time']}")
    logging.info(f"  买入时间    : {config['buy_time']}")
    logging.info(f"  首次检查    : {config['check_time_first']}")
    logging.info(f"  二次检查    : {config['check_time_second']}")

    # 赋值
    path_qmt = config['path_qmt']
    session_id = config['session_id']
    account_id = config['account_id']
    sell_time = config['sell_time']
    buy_time = config['buy_time']
    check_time_first = config['check_time_first']
    check_time_second = config['check_time_second']

    # 检查交易时间是否合理
    logging.info("开始进行交易时间检查")
    trade_times = [sell_time, check_time_first, buy_time, check_time_second]
    ok, trade_times = check_trade_times(trade_times)
    if not ok:
        return
    # 若时间被重设，更新变量
    sell_time, check_time_first, buy_time, check_time_second = trade_times

    # 读取初始交易倾向
    setting_data = load_json_file('core_parameters/setting/setting.json')
    sell_stocks_info = setting_data["sell_stocks_info"]
    buy_stocks_info = setting_data["buy_stocks_info"]

    # 设定交易计划执行日期为当天
    trade_date = datetime.now().strftime('%Y-%m-%d')

    # 设定交易计划文件保存地址
    trade_plan_file = f'./tradplan/trade_plan_{account_id}_{trade_date.replace("-", "")}.json'

    xt_trader = XtQuantTrader(path_qmt, session_id)
    callback = MyXtQuantTraderCallback()
    xt_trader.register_callback(callback)
    xt_trader.start()

    # 检查当天是否启动过miniQMT
    check_and_restart(config_path)
    # 自动重连并自动重启main.py
    ensure_qmt_and_connect(config_path, xt_trader, logger=logging)

    logging.info(f"开始加载股票代码")
    stock_code_file_path = r"core_parameters/stocks/core_stock_code.json"
    full_code_file_path = r"utils/stocks_code_search_tool/stocks_data/name_vs_code.json"
    try:
        # 加载常用组（名称->代码）
        stock_code_dict = load_json_file(stock_code_file_path)
        # 加载全量组（代码->名称），并生成反向映射（名称->代码）
        code2name = load_json_file(full_code_file_path)
        # 生成全量名称->代码字典
        full_name2code = {v: k for k, v in code2name.items()}
        # 合成一个查询函数
        def get_stock_code(name):
            return stock_code_dict.get(name) or full_name2code.get(name)
        # 反向映射用于持仓打印等
        reverse_mapping = generate_reverse_mapping(stock_code_dict)
        logging.info("股票代码加载完成！")
    except Exception as e:
        logging.error(f"❌ 加载股票代码失败: {e}")
        xt_trader.stop()
        return

    # 打印账户情况
    account_asset_info = print_account_asset(xt_trader, account_id)
    if account_asset_info:
        total_asset, cash, frozen_cash, market_value, percent_cash, percent_frozen, percent_market = account_asset_info
    # 打印持仓情况
    positions = print_positions(xt_trader, account_id, reverse_mapping, account_asset_info)
    # 打印交易计划
    print_trade_plan(
        config=config,
        account_asset_info=account_asset_info,
        positions=positions,
        stock_code_dict=stock_code_dict,
        trade_date=trade_date,
        sell_stocks_info=sell_stocks_info,
        buy_stocks_info=buy_stocks_info,
        trade_plan_file=trade_plan_file
    )
    time.sleep(5)

    logging.info("")
    logging.info("================================布置定时任务================================")
    scheduler = BackgroundScheduler()
    # 卖出任务时间
    sell_hour, sell_minute, sell_second = map(int, sell_time.split(":"))
    # 买入任务时间
    buy_hour, buy_minute, buy_second = map(int, buy_time.split(":"))
    # 撤单重下任务时间（第一次）
    check1_hour, check1_minute, check1_second = map(int, check_time_first.split(":"))
    # 撤单重下任务时间（第二次）
    check2_hour, check2_minute, check2_second = map(int, check_time_second.split(":"))

    # 卖出任务定时（计划）
    scheduler.add_job(
        sell_execution_task,
        trigger=CronTrigger(hour=sell_hour, minute=sell_minute, second=sell_second),
        args=[xt_trader, account_id, trade_plan_file],
        id="sell_execution_task",
        replace_existing=True
    )
    logging.info(f"卖出任务已定时在 {sell_time} 执行！")

    # 买入任务定时（计划）
    scheduler.add_job(
        buy_execution_task,
        trigger=CronTrigger(hour=buy_hour, minute=buy_minute, second=buy_second),
        args=[xt_trader, account_id, trade_plan_file],
        id="buy_execution_task",
        replace_existing=True
    )
    logging.info(f"买入任务已定时在 {buy_time} 执行！")

    # 撤单重下任务（第一次，计划）
    scheduler.add_job(
        cancel_and_reorder_task,
        trigger=CronTrigger(hour=check1_hour, minute=check1_minute, second=check1_second),
        args=[xt_trader, account_id, reverse_mapping, check_time_first],
        id="cancel_and_reorder_task_first",
        replace_existing=True
    )
    logging.info(f"撤单和重下任务（第一次）已定时在 {check_time_first} 执行！")

    # 撤单重下任务（第二次，计划）
    scheduler.add_job(
        cancel_and_reorder_task,
        trigger=CronTrigger(hour=check2_hour, minute=check2_minute, second=check2_second),
        args=[xt_trader, account_id, reverse_mapping, check_time_second],
        id="cancel_and_reorder_task_second",
        replace_existing=True
    )
    logging.info(f"撤单和重下任务（第二次）已定时在 {check_time_second} 执行！")

    # 定时打印持仓任务时间（14:59:00）
    scheduler.add_job(
        print_positions_task,
        trigger=CronTrigger(hour=14, minute=59, second=0),
        args=[xt_trader, account_id, reverse_mapping, account_asset_info],
        id="print_positions_task",
        replace_existing=True
    )
    logging.info("定时持仓打印任务已定时在 14:59:00 执行！")
    # ========= 银华日利自动交易 + “交易后20秒检查”（自动推算） =========

    # 自动买入银华日利
    buy_h, buy_m, buy_s = AUTO_BUY_511880_TIME
    scheduler.add_job(
        buy_all_funds_to_511880,
        trigger=CronTrigger(hour=buy_h, minute=buy_m, second=buy_s),
        args=[xt_trader, account_id],
        id="auto_buy_511880",
        replace_existing=True
    )
    logging.info(f"自动买入银华日利任务已定时在 {buy_h:02d}:{buy_m:02d}:{buy_s:02d} 执行！")

    # 自动买入后的 +20 秒检查（自动推算）
    chk_buy_h, chk_buy_m, chk_buy_s = add_seconds_to_hms(buy_h, buy_m, buy_s, 20)
    scheduler.add_job(
        cancel_and_reorder_task,
        trigger=CronTrigger(hour=chk_buy_h, minute=chk_buy_m, second=chk_buy_s),
        args=[xt_trader, account_id, reverse_mapping, f"{chk_buy_h:02d}:{chk_buy_m:02d}:{chk_buy_s:02d}"],
        id="check_after_511880_buy",
        replace_existing=True
    )
    logging.info(f"银华日利买入后20秒检查任务已定时在 {chk_buy_h:02d}:{chk_buy_m:02d}:{chk_buy_s:02d} 执行！")

    # 自动卖出银华日利
    sell_h, sell_m, sell_s = AUTO_SELL_511880_TIME
    scheduler.add_job(
        sell_all_511880,
        trigger=CronTrigger(hour=sell_h, minute=sell_m, second=sell_s),
        args=[xt_trader, account_id],
        id="auto_sell_511880",
        replace_existing=True
    )
    logging.info(f"自动卖出银华日利任务已定时在 {sell_h:02d}:{sell_m:02d}:{sell_s:02d} 执行！")

    # 自动卖出后的 +20 秒检查（自动推算）
    chk_sell_h, chk_sell_m, chk_sell_s = add_seconds_to_hms(sell_h, sell_m, sell_s, 20)
    scheduler.add_job(
        cancel_and_reorder_task,
        trigger=CronTrigger(hour=chk_sell_h, minute=chk_sell_m, second=chk_sell_s),
        args=[xt_trader, account_id, reverse_mapping, f"{chk_sell_h:02d}:{chk_sell_m:02d}:{chk_sell_s:02d}"],
        id="check_after_511880_sell",
        replace_existing=True
    )
    logging.info(f"银华日利卖出后20秒检查任务已定时在 {chk_sell_h:02d}:{chk_sell_m:02d}:{chk_sell_s:02d} 执行！")

    scheduler.start()

    # 注册信号处理器，保证kill时能优雅退出
    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGINT, handle_exit)
    try:
        signal.signal(signal.SIGBREAK, handle_exit)
    except AttributeError:
        pass

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        logging.info("程序被手动终止。")
    finally:
        scheduler.shutdown()
        xt_trader.stop()
        logging.info("交易线程已停止。")


if __name__ == "__main__":
    main()