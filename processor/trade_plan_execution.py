# coding:utf-8
import time
import datetime
import math
import logging
from typing import Dict, Any, Optional

from xtquant import xtdata
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount, _XTCONST_

from utils.log_utils import emit, get_logger

logger = get_logger(__name__)

class MyXtQuantTraderCallback(XtQuantTraderCallback):
    def on_disconnected(self):
        emit(logger, f"{datetime.datetime.now()} - 连接断开回调", level="error")

    def on_stock_order(self, order):
        emit(logger, f"{datetime.datetime.now()} - 委托回调 投资备注: {order.order_remark}")

    def on_stock_trade(self, trade):
        emit(
            logger,
            f"{datetime.datetime.now()} - 成交回调 {trade.order_remark} "
            f"委托方向(48买 49卖) {trade.offset_flag} 成交价格 {trade.traded_price} 成交数量 {trade.traded_volume}"
        )

    def on_order_error(self, order_error):
        emit(logger, f"委托报错回调 {order_error.order_remark} {order_error.error_msg}", level="error")

    def on_cancel_error(self, cancel_error):
        emit(logger, f"{datetime.datetime.now()} - 撤单失败回调", level="error")

    def on_order_stock_async_response(self, response):
        emit(logger, f"异步委托回调 投资备注: {response.order_remark}")

    def on_cancel_order_stock_async_response(self, response):
        emit(logger, f"{datetime.datetime.now()} - 撤单异步回调")

    def on_account_status(self, status):
        emit(logger, f"{datetime.datetime.now()} - 账户状态回调")


def _round_price_to_tick(price: float, tick: float) -> float:
    if tick and tick > 0:
        # 避免浮点误差，保留多一点精度
        return round(round(price / tick) * tick, 10)
    return price


def _clamp_price(price: float, lower: Optional[float], upper: Optional[float]) -> float:
    if lower is not None:
        price = max(price, lower)
    if upper is not None:
        price = min(price, upper)
    return price


def _get_board_lot(detail: Dict[str, Any], default_lot: int = 100) -> int:
    # 从合约细节里兜底读取最小成交单位
    for key in ("MinVolume", "VolumeStep", "TradeVolumeUnit"):
        v = detail.get(key)
        if isinstance(v, (int, float)) and v > 0:
            return int(v)
    return default_lot


def _safe_get_tick(stock: str, side: str, retry: int = 2, sleep_sec: float = 0.2) -> Dict[str, Any]:
    """
    获取 tick，必要时短重试。side: 'buy' 或 'sell'，用于回退价选择。
    """
    last_exc: Optional[Exception] = None
    for _ in range(max(1, retry + 1)):
        try:
            data = xtdata.get_full_tick([stock]) or {}
            tick = data.get(stock) or {}
            last_price = tick.get("lastPrice")
            if last_price is not None and last_price > 0:
                return tick
            if side == "buy":
                asks = tick.get("askPrice")
                if asks and isinstance(asks, (list, tuple)) and asks and asks[0]:
                    return tick
            else:
                bids = tick.get("bidPrice")
                if bids and isinstance(bids, (list, tuple)) and bids and bids[0]:
                    return tick
        except Exception as e:
            last_exc = e
        time.sleep(sleep_sec)
    if last_exc:
        emit(logger, f"{stock} 获取tick失败，返回空tick，原因：{last_exc}", level="warning")
    return {}


def _extract_working_price(tick: Dict[str, Any], side: str) -> Optional[float]:
    """
    提取用于下单的价格：
    - 优先 lastPrice
    - 买单回退 askPrice[0]，卖单回退 bidPrice[0]
    """
    p = tick.get("lastPrice")
    if p and p > 0:
        return float(p)
    if side == "buy":
        asks = tick.get("askPrice")
        if asks and isinstance(asks, (list, tuple)) and asks and asks[0]:
            return float(asks[0])
    else:
        bids = tick.get("bidPrice")
        if bids and isinstance(bids, (list, tuple)) and bids and bids[0]:
            return float(bids[0])
    return None


def _get_limits(detail: Dict[str, Any], tick: Dict[str, Any]) -> (Optional[float], Optional[float]):
    """
    提取涨跌停限制（尽可能兼容不同字段名）。
    """
    keys_upper = ["UpperLimitPrice", "LimitUp", "highLimited", "upperLimitPrice"]
    keys_lower = ["LowerLimitPrice", "LimitDown", "lowLimited", "lowerLimitPrice"]

    upper = None
    lower = None
    for k in keys_upper:
        v = detail.get(k)
        if v:
            upper = float(v)
            break
    for k in keys_lower:
        v = detail.get(k)
        if v:
            lower = float(v)
            break

    if upper is None:
        v = tick.get("highLimited")
        if v:
            upper = float(v)
    if lower is None:
        v = tick.get("lowLimited")
        if v:
            lower = float(v)
    return lower, upper


def execute_trade_plan(
    trader: XtQuantTrader,
    account: StockAccount,
    trade_plan: dict,
    action: Optional[str] = None,
    logger_: Optional[logging.Logger] = None
):
    """
    根据交易计划执行所有卖单和买单
    :param action: 'buy' 只买入, 'sell' 只卖出, None或'all'买卖都执行
    """
    lg = logger_ or logger

    # 账户资金与持仓
    account_info = trader.query_stock_asset(account)
    available_cash = float(getattr(account_info, "m_dCash", 0.0))
    positions = trader.query_stock_positions(account)
    position_available_dict = {i.stock_code: int(getattr(i, "m_nCanUseVolume", 0)) for i in positions}

    #    emit(lg, f"{account.account_id} 可用资金: {available_cash:.2f}", level="debug")
    #    emit(lg, f"{account.account_id} 可用持仓字典: {position_available_dict}", level="debug")

    now = datetime.datetime.now()
    cutover = now.replace(hour=9, minute=29, second=0, microsecond=0)
    tick_offset = 5 if now < cutover else 1

    # 先卖，释放资金
    if action in (None, "all", "sell"):
        for sell_item in trade_plan.get("sell", []):
            stock = sell_item.get("code")
            if not stock:
                emit(lg, f"【严重报错】卖单缺少代码字段: {sell_item}", level="error")
                continue
            try:
                target_vol = int(sell_item.get("actual_lots", 0))
                available_vol = int(position_available_dict.get(stock, 0))

                detail = xtdata.get_instrument_detail(stock) or {}
                price_tick = float(detail.get("PriceTick") or 0.01)
                board_lot = _get_board_lot(detail, default_lot=100)

                sell_vol = max(0, min(target_vol, available_vol))
                sell_vol = (sell_vol // board_lot) * board_lot

                tick = _safe_get_tick(stock, side="sell")
                current_price = _extract_working_price(tick, side="sell")
                if not current_price:
                    emit(lg, f"【严重报错】无法获取 {stock} 的有效卖出价格，跳过卖单", level="error")
                    continue

                raw_price = current_price - price_tick * tick_offset
                lower, upper = _get_limits(detail, tick)
                adjusted_price = _round_price_to_tick(_clamp_price(raw_price, lower, upper), price_tick)

                emit(
                    lg,
                    f"{stock} 当前价: {current_price:.4f} 偏移{tick_offset}tick后: {adjusted_price:.4f} "
                    f"目标量 {target_vol} 可用 {available_vol} 实际卖出 {sell_vol} 手({board_lot}/手)"
                )

                if sell_vol > 0 and adjusted_price > 0:
                    async_seq = trader.order_stock_async(
                        account, stock, _XTCONST_.STOCK_SELL, sell_vol, _XTCONST_.FIX_PRICE, adjusted_price,
                        "strategy_name", stock
                    )
                    emit(lg, f"{stock} 卖单已提交，异步委托序列号: {async_seq}")
                else:
                    emit(lg, f"{stock} 卖单未提交（数量或价格无效）", level="warning")
            except Exception as e:
                emit(lg, f"【严重报错】 卖单执行异常: {sell_item.get('name', stock)}，错误信息: {e}", level="error")
                continue

    # 后买，逐笔扣减可用资金
    if action in (None, "all", "buy"):
        for buy_item in trade_plan.get("buy", []):
            stock = buy_item.get("code")
            if not stock:
                emit(lg, f"【严重报错】买单缺少代码字段: {buy_item}", level="error")
                continue
            try:
                target_amount = float(buy_item.get("amount", 0.0))
                if available_cash <= 0:
                    emit(lg, f"{stock} 可用资金为 0，跳过后续买单", level="warning")
                    break

                detail = xtdata.get_instrument_detail(stock) or {}
                price_tick = float(detail.get("PriceTick") or 0.01)
                board_lot = _get_board_lot(detail, default_lot=100)

                tick = _safe_get_tick(stock, side="buy")
                current_price = _extract_working_price(tick, side="buy")
                if not current_price:
                    emit(lg, f"【严重报错】无法获取 {stock} 的有效买入价格，跳过买单", level="error")
                    continue

                raw_price = current_price + price_tick * tick_offset
                lower, upper = _get_limits(detail, tick)
                adjusted_price = _round_price_to_tick(_clamp_price(raw_price, lower, upper), price_tick)

                budget = min(target_amount, available_cash)
                est_vol = int(budget / adjusted_price / board_lot) * board_lot

                emit(
                    lg,
                    f"{stock} 当前价: {current_price:.4f} 偏移{tick_offset}tick后: {adjusted_price:.4f} "
                    f"目标金额 {target_amount:.2f} 预算 {budget:.2f} 估算股数 {est_vol} 手({board_lot}/手)"
                )

                if est_vol > 0 and adjusted_price > 0:
                    async_seq = trader.order_stock_async(
                        account, stock, _XTCONST_.STOCK_BUY, est_vol, _XTCONST_.FIX_PRICE, adjusted_price,
                        "strategy_name", stock
                    )
                    emit(lg, f"{stock} 买单已提交，异步委托序列号: {async_seq}")
                    # 粗估扣减（手续费忽略或另行处理）
                    available_cash -= est_vol * adjusted_price
                else:
                    emit(lg, f"{stock} 买单未提交（预算不足以整手或价格无效）", level="warning")
            except Exception as e:
                emit(lg, f"【严重报错】 买单执行异常: {buy_item.get('name', stock)}，错误信息: {e}", level="error")
                continue

    # === 在这里加委托列表打印（卖买都处理完后） ===
    orders = trader.query_stock_orders(account)
    emit(lg, f"当前委托列表: {[o.order_remark for o in orders]}")
    emit(lg, "所有交易计划已尝试提交，检查券商客户端委托流水确认。")

if __name__ == '__main__':
    emit(logger, "开始交易执行模块")