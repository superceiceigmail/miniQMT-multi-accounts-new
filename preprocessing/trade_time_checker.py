from datetime import datetime, time
import logging

def check_trade_time(trade_time, time_range=(time(9, 20), time(19, 59)), exit_on_error=True):
    """
    检查交易时间是否合规。
    1. 检查特殊情况：如果当前时间早于9:30，而交易时间晚于10点，报错。
    2. 检查交易时间是否已过期。
    3. 检查交易时间是否在指定时间范围内（默认 9:20~19:59）。
    """
    now = datetime.now()
    current_time = now.time()
    trade_time_obj = datetime.strptime(trade_time, "%H:%M:%S").time()
    start_time, end_time = time_range

    # 新增逻辑：当前时间早于9:30，且trade_time晚于等于10:00
    if current_time < time(9, 30) and trade_time_obj >= time(10, 0):
        logging.error("❌ 错误：皇上早上好，昨天应该是忘了修正交易，请将交易时间配置到10点以前")
        if exit_on_error:
            exit(1)
        return False

    # 检查是否过期
    if trade_time_obj <= current_time:
        logging.error(f"❌ 错误：交易时间 {trade_time} 已经过期，当前时间为 {now.strftime('%H:%M:%S')}。")
        if exit_on_error:
            exit(1)
        return False

    # 检查是否在规定时间范围内
    if not (start_time <= trade_time_obj <= end_time):
        logging.warning(
            f"⚠️ 警告：交易时间 {trade_time} 不在规定的区间 ({start_time.strftime('%H:%M')} ~ {end_time.strftime('%H:%M')}) 内，请检查设置！"
        )
        return False

    return True