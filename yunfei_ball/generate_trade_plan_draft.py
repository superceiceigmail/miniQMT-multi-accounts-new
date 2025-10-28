import json
import re
import os
import time
import uuid

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


def atomic_write_json(path: str, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def generate_trade_plan_draft_func(batch_no, operation_str, ratio, sample_amount, output_dir="setting", strategy_id=None):
    """
    生成单个策略的交易计划草稿文件（per-strategy）。
    如果传入 strategy_id，会把 strategy_id 写入文件名；否则会使用时间戳+uuid确保唯一性。
    返回生成的文件路径。
    """
    sell_stocks_info, buy_stocks_info = parse_trade_operations(operation_str, ratio, sample_amount)
    plan = {
        "sell_stocks_info": sell_stocks_info,
        "buy_stocks_info": buy_stocks_info,
        "meta": {
            "batch_no": batch_no,
            "strategy_id": strategy_id,
            "created_at": time.strftime('%Y-%m-%dT%H:%M:%S')
        }
    }
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 生成唯一文件名：包含批次、策略id（若有）、时间戳和短 uuid
    ts = time.strftime('%Y%m%dT%H%M%S')
    uid = uuid.uuid4().hex[:8]
    if strategy_id:
        filename = f"yunfei_trade_plan_draft_batch{batch_no}_strategy{strategy_id}_{ts}_{uid}.json"
    else:
        filename = f"yunfei_trade_plan_draft_batch{batch_no}_{ts}_{uid}.json"
    file_path = os.path.join(output_dir, filename)

    # 原子写文件，避免并发写入导致半文件
    atomic_write_json(file_path, plan)

    print(f"已生成交易计划草稿: {file_path}")

    # 返回文件路径，让调用方收集/合并
    return file_path


def batch_generate_trade_plan_drafts_func(batch_operations, ratio, sample_amount, output_dir="setting"):
    """
    批量生成四个批次的计划 (示例函数)
    """
    for batch_no in range(1, 5):
        operation_str = batch_operations.get(batch_no, "")
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
    batch_generate_trade_plan_drafts_func(batch_ops, ratio, sample_amount)