import os
from utils.code_normalizer import normalize_code

def load_stock_codes(file_path):
    """
    从文件加载股票代码，生成股票名称与代码的映射字典。
    文件格式: 每行包含 '股票名称:股票代码'
    """
    stock_code_dict = {}
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            for line in file:
                if line.strip():  # 忽略空行
                    try:
                        name, code = line.strip().split(':')
                        name = name.strip().strip("'")
                        code = code.strip().strip("',")
                        # 使用统一的 normalize_code 来给出带后缀的 code
                        code = normalize_code(code)
                        stock_code_dict[name] = code
                    except ValueError:
                        print(f"[WARN] 跳过无效行: {line.strip()}")
    except FileNotFoundError:
        print(f"[ERROR] 股票代码文件未找到: {file_path}")
    except Exception as e:
        print(f"[ERROR] 加载股票代码失败: {e}")

    return stock_code_dict

def generate_reverse_mapping(stock_code_dict):
    """
    根据股票代码字典生成反向映射，支持从代码查找名称。
    """
    return {v.split('.')[0]: k for k, v in stock_code_dict.items()}


if __name__ == "__main__":
    # 测试代码
    test_file_path = "E:\\pankou\\DailyTrading\\stock_code.txt"
    if os.path.exists(test_file_path):
        stock_code_dict = load_stock_codes(test_file_path)
        print("股票代码字典:")
        print(stock_code_dict)
        reverse_mapping = generate_reverse_mapping(stock_code_dict)
        print("\n反向映射:")
        print(reverse_mapping)
    else:
        print(f"[ERROR] 示例股票代码文件未找到: {test_file_path}")