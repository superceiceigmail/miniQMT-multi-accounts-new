from xtquant.xttrader import XtQuantTrader
from xtquant.xttype import StockAccount
from other.date_utils import get_weekday


def calculate_actual_sell_lots(stock, current_volume):
    """
    根据输入的 `lots` 值和当前持仓量计算实际计划的卖出量。
    """
    if stock['lots'] == 99999:
        total_lots_to_sell = current_volume  # 卖出全部仓位
    elif stock['lots'] == 55555:
        total_lots_to_sell = current_volume // 2  # 卖出一半仓位
    elif stock['lots'] == 66666:
        total_lots_to_sell = current_volume * 2 // 3  # 卖出三分之二仓位
    elif stock['lots'] == 33333:
        total_lots_to_sell = current_volume // 3  # 卖出三分之一仓位
    else:
        total_lots_to_sell = min(stock['lots'], current_volume)  # 默认逻辑

    # 确保卖出量是 100 的倍数（向下取整）
    total_lots_to_sell = (total_lots_to_sell // 100) * 100
    return total_lots_to_sell


def print_trade_plan(trader, account_id, trade_date, sell_time, buy_time, check_sell_time, check_buy_time,
                     sell_stocks_info, buy_stocks_info, stock_code_dict):
    """
    打印交易计划，包括卖出和买入计划的详细信息。
    """
    print("交易计划：")

    # 创建资金账号对象
    account = StockAccount(account_id)

    # 查询当前持仓数据
    positions = trader.query_stock_positions(account)

    if not positions:
        print("没有持仓数据返回，无法计算卖出计划")
        return

    # 将持仓数据转换为字典，方便后续查找
    current_positions = {position.stock_code.split('.')[0]: position for position in positions}

    # 计算并打印卖出计划
    print(f"卖出计划：")
    for stock in sell_stocks_info:
        stock_code = stock_code_dict.get(stock['name'])
        if stock_code:
            # 查找当前持仓量
            stock_code_without_suffix = stock_code.split('.')[0]  # 去掉后缀
            position = current_positions.get(stock_code_without_suffix)

            if position:
                current_volume = position.volume
                can_use_volume = position.can_use_volume  # 可用数量
                frozen_volume = position.frozen_volume  # 冻结数量

                # 计算实际计划的卖出量
                actual_lots_to_sell = calculate_actual_sell_lots(stock, can_use_volume)

                print(f"  - 股票名称：{stock['name']}, 股票代码：{stock_code}, 原始输入数量：{stock['lots']}手, "
                      f"实际计划数量：{actual_lots_to_sell}手, 可用数量：{can_use_volume}手, 冻结数量：{frozen_volume}手")
            else:
                print(f"  - 股票名称：{stock['name']} 当前没有持仓")
        else:
            print(f"  - 股票名称：{stock['name']} 的代码未找到")
    print(f"\n")

    # 计算并打印买入计划
    print(f"买入计划：")
    for stock in buy_stocks_info:
        stock_code = stock_code_dict.get(stock['name'])
        if stock_code:
            print(f"  - 股票名称：{stock['name']}, 股票代码：{stock_code}, 金额：{stock['amount']}元")
        else:
            print(f"  - 股票名称：{stock['name']} 的代码未找到")
    print(f"\n")

    # 打印交易日期和时间
    print(f"交易日期：{trade_date} {get_weekday(trade_date)}")
    print(f"卖出时间：{sell_time}, 买入时间：{buy_time}")
    print(f"(检查卖出时间：{check_sell_time}, 检查买入时间：{check_buy_time})")
    print("-" * 50)  # 添加分割线


if __name__ == "__main__":
    # 配置实盘环境
    xt_trader_path = "D:\\gjqmt\\userdata_mini"  # 修改为您本地的 XtQuantTrader 路径
    session_id = 8886006288  # 替换为您的会话 ID
    account_id = "8886006288"  # 替换为您的资金账号

    # 初始化 XtQuantTrader 实例
    trader = XtQuantTrader(xt_trader_path, session_id)

    # 启动交易线程
    trader.start()

    # 建立交易连接
    if trader.connect() == 0:
        print("交易系统连接成功！")

        # 测试数据
        trade_date = "2025-04-21"
        sell_time = "09:30:00"
        buy_time = "10:30:00"
        check_sell_time = "09:35:00"
        check_buy_time = "10:35:00"
        sell_stocks_info = [{'name': '30年国债', 'lots': 99999}]
        buy_stocks_info = [{'name': '银华日利', 'amount': 14000}]
        stock_code_dict = {'30年国债': '511090.SH', '银华日利': '511880.SH'}

        # 打印交易计划
        print_trade_plan(trader, account_id, trade_date, sell_time, buy_time, check_sell_time, check_buy_time,
                         sell_stocks_info, buy_stocks_info, stock_code_dict)

        # 停止交易线程
        trader.stop()
    else:
        print("交易系统连接失败！")