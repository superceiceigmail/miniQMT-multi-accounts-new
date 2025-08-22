from datetime import datetime, time

def check_trade_times(trade_times, time_range=(time(9, 20), time(19, 59)), auto_mode=True):
    """
    检查一组交易时间是否合规。支持自动模式用于接口调用，不再需要交互。
    返回：(是否通过, 交易时间列表, 错误/警告信息列表)
    """
    now = datetime.now()
    current_time = now.time()
    start_time, end_time = time_range

    expired_list = []
    out_of_range_list = []
    messages = []

    for trade_time in trade_times:
        trade_time_obj = datetime.strptime(trade_time, "%H:%M:%S").time()

        # 1. 检查特殊情况
        if current_time < time(9, 30) and trade_time_obj >= time(10, 0):
            msg = f"❌ 错误：交易时间 {trade_time} 配置到了10点以后，请修正为10点以前。"
            messages.append(msg)
            return False, trade_times, messages

        # 2. 检查是否过期
        if trade_time_obj <= current_time:
            msg = f"❌ 错误：交易时间 {trade_time} 已经过期，当前时间为 {now.strftime('%H:%M:%S')}。"
            expired_list.append(trade_time)
            messages.append(msg)

        # 3. 检查是否在规定时间范围
        if not (start_time <= trade_time_obj <= end_time):
            msg = (f"⚠️ 警告：交易时间 {trade_time} 不在规定区间 "
                   f"({start_time.strftime('%H:%M')} ~ {end_time.strftime('%H:%M')}) 内，请检查设置！")
            out_of_range_list.append(trade_time)
            messages.append(msg)

    if out_of_range_list:
        return False, trade_times, messages

    if expired_list:
        return False, trade_times, messages

    # 全部通过
    return True, trade_times, messages