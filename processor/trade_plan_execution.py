# processor/trade_plan_execution.py
"""
执行交易计划（sell / buy）。本文件对持仓 code 匹配做了后缀变体容错，
使用 utils.code_normalizer.match_available_code_in_dict 来匹配 position keys，
并在日志中打印匹配细节便于排查。
"""
import datetime
import time
import logging
from typing import Optional, Dict, Any

from utils.code_normalizer import normalize_code, match_available_code_in_dict, canonical_variants
from xtquant import xtdata
from xtquant.xttype import StockAccount

logger = logging.getLogger(__name__)

def emit(lg, msg: str, level: str = "info"):
    if level == "error":
        lg.error(msg)
    elif level == "warning":
        lg.warning(msg)
    else:
        lg.info(msg)

def _get_board_lot(detail: dict, default_lot: int = 100) -> int:
    """
    Try to determine board lot (lot size) from instrument detail.
    Fallback to default_lot.
    """
    try:
        # common keys
        if not detail:
            return default_lot
        for k in ("BoardLot", "boardLot", "lotSize", "BoardLotSize"):
            if k in detail and detail.get(k):
                try:
                    return int(detail.get(k))
                except Exception:
                    pass
        # some funds/ETF may standardize on 100
        return default_lot
    except Exception:
        return default_lot

def _safe_get_tick(stock: str, side: str = "sell") -> dict:
    """
    get tick from xtdata; returns {} on failure
    side used to pick bid/ask if necessary.
    """
    try:
        tick = xtdata.get_full_tick([stock]).get(stock) or {}
        return tick
    except Exception:
        return {}

def _extract_working_price(tick: dict, side: str = "sell") -> Optional[float]:
    """
    Choose a working price from tick data depending on side:
      - for sell: use bid price (or lastPrice)
      - for buy: use ask price (or lastPrice)
    """
    try:
        if not tick:
            return None
        last = tick.get("lastPrice") or tick.get("last") or None
        if side == "sell":
            bid = tick.get("bidPrice") or tick.get("bid") or (tick.get("bidPrice1") if isinstance(tick.get("bidPrice1"), (int, float)) else None)
            if bid:
                return float(bid)
            if last:
                return float(last)
            # try ask fallback
            ask = tick.get("askPrice") or tick.get("ask")
            if ask:
                return float(ask)
        else:
            ask = tick.get("askPrice") or tick.get("ask") or (tick.get("askPrice1") if isinstance(tick.get("askPrice1"), (int, float)) else None)
            if ask:
                return float(ask)
            if last:
                return float(last)
            bid = tick.get("bidPrice") or tick.get("bid")
            if bid:
                return float(bid)
    except Exception:
        return None
    return None

def execute_trade_plan(trader, account: StockAccount, trade_plan: dict, action: Optional[str] = None, logger_: Optional[logging.Logger] = None):
    """
    Execute trade_plan for given account.
    :param trader: xt_trader instance (supports query_stock_asset, query_stock_positions, order_stock_async etc.)
    :param account: StockAccount instance
    :param trade_plan: dict containing 'sell' and 'buy' lists
    :param action: 'sell', 'buy', or None/'all'
    """
    lg = logger_ or logger

    # query account & positions
    try:
        account_info = trader.query_stock_asset(account)
        available_cash = float(getattr(account_info, "m_dCash", 0.0) or 0.0)
    except Exception as e:
        available_cash = 0.0
        emit(lg, f"查询账户资金失败: {e}", level="error")

    try:
        positions = trader.query_stock_positions(account) or []
    except Exception as e:
        positions = []
        emit(lg, f"查询持仓失败: {e}", level="error")

    # build available dict: keys are the exact codes returned by broker (e.g. '159949.SZ') and possibly normalized variants
    position_available: Dict[str, int] = {}
    position_raw_map: Dict[str, Any] = {}
    for p in positions:
        try:
            # support xt position object or dict-like
            stock_code = getattr(p, "stock_code", None) or getattr(p, "m_strStockCode", None) or getattr(p, "stock", None) or getattr(p, "stock_code", None)
            if not stock_code:
                # try dict keys
                try:
                    stock_code = p.get('stock_code') or p.get('code') or p.get('stock')
                except Exception:
                    stock_code = None
            if not stock_code:
                continue
            stock_code = str(stock_code).strip()
            can_use = int(getattr(p, "m_nCanUseVolume", 0) or getattr(p, "m_iCanUse", 0) or (p.get('m_nCanUseVolume') if isinstance(p, dict) else None) or (p.get('can_use') if isinstance(p, dict) else None) or 0)
            # store under as-is key and normalized key
            position_available[stock_code] = position_available.get(stock_code, 0) + int(can_use or 0)
            norm = normalize_code(stock_code)
            if norm != stock_code:
                position_available[norm] = position_available.get(norm, 0) + int(can_use or 0)
            # also store base (no suffix)
            base = stock_code.split('.')[0]
            if base and base not in position_available:
                position_available[base] = position_available.get(base, 0) + int(can_use or 0)
            # raw map
            position_raw_map[stock_code] = p
            position_raw_map[norm] = p
            position_raw_map[base] = p
        except Exception:
            continue

    emit(lg, f"{account.account_id} 可用持仓字典 keys: {list(position_available.keys())}", level="debug")

    # SELL phase: submit sell orders first
    if action in (None, "all", "sell"):
        for sell_item in trade_plan.get("sell", []):
            stock = sell_item.get("code") or sell_item.get("stock_code") or sell_item.get("stock")
            if not stock:
                emit(lg, f"【严重报错】卖单缺少代码字段: {sell_item}", level="error")
                continue
            name = sell_item.get("name") or sell_item.get("stock") or stock
            norm_code = normalize_code(stock)
            # try to find available key in position_available using variants
            matched_key = match_available_code_in_dict(norm_code, position_available)
            if not matched_key:
                # second attempt: try plain norm_code if present
                if norm_code in position_available:
                    matched_key = norm_code
            can_use_volume = int(position_available.get(matched_key, 0)) if matched_key else 0

            emit(lg, f"准备卖出: {name} 原始code={stock} 规范后={norm_code} 匹配到键={matched_key} 可用={can_use_volume}", level="info")

            if can_use_volume <= 0:
                emit(lg, f"[错误] 【{name}】当前没有可用持仓量！", level="error")
                continue

            # determine board lot and lots to sell (round down to board lot)
            try:
                detail = xtdata.get_instrument_detail(matched_key or norm_code) or {}
            except Exception:
                detail = {}
            board_lot = _get_board_lot(detail, default_lot=100)
            lots_to_sell = (can_use_volume // board_lot) * board_lot
            if lots_to_sell <= 0:
                emit(lg, f"[警告] {name} 计算到下单手数为0（board_lot={board_lot}，可用={can_use_volume}），跳过", level="warning")
                continue

            # get working price
            tick = _safe_get_tick(matched_key or norm_code, side="sell")
            price = _extract_working_price(tick, side="sell")
            if not price or price <= 0:
                emit(lg, f"【严重报错】无法获取 {matched_key or norm_code} 的有效卖出价格，跳过卖单", level="error")
                continue

            # submit order (async)
            try:
                from xtquant.xttype import _XTCONST_
                async_seq = trader.order_stock_async(account, matched_key or norm_code, _XTCONST_.STOCK_SELL, lots_to_sell, _XTCONST_.FIX_PRICE, price, f"auto_sell_{name}", matched_key or norm_code)
                emit(lg, f"已提交卖单 {matched_key or norm_code} 卖出 {lots_to_sell} 股，价格 {price}，异步号 {async_seq}", level="info")
            except Exception as e:
                emit(lg, f"提交卖单失败: {e}", level="error")

    # small pause to let async callbacks update positions (if any callback mechanism exists)
    time.sleep(1.0)

    # BUY phase
    if action in (None, "all", "buy"):
        for buy_item in trade_plan.get("buy", []):
            stock = buy_item.get("code") or buy_item.get("stock_code") or buy_item.get("stock")
            if not stock:
                emit(lg, f"【严重报错】买单缺少代码字段: {buy_item}", level="error")
                continue
            name = buy_item.get("name") or buy_item.get("stock") or stock
            norm_code = normalize_code(stock)
            # amount to spend
            target_amount = float(buy_item.get("amount") or buy_item.get("sample_amount") or buy_item.get("target_amount") or 0.0)
            if target_amount <= 0:
                emit(lg, f"[警告] 买单 {name} 目标金额为0，跳过", level="warning")
                continue

            # refresh available cash (best-effort)
            try:
                account_info = trader.query_stock_asset(account)
                available_cash = float(getattr(account_info, "m_dCash", 0.0) or 0.0)
            except Exception:
                available_cash = available_cash  # keep previous

            if available_cash <= 0:
                emit(lg, f"{norm_code} 可用资金为 0，跳过后续买单", level="warning")
                break

            # get price and board_lot
            detail = xtdata.get_instrument_detail(norm_code) or {}
            board_lot = _get_board_lot(detail, default_lot=100)
            tick = _safe_get_tick(norm_code, side="buy")
            price = _extract_working_price(tick, side="buy")
            if not price or price <= 0:
                emit(lg, f"无法获取 {norm_code} 的买入价格，跳过买单", level="error")
                continue

            # compute volume (round down to board lot)
            volume = int(target_amount // price // board_lot) * board_lot
            if volume <= 0:
                emit(lg, f"按目标金额 {target_amount} 与价格 {price} 无法买入最小单位({board_lot})，跳过", level="info")
                continue

            # submit buy order
            try:
                from xtquant.xttype import _XTCONST_
                async_seq = trader.order_stock_async(account, norm_code, _XTCONST_.STOCK_BUY, volume, _XTCONST_.FIX_PRICE, price, f"auto_buy_{name}", norm_code)
                emit(lg, f"已提交买单 {norm_code} 买入 {volume} 股，价格 {price}，异步号 {async_seq}", level="info")
                # deduct estimated amount from available_cash to avoid over-placing subsequent buys in same loop
                available_cash -= volume * price
            except Exception as e:
                emit(lg, f"提交买单失败: {e}", level="error")

    emit(lg, "execute_trade_plan 完成", level="info")
    return