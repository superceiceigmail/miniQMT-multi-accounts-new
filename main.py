import time
import json
import logging
import os
from xtquant import xtdata
from datetime import datetime
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

# 全局账户名变量，用于日志标识
account_name = None

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
            logging.StreamHandler()
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

def main():
    # 日志启动
    setup_logging()
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
    sell_time, check_time_first, buy_time,check_time_second = trade_times

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

    #检查当天是否启动过miniQMT
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

    # 卖出任务定时
    scheduler.add_job(
        sell_execution_task,
        trigger=CronTrigger(hour=sell_hour, minute=sell_minute, second=sell_second),
        args=[xt_trader, account_id, trade_plan_file],
        id="sell_execution_task",
        replace_existing=True
    )
    logging.info(f"卖出任务已定时在 {sell_time} 执行！")

    # 买入任务定时
    scheduler.add_job(
        buy_execution_task,
        trigger=CronTrigger(hour=buy_hour, minute=buy_minute, second=buy_second),
        args=[xt_trader, account_id, trade_plan_file],
        id="buy_execution_task",
        replace_existing=True
    )
    logging.info(f"买入任务已定时在 {buy_time} 执行！")

    # 撤单重下任务（第一次）
    scheduler.add_job(
        cancel_and_reorder_task,
        trigger=CronTrigger(hour=check1_hour, minute=check1_minute, second=check1_second),
        args=[xt_trader, account_id, reverse_mapping, check_time_first],
        id="cancel_and_reorder_task_first",
        replace_existing=True
    )
    logging.info(f"撤单和重下任务（第一次）已定时在 {check_time_first} 执行！")

    # 撤单重下任务（第二次）
    scheduler.add_job(
        cancel_and_reorder_task,
        trigger=CronTrigger(hour=check2_hour, minute=check2_minute, second=check2_second),
        args=[xt_trader, account_id, reverse_mapping, check_time_second],
        id="cancel_and_reorder_task_second",
        replace_existing=True
    )
    logging.info(f"撤单和重下任务（第二次）已定时在 {check_time_second} 执行！")

    # 定时打印持仓任务时间（14:55:00）
    scheduler.add_job(
        print_positions_task,
        trigger=CronTrigger(hour=14, minute=55, second=0),
        args=[xt_trader, account_id, reverse_mapping, account_asset_info],
        id="print_positions_task",
        replace_existing=True
    )
    logging.info("定时持仓打印任务已定时在 14:55:00 执行！")

    stock_list = ['600001.SH', '511090.SH']
    period = '1d'
    start_time = '2024-01-01'
    end_time = ''

    # 补充下载行情数据
    for code in stock_list:
        logging.info(f"开始下载 {code} 的历史行情数据...")
        xtdata.download_history_data(
            code,
            period=period,
            start_time=start_time,
            end_time=end_time,
            incrementally=True
        )
        logging.info(f"{code} 下载完成。")

    # 或用批量接口
    def on_progress(data):
        logging.info(f"下载进度: {data}")

    time.sleep(2)  # 等待落地

    data = xtdata.get_local_data(
        field_list=[],  # 全部字段
        stock_list=stock_list,
        period=period,
        start_time='',
        end_time='',
        count=-1
    )

    logging.info(f"数据字段: {list(data.keys())}")
    for code in stock_list:
        df = data[code]
        logging.info(f"\n===== {code} DataFrame =====")
        logging.info(f"index (字段): {list(df.index)}")
        logging.info(f"columns (日期): {list(df.columns)[:10]}")
        logging.info(f"head:\n{df.head()}")

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