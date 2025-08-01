# coding:utf-8
import datetime
import json
from xtquant import xtdata

def auto_add_suffix(code):
    """
    自动为股票代码加市场后缀。简单规则：
    - 以6、5、9开头的为沪市 .SH
    - 以0、1、2、3、R开头的为深市 .SZ
    - 其它保留原样
    """
    if code.startswith(('6', '5', '9')):
        return code + '.SH'
    elif code.startswith(('0', '1', '2', '3', 'R')):
        return code + '.SZ'
    elif code.startswith('8'):
        return code + '.SH'
    else:
        return code  # 保留原样

def load_stock_codes(filename):
    """
    从文件中加载股票代码字典
    文件格式：每行一个股票，格式为 '名称': '代码',
    """
    stock_dict = {}
    with open(filename, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip().strip(',')
            if not line or ':' not in line:
                continue
            try:
                name, code = line.split(':')
                name = name.strip().strip("'").strip('"')
                code = code.strip().strip("'").strip('"')
                stock_dict[name] = code
            except Exception as e:
                print(f"无法解析行: {line}, 错误: {e}")
    return stock_dict

def get_latest_prices(stock_codes):
    """
    查询所有股票最新价格
    :param stock_codes: 股票代码列表
    :return: {原始代码: 最新价格}
    """
    prices = {}
    codes_with_suffix = [auto_add_suffix(code) for code in stock_codes]
    # 输出调试信息
    print("查询的带后缀代码列表：", codes_with_suffix)
    full_ticks = xtdata.get_full_tick(codes_with_suffix)
    print("full_ticks原始内容：", full_ticks)
    for original_code, code in zip(stock_codes, codes_with_suffix):
        tick = full_ticks.get(code)
        if tick:
            prices[original_code] = tick.get('lastPrice', None)
        else:
            prices[original_code] = None
    return prices

def label_stocks_with_latest_price(stock_file, output_file):
    """
    用 core_stock_code.json 文件生成带最新价格标签的 json 文件
    """
    stock_dict = load_stock_codes(stock_file)
    stock_codes = list(stock_dict.values())
    prices = get_latest_prices(stock_codes)
    labeled_data = {}
    for name, code in stock_dict.items():
        price = prices.get(code)
        labeled_data[name] = {'code': code, 'latest_price': price}
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(labeled_data, f, ensure_ascii=False, indent=2)
    print(f"{datetime.datetime.now()} 已完成最新价格标签文件: {output_file}")

