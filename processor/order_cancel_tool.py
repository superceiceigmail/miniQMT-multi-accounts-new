from xtquant.xttype import StockAccount
import logging

def cancel_orders(trader, account_id, code_to_name_dict):
    """
    打印指定资金账号的当前委托情况，并对状态为50（已报）和55（部成）的委托进行异步撤单。
    :param trader: XtQuantTrader 对象，用于查询交易数据。
    :param account_id: 资金账号（字符串）。
    :param code_to_name_dict: 股票代码到名称的映射字典。
    """
    account = StockAccount(account_id)
    orders = trader.query_stock_orders(account)

    if not orders:
        logging.warning("没有委托数据返回")
    else:
        logging.info("当前委托情况：")
        logging.info(f"{'订单编号':<12}{'柜台合同编号':<12}{'报单时间':<12}{'股票名称':<12}{'股票代码':<12}{'委托方向':<8}{'委托量':<8}{'成交量':<8}{'委托价格':<8}{'状态':<10}")
        logging.info("-" * 120)

        for order in orders:
            order_id = order.order_id
            order_sysid = order.order_sysid
            order_time = order.order_time
            stock_code = order.stock_code
            stock_name = code_to_name_dict.get(stock_code.split('.')[0], '未知股票')

            # 修正：用 m_nOrderType 判断买卖方向
            if hasattr(order, "m_nOrderType"):
                order_type = "买入" if order.m_nOrderType == 23 else "卖出" if order.m_nOrderType == 24 else f"未知({order.m_nOrderType})"
            else:
                order_type = "未知"  # 如果没有该字段

            order_volume = order.order_volume
            traded_volume = order.traded_volume
            price = order.price
            status = order.order_status

            status_dict = {
                48: "未报",
                49: "待报",
                50: "已报",
                51: "已报待撤",
                52: "部成待撤",
                53: "部撤",
                54: "已撤",
                55: "部成",
                56: "已成",
                57: "废单",
            }
            status_name = status_dict.get(status, "未知状态")

            logging.info(f"{order_id:<12}{order_sysid:<12}{order_time:<12}{stock_name:<12}{stock_code:<12}"
                         f"{order_type:<8}{order_volume:<8}{traded_volume:<8}{price:<8.2f}{status_name:<10}")

            if status in {50, 55}:
                market = 0  # 需根据实际情况设置
                cancel_result = trader.cancel_order_stock_sysid_async(account, market, order_sysid)
                if cancel_result > 0:
                    logging.info(f"合同编号 {order_sysid} 的异步撤单请求已成功发出，请等待撤单反馈。")
                else:
                    logging.warning(f"合同编号 {order_sysid} 的异步撤单请求失败，请检查原因。")

        logging.info("-" * 120)