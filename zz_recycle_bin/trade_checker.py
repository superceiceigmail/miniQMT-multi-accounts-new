from datetime import datetime, timedelta
from time import sleep
from xtquant.xttype import StockAccount
from xtquant.xttrader import XtQuantTrader
from xtquant.xttype import _XTCONST_


def check_and_handle_orders(trader, account):
    """
    检查十分钟内的所有未成交单，撤销无法成交的委托，并对撤销成功的部分重新下单。
    """
    print(f"\n--- 开始交易检查 --- 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")

    # 查询当日所有委托，仅查询可撤销的订单
    orders = trader.query_stock_orders(account, cancelable_only=True)
    if not orders:
        print("✅ 当前没有可撤销订单，无需处理。")
        return

    # 获取当前时间
    now = datetime.now()

    # 存储废单信息
    junk_orders = []

    # 用于重新下单的订单信息
    resubmit_orders = []

    for order in orders:
        order_time = datetime.strptime(str(order.order_time), "%H%M%S")

        # 如果订单时间超过10分钟，检查是否需要撤单
        if now - order_time > timedelta(minutes=10):
            if order.order_status in {_XTCONST_.ORDER_UNREPORTED, _XTCONST_.ORDER_WAIT_REPORTING, _XTCONST_.ORDER_REPORTED}:
                # 撤销订单
                print(f"⚠️ 检测到未成交订单，正在撤销，订单编号：{order.order_id}, 股票代码：{order.stock_code}, 状态：{order.status_msg}")
                cancel_result = trader.cancel_order_stock_async(account, order.order_id)
                if cancel_result == 0:
                    print(f"✅ 成功撤销订单，订单编号：{order.order_id}")
                    resubmit_orders.append(order)  # 将成功撤销的订单加入重新下单列表
                else:
                    print(f"❌ 撤销失败，订单编号：{order.order_id}")
            elif order.order_status == _XTCONST_.ORDER_JUNK:
                # 收集废单信息
                junk_orders.append(order)

    # 等待8秒后，检查成交情况
    sleep(8)

    # 查询当日所有成交
    trades = trader.query_stock_trades(account)
    if not trades:
        trades = []
    traded_volumes = {trade.order_id: trade.traded_volume for trade in trades}

    # 对撤销成功的部分重新下单
    for order in resubmit_orders:
        remaining_volume = order.order_volume - traded_volumes.get(order.order_id, 0)
        if remaining_volume > 0:
            print(f"🔄 撤单后重新下单，股票代码：{order.stock_code}, 剩余数量：{remaining_volume}, 原订单编号：{order.order_id}")
            new_order_result = trader.order_stock_async(
                account, order.stock_code, order.offset_flag, remaining_volume,
                _XTCONST_.FIX_PRICE, order.price, 'resubmit_strategy', order.stock_code
            )
            if new_order_result == 0:
                print(f"✅ 新订单提交成功，股票代码：{order.stock_code}, 剩余数量：{remaining_volume}")
            else:
                print(f"❌ 新订单提交失败，股票代码：{order.stock_code}, 剩余数量：{remaining_volume}")

    # 打印废单信息
    if junk_orders:
        print("\n以下为废单信息：")
        for junk_order in junk_orders:
            print(f"🚫 废单 - 股票代码：{junk_order.stock_code}, 原因：{junk_order.status_msg}, 委托编号：{junk_order.order_id}")
    else:
        print("✅ 无废单。")

    print("\n--- 交易检查完成 ---")


if __name__ == "__main__":
    # 示例使用
    path = 'D:\\gjqmt\\userdata_mini'  # xtquant 客户端路径
    session_id = 8886006288  # 会话编号
    account_id = '8886006288'  # 资金账号

    # 初始化 XtQuantTrader
    xt_trader = XtQuantTrader(path, session_id)

    # 创建资金账号对象
    account = StockAccount(account_id)

    # 尝试连接
    if xt_trader.connect() == 0:
        print("连接成功！")
        # 执行交易检查
        check_and_handle_orders(xt_trader, account)
    else:
        print("连接失败，无法执行交易检查。")