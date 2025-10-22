#!/usr/bin/env python3
# main.py — 程序入口（精简版）
import os
import sys
import time
import logging
import traceback
from datetime import datetime

from utils.log_utils import ensure_utf8_stdio, setup_logging
from utils.config_loader import load_json_file
from utils.stock_data_loader import load_stock_code_maps
from utils.asset_helpers import positions_to_dict
from preprocessing.qmt_connector import ensure_qmt_and_connect
from preprocessing.qmt_daily_restart_checker import check_and_restart
from processor.trade_plan_generation import print_trade_plan as generate_trade_plan_final_func
from utils.git_push_tool import push_project_to_github
from xtquant.xttype import StockAccount
from xtquant import xtdata

# 本地拆分模块
import helpers
import tasks

# 常量（保留你的原配置或改为外部配置）
ACCOUNT_CONFIG_MAP = {
    "shu": "core_parameters/account/8886006288.json",
    "mama": "core_parameters/account/mama.json",
}

YUNFEI_SCHEDULE_TIMES = helpers.YUNFEI_SCHEDULE_TIMES
AUTO_BUY_511880_TIME = helpers.AUTO_BUY_511880_TIME
AUTO_SELL_511880_TIME = helpers.AUTO_SELL_511880_TIME


def main():
    ensure_utf8_stdio()
    helpers.install_console_stream_filters()

    try:
        args = helpers.parse_args()
        account_name = args.account
    except SystemExit:
        raise
    except Exception as e:
        print("解析参数失败:", e)
        raise

    if not helpers.check_duplicate_instance('main.py', account_name):
        print(f"账户[{account_name}]已有实例运行，退出")
        sys.exit(0)

    setup_logging(console=True, file=True, account_name=account_name)

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

    path_qmt = config['path_qmt']
    session_id = config['session_id']
    account_id = config['account_id']
    sell_time = config['sell_time']
    buy_time = config['buy_time']
    check_time_first = config['check_time_first']
    check_time_second = config['check_time_second']

    # 检查 miniQMT 并保证连接
    check_and_restart(config_path)

    # 初始化 xt_trader（回调在 helpers 中定义并注册）
    xt_trader = helpers.init_xt_trader(path_qmt, session_id)

    # 确保 qmt 连接（会使用 xt_trader）
    ensure_qmt_and_connect(config_path, xt_trader, logger=logging)

    # 加载股票代码与 reverse mapping
    try:
        _, _, reverse_mapping = load_stock_code_maps()
        logging.info("股票代码加载成功，并生成 reverse_mapping")
    except Exception as e:
        logging.error(f"加载股票代码失败: {e}")
        xt_trader.stop()
        return

    # 初始资产/持仓快照（用于生成交易计划）
    account_asset_info = helpers.print_account_asset(xt_trader, account_id)
    positions = helpers.print_positions(xt_trader, account_id, reverse_mapping, account_asset_info)
    positions_dict = positions_to_dict(positions)

    # 生成最终交易计划（覆盖或创建文件）
    trade_plan_draft_file_path = 'tradeplan/trade_plan_draft.json'
    trade_date = datetime.now().strftime('%Y-%m-%d')
    trade_plan_file = f'./tradeplan/final/trade_plan_final_{account_id}_{trade_date.replace("-", "")}.json'

    generate_trade_plan_final_func(
        config=config,
        account_asset_info=account_asset_info,
        positions=positions_dict,
        trade_date=trade_date,
        setting_file_path=trade_plan_draft_file_path,
        trade_plan_file=trade_plan_file
    )

    time.sleep(1)
    logging.info("布置定时任务")
    scheduler = helpers.create_scheduler()

    # 注册关键任务（使用 tasks 中的工厂）
    sell_task = tasks.sell_execution_task_factory(xt_trader, account_id, trade_plan_file, trade_plan_draft_file_path)
    helpers.add_cron_job(scheduler, sell_task, sell_time, job_id="sell_execution_task")

    buy_task = tasks.buy_execution_task_factory(xt_trader, account_id, trade_plan_file, trade_plan_draft_file_path)
    helpers.add_cron_job(scheduler, buy_task, buy_time, job_id="buy_execution_task")

    cancel_times = [check_time_first, check_time_second, "13:00:03"]
    cancel_jobs = []
    for idx, t in enumerate(cancel_times, 1):
        cancel_jobs.append({
            "func": tasks.cancel_and_reorder_task_factory(xt_trader, account_id, reverse_mapping),
            "time": t,
            "id": f"cancel_and_reorder_task_{idx}"
        })
    helpers.add_multiple_cron_jobs(scheduler, cancel_jobs)

    print_jobs = [
        {"func": tasks.print_positions_task_factory(xt_trader, account_id, reverse_mapping), "time": "09:35:00", "id": "print_positions_task_0935"},
        {"func": tasks.print_positions_task_factory(xt_trader, account_id, reverse_mapping), "time": "14:57:00", "id": "print_positions_task_1457"}
    ]
    helpers.add_multiple_cron_jobs(scheduler, print_jobs)

    # 511880 自动买卖
    buy_h, buy_m, buy_s = AUTO_BUY_511880_TIME
    buy_511880_job = tasks.buy_all_funds_to_511880_factory(xt_trader, account_id)
    helpers.add_cron_job(scheduler, buy_511880_job, f"{buy_h:02d}:{buy_m:02d}:{buy_s:02d}", job_id="auto_buy_511880")
    chk_buy_h, chk_buy_m, chk_buy_s = helpers.add_seconds_to_hms(buy_h, buy_m, buy_s, 20)
    helpers.add_cron_job(scheduler, tasks.cancel_and_reorder_task_factory(xt_trader, account_id, reverse_mapping),
                         f"{chk_buy_h:02d}:{chk_buy_m:02d}:{chk_buy_s:02d}", job_id="check_after_511880_buy")

    sell_h, sell_m, sell_s = AUTO_SELL_511880_TIME
    sell_511880_job = tasks.sell_all_511880_factory(xt_trader, account_id)
    helpers.add_cron_job(scheduler, sell_511880_job, f"{sell_h:02d}:{sell_m:02d}:{sell_s:02d}", job_id="auto_sell_511880")
    chk_sell_h, chk_sell_m, chk_sell_s = helpers.add_seconds_to_hms(sell_h, sell_m, sell_s, 20)
    helpers.add_cron_job(scheduler, tasks.cancel_and_reorder_task_factory(xt_trader, account_id, reverse_mapping),
                         f"{chk_sell_h:02d}:{chk_sell_m:02d}:{chk_sell_s:02d}", job_id="check_after_511880_sell")

    # 自动推送 frontend（保持原有 lambda 调用方式）
    helpers.add_cron_job(
        scheduler,
        lambda path=r"C:\Users\ceicei\PycharmProjects\miniQMT-frontend": push_project_to_github(path),
        "09:36:00",
        job_id="push_miniQMT_frontend_to_github"
    )

    # 云飞跟投任务（使用当前快照）
    helpers.add_yunfei_jobs(scheduler, xt_trader, config, account_asset_info, positions_dict, StockAccount(account_id))

    scheduler.start()

    # 信号注册（会在 handle_exit 中停止 scheduler 和 xt_trader）
    helpers.register_signal_handlers(scheduler, xt_trader)

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