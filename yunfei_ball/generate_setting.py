import json
import re
import os

def parse_trade_operations(operation_str, ratio, sample_amount):
    """
    解析买卖操作字符串，返回买入和卖出计划列表
    """
    sell_stocks_info = []
    buy_stocks_info = []

    # 按分号分割每个操作
    operations = [op.strip() for op in operation_str.split(';') if op.strip()]
    for op in operations:
        # 匹配“买入 xxx(代码)”或“卖出 xxx(代码)”
        match = re.match(r'(买入|卖出)\s*([^(]+)\((\d+)\)', op)
        if not match:
            continue  # 跳过无效行
        action, name, code = match.groups()
        stock_info = {
            "name": name.strip(),
            "code": code.strip(),
            "ratio": str(ratio),
            "sample_amount": float(sample_amount)
        }
        if action == "买入":
            buy_stocks_info.append(stock_info)
        elif action == "卖出":
            sell_stocks_info.append(stock_info)
    return sell_stocks_info, buy_stocks_info

def generate_setting_file(batch_no, operation_str, ratio, sample_amount, output_dir="setting"):
    """
    生成单个批次的yunfei_setting{batch_no}.json
    """
    sell_stocks_info, buy_stocks_info = parse_trade_operations(operation_str, ratio, sample_amount)
    plan = {
        "sell_stocks_info": sell_stocks_info,
        "buy_stocks_info": buy_stocks_info
    }
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    file_path = os.path.join(output_dir, f"yunfei_setting{batch_no}.json")
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)
    print(f"已生成{file_path}")

def batch_generate_setting_plans(batch_operations, ratio, sample_amount, output_dir="setting"):
    """
    批量生成四个批次的计划
    batch_operations: dict, 如 {1: "卖出 科创50(588000); 买入 日经ETF(513520);", 2: "..."}
    ratio: float
    sample_amount: float
    """
    for batch_no in range(1, 5):
        operation_str = batch_operations.get(batch_no, "")
        generate_setting_file(batch_no, operation_str, ratio, sample_amount, output_dir)

# 示例调用
if __name__ == "__main__":
    batch_ops = {
        1: "卖出 科创50(588000); 买入 日经ETF(513520);",
        2: "卖出 黄金ETF(518880); 买入 恒生ETF(159920);",
        3: "买入 纳指ETF(513100); 卖出 沪深300ETF(510300);",
        4: "买入 标普500ETF(513500);"
    }
    ratio = 1.03
    sample_amount = 751900.0
    batch_generate_trade_plans(batch_ops, ratio, sample_amount)