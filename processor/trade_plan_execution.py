# coding:utf-8
import time
import datetime
from xtquant import xtdata
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount, _XTCONST_
import json
import os

class MyXtQuantTraderCallback(XtQuantTraderCallback):
    def on_disconnected(self):
        print(datetime.datetime.now(), '连接断开回调')

    def on_stock_order(self, order):
        print(datetime.datetime.now(), '委托回调 投资备注', order.order_remark)

    def on_stock_trade(self, trade):
        print(datetime.datetime.now(), '成交回调', trade.order_remark,
              f"委托方向(48买 49卖) {trade.offset_flag} 成交价格 {trade.traded_price} 成交数量 {trade.traded_volume}")

    def on_order_error(self, order_error):
        print(f"委托报错回调 {order_error.order_remark} {order_error.error_msg}")

    def on_cancel_error(self, cancel_error):
        print(datetime.datetime.now(), "撤单失败回调")

    def on_order_stock_async_response(self, response):
        print(f"异步委托回调 投资备注: {response.order_remark}")

    def on_cancel_order_stock_async_response(self, response):
        print(datetime.datetime.now(), "撤单异步回调")

    def on_account_status(self, status):
        print(datetime.datetime.now(), "账户状态回调")

def execute_trade_plan(trader, account, trade_plan, action=None):
    """
    根据交易计划执行所有卖单和买单
    :param action: 'buy' 只买入, 'sell' 只卖出, None或'all'买卖都执行
    """
    # 查询当前持仓信息和可用资金
    account_info = trader.query_stock_asset(account)
    available_cash = account_info.m_dCash
    positions = trader.query_stock_positions(account)
    position_available_dict = {i.stock_code: i.m_nCanUseVolume for i in positions}

    print(account.account_id, '可用资金', available_cash)
    print(account.account_id, '可用持仓字典', position_available_dict)

    now = datetime.datetime.now()
    nine_thirty = now.replace(hour=9, minute=29, second=0, microsecond=0)
    tick_offset = 5 if now < nine_thirty else 1

    if action in (None, "all", "sell"):
        # 执行卖单
        for sell_item in trade_plan.get('sell', []):
            try:
                stock = sell_item['code']
                target_vol = sell_item['actual_lots']  # 从交易计划中获取实际卖出量
                available_vol = position_available_dict.get(stock, 0)
                sell_vol = min(target_vol, available_vol)

                full_tick = xtdata.get_full_tick([stock])
                current_price = full_tick[stock]['lastPrice']
                instrument_detail = xtdata.get_instrument_detail(stock)
                if not instrument_detail:
                    print(f"【严重报错】【严重报错】 未能获取 {stock} 的详细信息，跳过卖单")
                    continue
                price_tick = instrument_detail.get('PriceTick')
                adjusted_price = current_price - price_tick * tick_offset

                print(f"{stock} 当前价格：{current_price} 卖单偏移{tick_offset}个tick后价格：{adjusted_price} 目标卖出量 {target_vol} 可用数量 {available_vol} 实际卖出 {sell_vol} 股")
                if sell_vol > 0:
                    async_seq = trader.order_stock_async(
                        account, stock, _XTCONST_.STOCK_SELL, sell_vol, _XTCONST_.FIX_PRICE, adjusted_price,
                        'strategy_name', stock)
                    print(f"{stock} 卖单已提交，异步委托序列号: {async_seq}")
            except Exception as e:
                print(f"【严重报错】【严重报错】 卖单执行异常: {sell_item.get('name', stock)}，错误信息: {e}")
                continue

    if action in (None, "all", "buy"):
        # 执行买单
        for buy_item in trade_plan.get('buy', []):
            try:
                stock = buy_item['code']
                target_amount = buy_item['amount']
                # 调试打印（加在这里）
                print(f"本次买单代码: {stock}")
                print(f"xtdata.get_full_tick([{stock}]) 查询结果: {xtdata.get_full_tick([stock])}")

                full_tick = xtdata.get_full_tick([stock])
                current_price = full_tick[stock]['lastPrice']
                instrument_detail = xtdata.get_instrument_detail(stock)
                if not instrument_detail:
                    print(f"【严重报错】【严重报错】 未能获取 {stock} 的详细信息，跳过买单")
                    continue
                price_tick = instrument_detail.get('PriceTick')
                adjusted_price = current_price + price_tick * tick_offset

                buy_amount = min(target_amount, available_cash)
                buy_vol = int(buy_amount / adjusted_price / 100) * 100

                print(f"{stock} 当前价格：{current_price} 买单偏移{tick_offset}个tick后价格：{adjusted_price} 目标买入金额 {target_amount} 实际买入股数 {buy_vol} 股")
                if buy_vol > 0:
                    async_seq = trader.order_stock_async(
                        account, stock, _XTCONST_.STOCK_BUY, buy_vol, _XTCONST_.FIX_PRICE, adjusted_price,
                        'strategy_name', stock)
                    print(f"{stock} 买单已提交，异步委托序列号: {async_seq}")
            except Exception as e:
                print(f"【严重报错】【严重报错】 买单执行异常: {buy_item.get('name', stock)}，错误信息: {e}")
                continue

if __name__ == '__main__':
    print("开始交易执行模块")
