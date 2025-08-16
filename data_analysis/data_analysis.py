import logging
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant import xtdata
import time


# ======= 固定miniQMT参数 =======
SESSION_ID = 8886006288
ACCOUNT_ID = "8886006288"
PATH_QMT = r"D:\gjqmt\userdata_mini"


# ==== 股票列表、周期、时间区间 ====
STOCK_LIST = ['600119.SH']
PERIODS = ['1d', '1h']  # 日线和小时线
START_TIME = '2020-01-01'
END_TIME = ''

# ========== 日志配置 ==========
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

class MyXtQuantTraderCallback(XtQuantTraderCallback):
    def on_disconnected(self):
        logging.error("miniQMT连接断开")
    def on_stock_order(self, order):
        logging.info(f"委托回调: {order.order_remark}")
    def on_stock_trade(self, trade):
        logging.info(f"成交回调: {trade.order_remark}, 成交价格: {trade.traded_price}, 成交数量: {trade.traded_volume}")
    def on_order_error(self, order_error):
        logging.error(f"委托报错: {order_error.order_remark}, 错误信息: {order_error.error_msg}")
    def on_cancel_error(self, cancel_error):
        logging.error("撤单失败回调")
    def on_order_stock_async_response(self, response):
        logging.info(f"异步委托回调: {response.order_remark}")
    def on_cancel_order_stock_async_response(self, response):
        logging.info("撤单异步回调")
    def on_account_status(self, status):
        logging.info("账户状态回调")

def connect_and_login_qmt():
    """
    启动并连接miniQMT
    """
    trader = XtQuantTrader(PATH_QMT, SESSION_ID)
    callback = MyXtQuantTraderCallback()
    trader.register_callback(callback)
    trader.start()
    logging.info("miniQMT连接启动成功")
    time.sleep(2)
    return trader

def download_history_data():
    for code in STOCK_LIST:
        for period in PERIODS:
            logging.info(f"开始下载 {code} 的 {period} 行情数据...")
            try:
                xtdata.download_history_data(
                    code,
                    period=period,
                    start_time=START_TIME,
                    end_time=END_TIME,
                    incrementally=True
                )
                logging.info(f"{code} {period} 下载完成。")
            except Exception as e:
                logging.error(f"{code} {period} 下载异常: {e}")

def analyze_local_data():
    time.sleep(2)
    for code in STOCK_LIST:
        for period in PERIODS:
            try:
                data = xtdata.get_local_data(
                    field_list=[],      # 空为全部字段
                    stock_list=[code],  # list类型
                    period=period,      # str类型
                    start_time='',
                    end_time='',
                    count=-1
                )
            except Exception as e:
                logging.error(f"{code} {period} 本地数据读取异常: {e}")
                continue

            if not data:
                logging.warning(f"{code} {period} 数据为空")
                continue

            for field, df in data.items():
                logging.info(f"\n==== {code} {period} 字段: {field} DataFrame ====")
                logging.info(f"index: {list(df.index)}")
                logging.info(f"columns: {list(df.columns)[:10]}")
                logging.info(f"数据预览:\n{df.head()}")
                if not df.empty:
                    # 仅分析close字段
                    if field == 'close':
                        # axis=1 代表对每只股票（只有一只）取所有日期的均值
                        close_mean = df.mean(axis=1)
                        close_max = df.max(axis=1)
                        close_min = df.min(axis=1)
                        latest_date = df.columns[-1]
                        latest_close = df.iloc[0, -1]
                        logging.info(f"{code} {period} 收盘均价: {close_mean.values[0]}")
                        logging.info(f"{code} {period} 收盘最高: {close_max.values[0]}")
                        logging.info(f"{code} {period} 收盘最低: {close_min.values[0]}")
                        logging.info(f"{code} {period} 最新收盘价({latest_date}): {latest_close}")
                else:
                    logging.info(f"{code} {period} 字段 {field} 数据为空")



def main():
    logging.info("======= 数据分析脚本启动 =======")
    trader = connect_and_login_qmt()
    download_history_data()
    analyze_local_data()
    trader.stop()
    logging.info("miniQMT连接已关闭")
    logging.info("======= 数据分析脚本结束 =======")

if __name__ == "__main__":
    main()