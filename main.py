# main.py

try:
    import os
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    import logging
    import time
    import json
    import argparse
    import signal
    from datetime import datetime
    import traceback
    import psutil
    from collections import defaultdict
    from utils.log_utils import ensure_utf8_stdio, setup_logging
    # 导入新的配置加载工具
    from utils.config_loader import load_json_file
    # 【新增】导入新的股票代码加载工具
    from utils.stock_data_loader import load_stock_code_maps
except Exception as err:
    raise

from xtquant import xtdata
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount

from processor.trade_plan_execution import execute_trade_plan
from processor.position_connector import print_positions
from processor.asset_connector import print_account_asset
from processor.order_cancel_tool import cancel_orders
from utils.stock_code_mapper import generate_reverse_mapping
# 交易计划生成文件不需要再传 sell_stocks_info 和 buy_stocks_info
from processor.trade_plan_generation import print_trade_plan
from processor.orders_reorder_tool import reorder_orders
from preprocessing.qmt_connector import ensure_qmt_and_connect
from preprocessing.trade_time_checker import check_trade_times
from preprocessing.qmt_daily_restart_checker import check_and_restart
from utils.git_push_tool import push_project_to_github
# 【修改】导入 fetch_and_check_batch_with_trade_plan
from yunfei_ball.yunfei_connect_follow import fetch_and_check_batch_with_trade_plan, INPUT_JSON
# 【删除】以下导入不再需要
# from yunfei_ball.yunfei_connect_follow import run_scheduler_with_staggered_batches
# from apscheduler.schedulers.background import BackgroundScheduler
# from apscheduler.triggers.date import DateTrigger
# from yunfei_ball.yunfei_connect_follow import get_batch_schedules, run_batch

# ========== 配置 ==========
SCHEDULE_TIMES = [
    "23:53:00",
    "23:53:05",
    "14:31:20",
    "14:51:25",
]

AUTO_BUY_511880_TIME = (9, 33, 0)
AUTO_SELL_511880_TIME = (14, 56, 0)

ACCOUNT_CONFIG_MAP = {
    "shu": "core_parameters/account/8886006288.json",
    "1234": "core_parameters/account/1234567890.json",
    # 更多账户...
}

account_name = None


# ========== 日志回调 (保持不变) ==========
class MyXtQuantTraderCallback(XtQuantTraderCallback):
    def on_disconnected(self, *args, **kwargs):
        logging.error(f"{datetime.now()} - 连接断开")

    def on_stock_order(self, order):
        logging.info(f"{datetime.now()} - 委托回调: {order.order_remark}")

    def on_stock_trade(self, trade):
        logging.info(
            f"{datetime.now()} - 成交回调: {trade.order_remark}, 成交价格: {trade.traded_price}, 成交数量: {trade.traded_volume}")

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


# ========== 工具函数 (保持不变) ==========
def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--account', required=True, help='账户别名或ID')
    return parser.parse_args()


def handle_exit(signum, frame):
    global account_name
    logging.info(f"[main.py][账户:{account_name}] 收到终止信号({signum})，主进程pid={os.getpid()} 开始清理子进程")
    try:
        parent = psutil.Process(os.getpid())
        children = parent.children(recursive=True)
        for child in children:
            logging.info(f"[main.py][账户:{account_name}] 终止子进程 {child.pid} {child.name()}")
            child.terminate()
        gone, alive = psutil.wait_procs(children, timeout=5)
        for p in alive:
            logging.warning(f"[main.py][账户:{account_name}] 强制kill未退出的进程 {p.pid} {p.name()}")
            p.kill()
    except Exception as e:
        logging.error(f"[main.py][账户:{account_name}] 终止子进程异常: {e}")
    logging.info(f"[main.py][账户:{account_name}] 主进程即将退出。")
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
        logging.error(f"❌ 无法加载交易计划文件 `{abs_path}`: {e}")
        return None


def cancel_and_reorder_task(xt_trader, account_id, reverse_mapping, check_time):
    cancel_orders(xt_trader, account_id, reverse_mapping)
    time.sleep(6)
    reorder_orders(xt_trader, account_id, reverse_mapping)


def add_seconds_to_hms(h: int, m: int, s: int, delta: int = 20):
    total = (h * 3600 + m * 60 + s + delta) % (24 * 3600)
    nh = total // 3600
    nm = (total % 3600) // 60
    ns = total % 60
    return nh, nm, ns


def sell_execution_task(xt_trader, account_id, trade_plan_file):
    logging.info(f"--- 卖出任务 --- 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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
    logging.info(f"--- 买入任务 --- 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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


def print_positions_task(xt_trader, account_id, reverse_mapping, account_asset_info):
    logging.info(f"--- 定时打印持仓任务 --- 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    positions = print_positions(xt_trader, account_id, reverse_mapping, account_asset_info)
    logging.info(f"持仓信息: {positions}")


def buy_all_funds_to_511880(xt_trader, account_id):
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
        price = tick.get("lastPrice") or tick.get("askPrice", [None])[0]
        if not price or price <= 0:
            logging.error("无法获取511880.SH买入价格！")
            return
        board_lot = 100
        volume = int(available_cash // price // board_lot) * board_lot
        logging.info(
            f"买入银华日利时：可用资金={available_cash}，价格={price}，最小单位(board_lot)={board_lot}，实际买入量(volume)={volume}")
        if volume <= 0:
            logging.info("资金不足以买入最小单位，跳过。")
            return
        async_seq = xt_trader.order_stock_async(
            account, "511880.SH", _XTCONST_.STOCK_BUY, volume, _XTCONST_.FIX_PRICE, price, "auto_yinhuarili",
            "511880.SH"
        )
        logging.info(f"已委托买入银华日利 {volume} 股，单价 {price}，异步号 {async_seq}")
    except Exception as e:
        logging.error(f"买入511880异常: {e}")


def sell_all_511880(xt_trader, account_id):
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
        price = tick.get("lastPrice") or tick.get("bidPrice", [None])[0]
        board_lot = 100
        volume = (can_sell // board_lot) * board_lot
        if volume <= 0:
            logging.info("银华日利可卖数量不足最小单位，跳过。")
            return
        async_seq = xt_trader.order_stock_async(
            account, "511880.SH", _XTCONST_.STOCK_SELL, volume, _XTCONST_.FIX_PRICE, price, "auto_yinhuarili",
            "511880.SH"
        )
        logging.info(f"已委托卖出银华日利 {volume} 股，单价 {price}，异步号 {async_seq}")
    except Exception as e:
        logging.error(f"卖出511880异常: {e}")

# 【新增】加载云飞策略配置
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
        logging.error(f"❌ 无法加载云飞配置 allocation.json: {e}")
        return {}

# 【新增】添加云飞定时任务到调度器
def add_yunfei_jobs(scheduler, xt_trader, config, account_asset_info, positions):
    batch_cfgs_map = load_yunfei_configs()
    if not batch_cfgs_map:
        logging.warning("云飞策略配置为空，跳过云飞跟投任务设置。")
        return

    for idx, tstr in enumerate(SCHEDULE_TIMES, 1):
        batch_cfgs = batch_cfgs_map.get(idx, [])
        if not batch_cfgs:
            logging.info(f"批次{idx}无策略配置，跳过。")
            continue

        try:
            h, m, s = map(int, tstr.split(':'))
        except ValueError:
            logging.error(f"时间格式错误: {tstr}，跳过批次{idx}。")
            continue

        job_id = f"yunfei_batch_{idx}_at_{tstr.replace(':', '')}"

        scheduler.add_job(
            fetch_and_check_batch_with_trade_plan,
            trigger=CronTrigger(hour=h, minute=m, second=s),
            args=[
                idx,  # batch_no
                tstr,  # batch_time
                batch_cfgs,  # batch_cfgs
                config,  # config
                account_asset_info,  # account_asset_info
                positions,  # positions
                print_trade_plan # print_trade_plan 函数
            ],
            id=job_id,
            replace_existing=True
        )
        logging.info(f"✅ 云飞跟投任务定时：批次{idx} @ {tstr}，策略：{[c['策略名称'] for c in batch_cfgs]}")


# ========== 主入口 ==========
def main():
    global account_name

    ensure_utf8_stdio()

    # 1. 先解析参数
    try:
        args = parse_args()
        account_name = args.account
    except SystemExit as e:
        print(f"parse_args() SystemExit: {e}")
        raise
    except Exception as e:
        print(f"exception at account_name = args.account: {e}")
        import traceback
        print(traceback.format_exc())
        raise

    # 2. 日志初始化
    setup_logging(console=True, file=True, account_name=account_name)
    logging.info(f"===============程序开始执行================")
    logging.info(f"sys.argv = {sys.argv}")
    logging.info(f"账户参数解析成功: {account_name}")

    # 3. 获取 config_path
    config_path = ACCOUNT_CONFIG_MAP.get(account_name)
    if not config_path:
        logging.error("找不到账户")
        return

    # 4. 加载配置
    try:
        config = load_json_file(config_path)
        logging.info(f"账户配置加载成功: {config_path}")
    except Exception as e:
        logging.error(f"加载 config_path 出错：{e}")
        logging.error(traceback.format_exc())
        return

    # 打印账户信息
    logging.info(
        f"账户号: {config['account_id']} 卖出时间: {config['sell_time']} 买入时间: {config['buy_time']} 首次检查: {config['check_time_first']} 二次检查: {config['check_time_second']}")

    # 赋值
    path_qmt = config['path_qmt']
    session_id = config['session_id']
    account_id = config['account_id']
    sell_time = config['sell_time']
    buy_time = config['buy_time']
    check_time_first = config['check_time_first']
    check_time_second = config['check_time_second']

    # 检查交易时间是否合理（仅打印错误，不中断主流程）
    trade_times = [sell_time, check_time_first, buy_time, check_time_second]
    ok, checked_times, msg_list = check_trade_times(trade_times)
    for msg in msg_list:
        logging.error(msg)

    trade_plan_draft_file_path = 'tradeplan/trade_plan_draft.json'

    # 设定交易计划执行日期为当天
    trade_date = datetime.now().strftime('%Y-%m-%d')
    trade_plan_file = f'./tradeplan/final/trade_plan_{account_id}_{trade_date.replace("-", "")}.json'

    xt_trader = XtQuantTrader(path_qmt, session_id)
    callback = MyXtQuantTraderCallback()
    xt_trader.register_callback(callback)
    xt_trader.start()

    # 检查当天是否启动过miniQMT
    check_and_restart(config_path)
    ensure_qmt_and_connect(config_path, xt_trader, logger=logging)

    # 【修改点】使用新的加载工具获取 reverse_mapping
    logging.info("开始加载股票代码")
    try:
        # 只需获取 reverse_mapping，其他信息由 print_trade_plan 内部自己加载
        _, _, reverse_mapping = load_stock_code_maps()
        logging.info("股票代码加载成功，并生成 reverse_mapping")
    except Exception as e:
        logging.error(f"❌ 加载股票代码失败: {e}")
        xt_trader.stop()
        return

    account_asset_info = print_account_asset(xt_trader, account_id)
    positions = print_positions(xt_trader, account_id, reverse_mapping, account_asset_info)

    # 【修改点】调用 print_trade_plan 时，不再传入 stock_code_dict
    print_trade_plan(
        config=config,
        account_asset_info=account_asset_info,
        positions=positions,
        trade_date=trade_date,
        setting_file_path=trade_plan_draft_file_path,  # 传入文件路径
        trade_plan_file=trade_plan_file
    )

    # 【删除】不再需要调用 run_scheduler_with_staggered_batches
    # run_scheduler_with_staggered_batches(config, account_asset_info, positions, print_trade_plan)

    time.sleep(5)
    logging.info("布置定时任务")
    scheduler = BackgroundScheduler()
    sell_hour, sell_minute, sell_second = map(int, sell_time.split(":"))
    buy_hour, buy_minute, buy_second = map(int, buy_time.split(":"))
    check1_hour, check1_minute, check1_second = map(int, check_time_first.split(":"))
    check2_hour, check2_minute, check2_second = map(int, check_time_second.split(":"))

    # ... (原有定时任务配置保持不变)
    scheduler.add_job(
        sell_execution_task,
        trigger=CronTrigger(hour=sell_hour, minute=sell_minute, second=sell_second),
        args=[xt_trader, account_id, trade_plan_file],
        id="sell_execution_task",
        replace_existing=True
    )
    logging.info(f"卖出任务定时: {sell_time}")

    scheduler.add_job(
        buy_execution_task,
        trigger=CronTrigger(hour=buy_hour, minute=buy_minute, second=buy_second),
        args=[xt_trader, account_id, trade_plan_file],
        id="buy_execution_task",
        replace_existing=True
    )
    logging.info(f"买入任务定时: {buy_time}")

    scheduler.add_job(
        cancel_and_reorder_task,
        trigger=CronTrigger(hour=check1_hour, minute=check1_minute, second=check1_second),
        args=[xt_trader, account_id, reverse_mapping, check_time_first],
        id="cancel_and_reorder_task_first",
        replace_existing=True
    )
    logging.info(f"撤单和重下任务1定时: {check_time_first}")

    scheduler.add_job(
        cancel_and_reorder_task,
        trigger=CronTrigger(hour=check2_hour, minute=check2_minute, second=check2_second),
        args=[xt_trader, account_id, reverse_mapping, check_time_second],
        id="cancel_and_reorder_task_second",
        replace_existing=True
    )
    logging.info(f"撤单和重下任务2定时: {check_time_second}")

    scheduler.add_job(
        cancel_and_reorder_task,
        trigger=CronTrigger(hour=13, minute=0, second=3),
        args=[xt_trader, account_id, reverse_mapping, "13:00:03"],
        id="cancel_and_reorder_task_130003",
        replace_existing=True
    )
    logging.info("撤单和重下任务定时: 13:00:03")

    scheduler.add_job(
        print_positions_task,
        trigger=CronTrigger(hour=9, minute=35, second=0),
        args=[xt_trader, account_id, reverse_mapping, account_asset_info],
        id="print_positions_task_0935",
        replace_existing=True
    )
    logging.info("定时持仓打印任务定时1: 9:35:00")

    scheduler.add_job(
        print_positions_task,
        trigger=CronTrigger(hour=14, minute=57, second=0),
        args=[xt_trader, account_id, reverse_mapping, account_asset_info],
        id="print_positions_task_1457",
        replace_existing=True
    )
    logging.info("定时持仓打印任务定时2: 14:57:00")

    # 银华日利自动交易任务
    buy_h, buy_m, buy_s = AUTO_BUY_511880_TIME
    scheduler.add_job(
        buy_all_funds_to_511880,
        trigger=CronTrigger(hour=buy_h, minute=buy_m, second=buy_s),
        args=[xt_trader, account_id],
        id="auto_buy_511880",
        replace_existing=True
    )
    logging.info(f"自动买入银华日利任务定时: {buy_h:02d}:{buy_m:02d}:{buy_s:02d}")

    chk_buy_h, chk_buy_m, chk_buy_s = add_seconds_to_hms(buy_h, buy_m, buy_s, 20)
    scheduler.add_job(
        cancel_and_reorder_task,
        trigger=CronTrigger(hour=chk_buy_h, minute=chk_buy_m, second=chk_buy_s),
        args=[xt_trader, account_id, reverse_mapping, f"{chk_buy_h:02d}:{chk_buy_m:02d}:{chk_buy_s:02d}"],
        id="check_after_511880_buy",
        replace_existing=True
    )
    logging.info(f"银华日利买入后20秒检查任务定时: {chk_buy_h:02d}:{chk_buy_m:02d}:{chk_buy_s:02d}")

    sell_h, sell_m, sell_s = AUTO_SELL_511880_TIME
    scheduler.add_job(
        sell_all_511880,
        trigger=CronTrigger(hour=sell_h, minute=sell_m, second=sell_s),
        args=[xt_trader, account_id],
        id="auto_sell_511880",
        replace_existing=True
    )
    logging.info(f"自动卖出银华日利任务定时: {sell_h:02d}:{sell_m:02d}:{sell_s:02d}")

    chk_sell_h, chk_sell_m, chk_sell_s = add_seconds_to_hms(sell_h, sell_m, sell_s, 20)
    scheduler.add_job(
        cancel_and_reorder_task,
        trigger=CronTrigger(hour=chk_sell_h, minute=chk_sell_m, second=chk_sell_s),
        args=[xt_trader, account_id, reverse_mapping, f"{chk_sell_h:02d}:{chk_sell_m:02d}:{chk_sell_s:02d}"],
        id="check_after_511880_sell",
        replace_existing=True
    )
    logging.info(f"银华日利卖出后20秒检查任务定时: {chk_sell_h:02d}:{chk_sell_m:02d}:{chk_sell_s:02d}")

    # ========== 新增：miniQMT-frontend 自动 push GitHub 任务 ==========
    scheduler.add_job(
        push_project_to_github,
        trigger=CronTrigger(hour=9, minute=36, second=0),
        args=[r"C:\Users\ceicei\PycharmProjects\miniQMT-frontend"],
        id="push_miniQMT_frontend_to_github",
        replace_existing=True
    )
    logging.info("miniQMT-frontend 自动推送GitHub任务定时: 9:36:00")
    # ===============================================================

    # 【新增】添加云飞跟投定时任务
    add_yunfei_jobs(scheduler, xt_trader, config, account_asset_info, positions)

    scheduler.start()

    # 注册信号处理器
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
        scheduler.shutdown()
        xt_trader.stop()
        logging.info("交易线程已停止。")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        err_txt = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
        logging.error(err_txt)
        raise