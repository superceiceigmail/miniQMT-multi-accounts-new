# utils/stock_data_loader.py

import os
from utils.config_loader import load_json_file
from utils.stock_code_mapper import generate_reverse_mapping

# 定义文件路径常量
STOCK_CODE_FILE_PATH = r"core_parameters/stocks/core_stock_code.json"
FULL_CODE_FILE_PATH = r"utils/stocks_code_search_tool/stocks_data/name_vs_code.json"


def load_stock_code_maps():
    """
    加载股票代码字典、名称与代码的完整映射，并生成反向查找函数和 reverse_mapping。

    返回:
        stock_code_dict: 核心股票代码字典 (dict)
        get_stock_code_func: 股票名称到代码的查找函数 (function)
        reverse_mapping: 代码到名称的反向映射 (dict)
    """
    try:
        # 1. 加载核心股票代码
        stock_code_dict = load_json_file(STOCK_CODE_FILE_PATH)

        # 2. 加载完整的名称/代码映射
        code2name = load_json_file(FULL_CODE_FILE_PATH)
        full_name2code = {v: k for k, v in code2name.items()}

        def get_stock_code(name):
            """查找股票代码，优先从核心字典，其次从完整映射。"""
            # 需要先通过 core_stock_code.json 查找，因为 full_name2code 只能通过 name 查 code
            core_code = stock_code_dict.get(name)
            if core_code:
                return core_code
            return full_name2code.get(name)

        # 3. 生成 reverse_mapping (main.py 需要)
        reverse_mapping = generate_reverse_mapping(stock_code_dict)

        return stock_code_dict, get_stock_code, reverse_mapping

    except Exception as e:
        # 抛出更具体的错误，供上层捕获
        raise IOError(f"❌ 无法加载股票代码文件或映射：{e}") from e