# tasks.py — 任务工厂（撤单/重下、打印持仓、511880 自动买卖、买/卖执行）
import time
import logging
from datetime import datetime
import json

from xtquant.xttype import StockAccount
from xtquant import xtdata
from processor.order_cancel_tool import cancel_orders
from processor.orders_reorder_tool import reorder_orders
from processor.trade_plan_execution import execute_trade_plan

# 撤单与重下
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

# 打印持仓
def print_positions_task_factory(xt_trader, account_id, reverse_mapping):
    def task():
        try:
            logging.info(f"--- 定时打印持仓任务 --- 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            account_asset_info = None
            # 直接调用 processor 的打印接口（main 中会传入）
            from processor.asset_connector import print_account_asset
            account_asset_info = print_account_asset(xt_trader, account_id)
            from processor.position_connector import print_positions
            positions = print_positions(xt_trader, account_id, reverse_mapping, account_asset_info)
            logging.info(f"持仓信息: {positions}")
        except Exception as e:
            logging.error(f"打印持仓失败: {e}")
    return task

# 511880 的买入（把逻辑保留）
def buy_all_funds_to_511880_factory(xt_trader, account_id):
    def task():
        logging.info(f"--- 自动买入银华日利 --- 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            account = StockAccount(account_id)
            account_info = xt_trader.query_stock_asset(account)
            available_cash = float(getattr(account_info, "m_dCash", 0.0) or 0.0)
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

# 511880 的卖出
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

# 卖出执行任务（支持在卖出后根据 draft 同时买入）
def sell_execution_task_factory(xt_trader, account_id, trade_plan_file, draft_file_path):
    def task():
        logging.info(f"--- 卖出任务 --- 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            from helpers import get_can_directly_buy, load_trade_plan
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

# 买入执行任务
def buy_execution_task_factory(xt_trader, account_id, trade_plan_file, draft_file_path):
    def task():
        logging.info(f"--- 买入任务 --- 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            from helpers import get_can_directly_buy, load_trade_plan
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