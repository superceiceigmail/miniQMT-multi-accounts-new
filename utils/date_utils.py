from datetime import datetime

# 中文星期映射
weekdays_cn = {
    0: '星期一',
    1: '星期二',
    2: '星期三',
    3: '星期四',
    4: '星期五',
    5: '星期六',
    6: '星期日'
}

def format_date(date_str):
    """
    格式化日期函数，将日期字符串格式化为标准格式：YYYY-MM-DD。
    如果月或日少于两位数字，会补齐前导零。
    """
    try:
        year, month, day = date_str.split('-')
        month = month.zfill(2)
        day = day.zfill(2)
        return f"{year}-{month}-{day}"
    except Exception as e:
        print(f"[ERROR] 日期格式化失败: {e}")
        return None

def get_weekday(date_str):
    """
    根据日期字符串获取中文星期几。
    支持 YYYY-MM-DD 格式的日期字符串。
    """
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        return weekdays_cn.get(date_obj.weekday(), '未知')
    except Exception as e:
        print(f"[ERROR] 日期转换星期失败: {e}")
        return None

if __name__ == "__main__":
    # 测试代码
    test_date = "2025-04-21"
    formatted_date = format_date(test_date)
    print(f"格式化日期: {formatted_date}")
    weekday = get_weekday(test_date)
    print(f"对应星期: {weekday}")