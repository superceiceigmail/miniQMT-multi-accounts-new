from xtquant.xttype import StockAccount
from xtquant import xtconstant, xtdata
from datetime import datetime, timedelta
import os
import json
import logging
REORDER_RECORD_DIR = "runtime/reorder_records"
def _get_today_reorder_record_file():
    today_str = datetime.now().strftime("%Y%m%d")
    # 自动创建目录（如果不存在）
    os.makedirs(REORDER_RECORD_DIR, exist_ok=True)
    return os.path.join(REORDER_RECORD_DIR, f"reorder_record_{today_str}.json")

def load_reorder_record():
    fname = _get_today_reorder_record_file()
    if os.path.exists(fname):
        try:
            with open(fname, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_reorder_record(record_set):
    fname = _get_today_reorder_record_file()
    with open(fname, 'w', encoding='utf-8') as f:
        json.dump(list(record_set), f)

def reorder_orders(trader, account_id, code_to_name_dict, window_min=10, price_offset_tick=2, min_hand=100):
    """
    对指定账户近window_min分钟内已撤单/部撤的订单，自动重下未成交部分。
    仅对当天未重下过的撤单号进行重下，防止重复重下。
    买入：最新价+price_offset_tick*tick，卖出：最新价-price_offset_tick*tick
    仅重下剩余大于min_hand的部分
    """
    account = StockAccount(account_id)
    orders = trader.query_stock_orders(account)
    if not orders:
        logging.warning("没有委托数据返回")
        return

    logging.info(f"\n=== 最近{window_min}分钟内未重下过的已撤销委托重下 ===")
    logging.info(f"{'订单编号':<12}{'柜台合同编号':<12}{'时间':<19}{'股票名称':<12}{'股票代码':<12}{'方向':<6}"
                 f"{'委托量':<8}{'成交':<8}{'价格':<8}{'状态':<8}")
    logging.info("-" * 110)

    cancelled_status_set = {53, 54}   # 53:部撤, 54:已撤
    now = datetime.now()
    reordered = load_reorder_record()
    record_changed = False

    for order in orders:
        # 兼容不同API字段
        order_status = getattr(order, "order_status", getattr(order, "m_nOrderStatus", None))
        if order_status not in cancelled_status_set:
            continue

        order_time = getattr(order, "order_time", getattr(order, "m_nOrderTime", None))
        try:
            order_time_obj = datetime.fromtimestamp(order_time)
        except Exception as e:
            logging.warning(f"订单{getattr(order, 'order_id', '')}时间戳解析失败，跳过：{e}")
            continue
        if not (now - timedelta(minutes=window_min) <= order_time_obj <= now):
            continue

        order_id = str(getattr(order, "order_id", getattr(order, "m_nOrderID", '')))
        order_sysid = getattr(order, "order_sysid", getattr(order, "m_strOrderSysID", ''))
        stock_code = getattr(order, "stock_code", getattr(order, "m_strStockCode", ''))
        stock_name = code_to_name_dict.get(stock_code.split('.')[0], '未知股票')
        order_type = getattr(order, "order_type", getattr(order, "m_nOrderType", None))
        order_volume = getattr(order, "order_volume", getattr(order, "m_nOrderVolume", 0))
        traded_volume = getattr(order, "traded_volume", getattr(order, "m_nTradedVolume", 0))
        price = getattr(order, "price", getattr(order, "m_dPrice", 0))

        # 用order_id作为当天已重下的唯一标识
        if order_id in reordered:
            logging.info(f"委托{order_id}今日已重下过，跳过。")
            continue

        # 判断买卖方向
        if order_type == 23:
            order_type_str = "买入"
            is_buy = True
        elif order_type == 24:
            order_type_str = "卖出"
            is_buy = False
        else:
            order_type_str = f"未知({order_type})"
            logging.warning(f"订单{order_id}未知买卖方向(order_type={order_type})，跳过")
            continue

        logging.info(f"{order_id:<12}{order_sysid:<12}{order_time_obj.strftime('%Y-%m-%d %H:%M'):<19}{stock_name:<12}{stock_code:<12}"
                     f"{order_type_str:<6}{order_volume:<8}{traded_volume:<8}{price:<8.4f}{'部撤/已撤':<8}")

        left_volume = order_volume - traded_volume
        if left_volume <= 0:
            logging.info(f"委托{order_id}已全部成交，无需重下。")
            continue
        if left_volume < min_hand:
            logging.info(f"委托{order_id}剩余量{left_volume}不足最小单位{min_hand}，跳过。")
            continue

        # 取整手
        left_volume = (left_volume // min_hand) * min_hand

        try:
            full_tick = xtdata.get_full_tick([stock_code])
            current_price = full_tick[stock_code]['lastPrice']
            instrument_detail = xtdata.get_instrument_detail(stock_code)
            if not instrument_detail:
                logging.warning(f"⚠️ 未能获取 {stock_code} 的详细信息，跳过重下单")
                continue
            price_tick = instrument_detail.get('PriceTick', 0.001)
            if is_buy:
                adjusted_price = round(current_price + price_offset_tick*price_tick, 4)
                logging.info(f"{stock_code} 买单: 最新价({current_price}) + {price_offset_tick}tick({price_tick}) = {adjusted_price}")
            else:
                adjusted_price = round(current_price - price_offset_tick*price_tick, 4)
                logging.info(f"{stock_code} 卖单: 最新价({current_price}) - {price_offset_tick}tick({price_tick}) = {adjusted_price}")
        except Exception as e:
            logging.warning(f"⚠️ 获取{stock_code}价格信息失败，跳过重下单，原因：{e}")
            continue

        # 下单
        try:
            async_seq = trader.order_stock_async(
                account, stock_code, 0 if is_buy else 1, left_volume,
                xtconstant.FIX_PRICE, adjusted_price,
                'reorder_cancelled', f"reorder_{stock_code}")
            logging.info(f"委托{order_id}已撤单且剩余{left_volume}已重下单，异步委托序列号: {async_seq}")
            reordered.add(order_id)
            record_changed = True
        except Exception as e:
            logging.warning(f"⚠️ 重下单失败: {e}")

    if record_changed:
        save_reorder_record(reordered)
    logging.info("-" * 110)