from datetime import datetime, time, timedelta
import logging

def check_trade_times(trade_times, time_range=(time(9, 20), time(19, 59)), exit_on_error=True):
    """
    检查一组交易时间是否合规。支持强制重设交易时间（输入B）。
    返回：(是否通过, 交易时间列表)
    """
    now = datetime.now()
    current_time = now.time()
    start_time, end_time = time_range

    expired_list = []
    out_of_range_list = []

    for trade_time in trade_times:
        trade_time_obj = datetime.strptime(trade_time, "%H:%M:%S").time()

        # 1. 检查特殊情况
        if current_time < time(9, 30) and trade_time_obj >= time(10, 0):
            logging.error(f"❌ 错误：皇上早上好，交易时间 {trade_time} 配置到了10点以后，请修正为10点以前。")
            if exit_on_error:
                exit(1)
            return False, trade_times

        # 2. 检查是否过期
        if trade_time_obj <= current_time:
            logging.error(f"❌ 错误：交易时间 {trade_time} 已经过期，当前时间为 {now.strftime('%H:%M:%S')}。")
            expired_list.append(trade_time)

        # 3. 检查是否在规定时间范围
        if not (start_time <= trade_time_obj <= end_time):
            logging.warning(
                f"⚠️ 警告：交易时间 {trade_time} 不在规定区间 ({start_time.strftime('%H:%M')} ~ {end_time.strftime('%H:%M')}) 内，请检查设置！"
            )
            out_of_range_list.append(trade_time)

    if out_of_range_list:
        return False, trade_times

    # 只询问一次是否继续
    if expired_list:
        times_str = ", ".join(expired_list)
        choice = input(f"有已过期交易时间：{times_str}，是否全部继续？(Y/N/B): ").strip().upper()
        if choice == 'Y':
            return True, trade_times
        elif choice == 'B':
            # 强制设置新交易时间：当前时间+2分钟，每次+10秒
            base_dt = now + timedelta(minutes=2)
            new_times = []
            for i in range(len(trade_times)):
                new_dt = base_dt + timedelta(seconds=10 * i)
                new_time_str = new_dt.strftime('%H:%M:%S')
                new_times.append(new_time_str)
                logging.warning(f"⚡ 强制重设第{i+1}个交易时间为: {new_time_str}")
            logging.warning(f"交易时间已全部重置: {new_times}")
            return True, new_times
        else:
            exit(1)

    # 全部通过
    return True, trade_times