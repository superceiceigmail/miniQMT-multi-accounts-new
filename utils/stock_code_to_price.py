# coding:utf-8
import datetime
import json
from xtquant import xtdata

from utils.code_normalizer import normalize_code

def auto_add_suffix(code):
    """
    使用统一的 normalize_code 规则来返回带后缀的代码。
    """
    try:
        return normalize_code(str(code).strip())
    except Exception:
        return code  # 失败时保持原样

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

