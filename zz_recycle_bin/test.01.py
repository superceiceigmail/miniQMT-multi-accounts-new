from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount
from xtquant import xtconstant
import time


class MyXtQuantTraderCallback(XtQuantTraderCallback):
    def on_disconnected(self):
        """连接断开"""
        print("Connection lost")

    def on_stock_order(self, order):
        """委托回报推送"""
        print(f"Order callback: {order.stock_code}, Status: {order.order_status}, Order ID: {order.order_id}")

    def on_stock_trade(self, trade):
        """成交变动推送"""
        print(f"Trade callback: {trade.stock_code}, Volume: {trade.traded_volume}, Price: {trade.traded_price}")

    def on_order_error(self, order_error):
        """委托失败推送"""
        print(f"Order Error: {order_error.order_id}, {order_error.error_msg}")


def place_sell_order():
    """
    执行卖出操作的函数
    """
    print(f"[{datetime.now()}] Starting sell order process...")

    # 配置路径和账号信息
    path = "D:\\gjqmt\\userdata_mini"  # 替换为您的MiniQMT路径
    session_id = 123456  # 会话编号
    account_id = "8886006288"  # 替换为您的资金账号

    # 创建交易实例
    trader = XtQuantTrader(path, session_id)
    callback = MyXtQuantTraderCallback()
    trader.register_callback(callback)

    # 启动交易线程
    trader.start()

    # 建立交易连接
    if trader.connect() != 0:
        print("Failed to connect to trading system")
        return

    # 订阅资金账号
    account = StockAccount(account_id, "STOCK")
    if trader.subscribe(account) != 0:
        print("Failed to subscribe to account")
        return

    # 股票代码和卖出数量
    stock_code = "511880.SH"  # 股票代码
    sell_volume = 100 * 100  # 100手（1手 = 100股）

    # 获取最新价格（示例固定价格，实际可通过行情接口获取）
    latest_price = 100.0  # 请根据您的需求获取实时价格
    print(f"Placing sell order for {stock_code}, Volume: {sell_volume}, Price: {latest_price}")

    # 下单卖出
    order_id = trader.order_stock(account, stock_code, xtconstant.STOCK_SELL, sell_volume, xtconstant.FIX_PRICE, latest_price, "sell_strategy", "sell_511880")
    if order_id > 0:
        print(f"Sell order placed successfully, Order ID: {order_id}")
    else:
        print("Failed to place sell order")


if __name__ == "__main__":
    # 创建后台调度器
    scheduler = BackgroundScheduler()

    # 添加每天早上 9:20 执行的任务
    scheduler.add_job(place_sell_order, 'cron', hour=17, minute=3)

    # 启动调度器
    scheduler.start()
    print("Scheduler started. Waiting for the scheduled time...")

    try:
        # 主线程保持运行
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        # 捕获退出信号，关闭调度器
        scheduler.shutdown()
        print("Scheduler shut down.")