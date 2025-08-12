import os
import json
import math
from utils.date_utils import get_weekday

def parse_proportion(value):
    """将百分数或小数转成浮点比例（如0.8）"""
    if isinstance(value, str):
        value = value.strip()
        if value.endswith("%"):
            return float(value[:-1]) / 100.0
        else:
            return float(value)
    return float(value)

def merge_stocks_by_name(stocks):
    """合并同名股票的 ratio，并保留其它字段（如有）。"""
    merged = {}
    for stock in stocks:
        name = stock["name"]
        ratio = float(stock.get("ratio", 0))
        if name in merged:
            merged[name]["ratio"] += ratio
        else:
            merged[name] = stock.copy()
            merged[name]["ratio"] = ratio
    return list(merged.values())

def normalize_code(code):
    """
    统一股票代码格式，便于对比。
    规则：全大写、无空格、必须有 .SZ/.SH 后缀（如无则自动判断补齐）。
    """
    if not code:
        return ""
    code = str(code).strip().upper()
    if code.endswith('.SZ') or code.endswith('.SH'):
        return code
    if code.isdigit():
        # 常见规则：6/5开头为沪市，其他为深市
        if code.startswith('6') or code.startswith('5'):
            return code + '.SH'
        else:
            return code + '.SZ'
    return code

def print_trade_plan(
    config,
    account_asset_info,
    positions,
    stock_code_dict,
    trade_date,
    sell_stocks_info,
    buy_stocks_info,
    trade_plan_file=None
):
    print("")
    print("\n===== 原始交易计划 =====")

    print(f"账户号：{config.get('account_id', '-')}")
    print(f"操作资金比例（proportion）：{config.get('proportion', '-')}")

    # 步骤1：合并重复股票
    merged_sell = merge_stocks_by_name(sell_stocks_info)
    merged_buy = merge_stocks_by_name(buy_stocks_info)
    sell_names = set([x["name"] for x in merged_sell])
    buy_names = set([x["name"] for x in merged_buy])
    both = sell_names & buy_names
    if both:
        print(f"【严重错误】：以下股票既在买入又在卖出计划：{', '.join(both)}")

    # 步骤2：打印原始卖出计划
    print("原始卖出计划：")
    for stock in merged_sell:
        print(f"  - {stock['name']}，ratio={stock['ratio']}")

    print("\n原始买入计划：")
    for stock in merged_buy:
        print(f"  - {stock['name']}，ratio={stock['ratio']}")

    print("")
    print("================================ 实际执行计划 ================================")

    # 打印交易日期和时间
    print(f"交易日期：{trade_date} {get_weekday(trade_date)}")
    print(f"卖出时间    : {config.get('sell_time', '-')}")
    print(f"买入时间    : {config.get('buy_time', '-')}")
    print(f"首次检查    : {config.get('check_time_first', '-')}")
    print(f"二次检查    : {config.get('check_time_second', '-')}")

    # 步骤3：卖出计划逻辑

    proportion = parse_proportion(config.get('proportion', 1.0))
    total_asset = float(account_asset_info[0])  # 0: total_asset
    cash = float(account_asset_info[1])         # 1: cash
    op_asset = proportion * total_asset
    print("")
    print(f"总资产：{total_asset}，操作资金（proportion×总资产）：{op_asset}")

    print("\n===== 卖出计划 =====")
    sell_plan = []
    sell_total_money = 0.0
    for stock in merged_sell:
        name = stock["name"]
        # ratio 以百分数数字部分表示，如1.4表示1.4%，这里需除以100
        ratio = float(stock["ratio"]) / 100
        code = stock_code_dict.get(name)
        norm_code = normalize_code(code)
        # 找到持仓
        pos = None
        for p in positions:
            if normalize_code(p.stock_code) == norm_code:
                pos = p
                break
        # 操作金额
        stock_op_money = op_asset * ratio
        # 市值、可用、价格
        if pos:
            market_value = float(getattr(pos, "market_value", 0))
            can_use_volume = int(getattr(pos, "can_use_volume", 0))
            avg_price = float(getattr(pos, "avg_price", 0))
            volume = int(getattr(pos, "volume", 0))
        else:
            market_value = 0
            can_use_volume = 0
            avg_price = 0
            volume = 0
        actual_lots = 0
        # 先检查持仓
        if can_use_volume == 0:
            print(f"【严重错误】【严重错误】 严重错误：【{name}】当前没有可用持仓量！")
        elif market_value == 0:
            print(f"【严重错误】【严重错误】 严重错误：【{name}】当前市值为0，无法计算卖出金额！")
        else:
            # 判断操作金额和市值关系
            ratio_mv = stock_op_money / market_value if market_value > 0 else 0
            if 0.8 <= ratio_mv <= 1.2:
                # 近似等于市值，全部卖出
                actual_lots = can_use_volume // 100 * 100
                sell_money = market_value
                print(f"【{name}】计划卖出全部可用持仓量：{actual_lots}")
            elif ratio_mv > 1.2:
                actual_lots = can_use_volume // 100 * 100
                sell_money = market_value
                print(f"[警告] 当前操作金额大于市值120%，卖掉全部可用持仓量{actual_lots}，但警告：仓位不足，难以支持卖出")
            else:
                # 按金额算手数
                if avg_price > 0:
                    lots = math.ceil(stock_op_money / avg_price / 100) * 100
                    actual_lots = min(lots, can_use_volume)
                    sell_money = actual_lots * avg_price
                    print(f"【{name}】按计划金额卖出：{actual_lots}（按均价{avg_price:.2f}算）")
                else:
                    actual_lots = 0
                    sell_money = 0
                    print(f"【严重错误】【严重错误】 无法获取均价，无法计算卖出数量")
            sell_total_money += sell_money
        # 统计
        sell_plan.append({
            "name": name,
            "lots": 99999,
            "actual_lots": actual_lots if can_use_volume else 0,
            "code": norm_code   # 这里保存带后缀的股票代码
        })
        print(
            f"  - 名称:{name} 代码:{norm_code} 操作比例:{ratio:.4f} 当前持仓:{volume} 可用:{can_use_volume} 市值:{market_value} "
            f"计划卖出数量:{actual_lots if can_use_volume else 0}")

    # 步骤4：买入计划逻辑
    print("\n===== 买入计划 =====")
    buy_plan = []
    buy_total_money = 0.0
    for stock in merged_buy:
        name = stock["name"]
        ratio = float(stock["ratio"]) / 100
        code = stock_code_dict.get(name)
        norm_code = normalize_code(code)
        if not norm_code:  # 这里新增
            print(f"【严重错误】【严重错误】：买入计划中【{name}】没有找到有效股票代码，请检查stock_code_dict或输入配置！")
            raise ValueError(f"买入计划中【{name}】没有找到有效股票代码，程序终止。")
        op_money = op_asset * ratio
        buy_total_money += op_money
        print(
            f"  - 名称:{name} 代码:{norm_code} 操作比例:{ratio:.4f} 计划买入金额:{op_money:.2f}")
        buy_plan.append({
            "name": name,
            "amount": int(op_money),
            "code": norm_code  # 这里保存带后缀的股票代码
        })

    # 步骤5：资金充足性校验
    print("")
    print("================================ 资金充足性校验 ================================")
    total_available = cash + sell_total_money - buy_total_money
    print(f"可用资金：{cash:.2f}，预计卖出回笼资金：{sell_total_money:.2f}，预计买入资金：{buy_total_money:.2f}")
    print(f"可用+卖出-买入后资金余额：{total_available:.2f}")
    if total_available < 0:
        print(f"【严重错误】【严重错误】 资金不足警告：预计可用资金不足以支持整体交易计划，缺口 {abs(total_available):.2f}")

    # 步骤6：保存计划
    if not trade_plan_file:
        folder = "zz_account_tradplan"
        filename = f"trade_plan_{config.get('account_id', '-')}_{trade_date.replace('-', '')}.json"
        os.makedirs(folder, exist_ok=True)
        trade_plan_file = os.path.join(folder, filename)
    else:
        folder = os.path.dirname(trade_plan_file)
        if folder:
            os.makedirs(folder, exist_ok=True)
    with open(trade_plan_file, 'w', encoding='utf-8') as f:
        json.dump({"sell": sell_plan, "buy": buy_plan}, f, ensure_ascii=False, indent=4)
    print(f"交易计划已保存到 {trade_plan_file}")