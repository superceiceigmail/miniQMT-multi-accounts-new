from datetime import datetime, time
import logging

def check_trade_times(trade_times, time_range=(time(9, 20), time(19, 59)), exit_on_error=True):
    """
    检查一组交易时间是否合规，只在有过期交易时间时询问一次是否继续。
    用法：
        trade_times = [sell_time, buy_time, check_time_first, check_time_second]
        if not check_trade_times(trade_times):
            return

    检查内容：
    1. 检查特殊情况：如果当前时间早于9:30，且某个交易时间晚于等于10点，报错并退出或跳过。
    2. 检查所有交易时间是否有已过期的（小于等于当前时间）。如有则全部列出，并只询问一次“是否继续(Y/N)”，Y则通过全部，N则退出。
    3. 检查所有交易时间是否在指定时间范围（默认9:20~19:59）。如有不在区间则警告并返回False（跳过）。
    4. 所有检查通过返回True，否则返回False。
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
            return False

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
        return False

    # 只询问一次是否继续
    if expired_list:
        times_str = ", ".join(expired_list)
        choice = input(f"有已过期交易时间：{times_str}，是否全部继续？(Y/N): ").strip().upper()
        if choice == 'Y':
            return True
        else:
            exit(1)

    # 全部通过
    return True