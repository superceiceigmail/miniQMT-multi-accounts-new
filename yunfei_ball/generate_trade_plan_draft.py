import json
import re
import os


def parse_trade_operations(operation_str, ratio, sample_amount):
    sell_stocks_info = []
    buy_stocks_info = []

    # 支持中英文分号
    operations = re.split(r'[;；]', operation_str)
    for op in operations:
        op = op.strip()
        if not op:
            continue
        # 支持带 SH/SZ 后缀的代码
        match = re.match(r'(买入|卖出)\s*([^(]+)\(([\w\.]+)\)', op)
        if not match:
            print("[未匹配行]", op)  # 可以加日志便于排查
            continue
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


# 【修改】函数名结尾添加 _func
def generate_trade_plan_draft_func(batch_no, operation_str, ratio, sample_amount, output_dir="setting"):
    """
    生成单个批次的 yunfei_trade_plan_draft_{batch_no}.json
    """
    sell_stocks_info, buy_stocks_info = parse_trade_operations(operation_str, ratio, sample_amount)
    plan = {
        "sell_stocks_info": sell_stocks_info,
        "buy_stocks_info": buy_stocks_info
    }
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 【修改】文件名改为 yunfei_trade_plan_draft_...
    file_path = os.path.join(output_dir, f"yunfei_trade_plan_draft_{batch_no}.json")
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)

    # 【修改】更新打印信息
    print(f"已生成交易计划草稿: {file_path}")

    # 【新增】返回文件路径，让调用方直接使用
    return file_path


def batch_generate_trade_plan_drafts_func(batch_operations, ratio, sample_amount, output_dir="setting"):
    """
    批量生成四个批次的计划 (示例函数)
    """
    for batch_no in range(1, 5):
        operation_str = batch_operations.get(batch_no, "")
        # 【修改】调用更新后的函数
        generate_trade_plan_draft_func(batch_no, operation_str, ratio, sample_amount, output_dir)


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
    # 【修改】调用更新后的示例函数
    batch_generate_trade_plan_drafts_func(batch_ops, ratio, sample_amount)