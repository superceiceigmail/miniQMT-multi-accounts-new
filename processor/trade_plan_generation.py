# processor/trade_plan_generation.py

import os
import json
import math
import logging
from datetime import datetime
from utils.date_utils import get_weekday
from utils.log_utils import emit, LogCollector
from utils.config_loader import load_json_file
# 【新增】导入新的加载工具
from utils.stock_data_loader import load_stock_code_maps

def parse_proportion(value):
    # ... (保持不变)
    if isinstance(value, str):
        value = value.strip()
        if value.endswith("%"):
            return float(value[:-1]) / 100.0
        else:
            return float(value)
    return float(value)

def merge_stocks_by_name(stocks):
    # ... (保持不变)
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
    # ... (保持不变)
    if not code:
        return ""
    code = str(code).strip().upper()
    if code.endswith('.SZ') or code.endswith('.SH'):
        return code
    if code.isdigit():
        if code.startswith('6') or code.startswith('5'):
            return code + '.SH'
        else:
            return code + '.SZ'
    return code


def print_trade_plan(
    config,
    account_asset_info,
    positions,
    # 【修复点】将非可选参数 setting_file_path 提前
    setting_file_path,
    # 可选参数放在后面
    trade_date=None,
    trade_plan_file=None,
    logger=None,
    collect_text=False,
    collector: LogCollector | None = None,
):
    logger = logger or logging.getLogger(__name__)
    collector = collector or (LogCollector() if collect_text else None)

    # 1. 确保 trade_date
    if not trade_date:
        trade_date = datetime.now().strftime('%Y-%m-%d')
        emit(logger, f"trade_date 未传入，使用当前日期: {trade_date}", level="debug", collector=collector)

    # 2. 【修改点】内部加载股票代码
    try:
        # 使用新工具加载，只获取查找函数
        _, get_stock_code, _ = load_stock_code_maps()
        emit(logger, "股票代码字典加载成功 (在 trade_plan_generation 内部)", level="debug", collector=collector)
    except IOError as e:
        emit(logger, f"[错误] {e}", level="error", collector=collector)
        # 抛出异常中断后续计划生成
        raise ValueError(f"无法加载股票代码：{e}") from e

    # 3. 加载交易倾向数据（已有逻辑）
    try:
        setting_data = load_json_file(setting_file_path)
        sell_stocks_info = setting_data["sell_stocks_info"]
        buy_stocks_info = setting_data["buy_stocks_info"]
        emit(logger, f"交易倾向数据已从文件 `{setting_file_path}` 加载", level="debug", collector=collector)
    except Exception as e:
        emit(logger, f"[错误] 无法加载或解析交易倾向文件 `{setting_file_path}`: {e}", level="error",
             collector=collector)
        raise ValueError(f"无法加载交易倾向文件：{e}") from e

    # ==== 新增日期比对逻辑 ====
    plan_date = setting_data.get("plan_date")
    if plan_date:
        if trade_date != plan_date:
            emit(logger, f"[错误] 当前交易日期 {trade_date} 与计划日期 {plan_date} 不一致，已终止程序！", level="error",
                 collector=collector)
            raise ValueError(f"交易日期不一致：当前 {trade_date}，计划 {plan_date}")

    emit(logger, "")
    emit(logger, "===== 原始交易计划 =====", collector=collector)
    emit(logger, f"账户号：{config.get('account_id', '-')}", collector=collector)
    emit(logger, f"操作资金比例（proportion）：{config.get('proportion', '-')}", collector=collector)

    merged_sell = merge_stocks_by_name(sell_stocks_info)
    merged_buy = merge_stocks_by_name(buy_stocks_info)
    sell_names = {x["name"] for x in merged_sell}
    buy_names = {x["name"] for x in merged_buy}
    both = sell_names & buy_names
    if both:
        emit(logger, f"[错误] 以下股票既在买入又在卖出计划：{', '.join(sorted(both))}", level="error", collector=collector)

    emit(logger, "原始卖出计划：", collector=collector)
    for stock in merged_sell:
        emit(logger, f"  - {stock['name']}，ratio={stock['ratio']}", collector=collector)

    emit(logger, "原始买入计划：", collector=collector)
    for stock in merged_buy:
        emit(logger, f"  - {stock['name']}，ratio={stock['ratio']}", collector=collector)

    emit(logger, "")
    emit(logger, "**************************** 实际执行计划 ************************", collector=collector)
    emit(logger, f"交易日期：{trade_date} {get_weekday(trade_date)}", collector=collector)
    emit(logger, f"卖出时间    : {config.get('sell_time', '-')}", collector=collector)
    emit(logger, f"买入时间    : {config.get('buy_time', '-')}", collector=collector)
    emit(logger, f"首次检查    : {config.get('check_time_first', '-')}", collector=collector)
    emit(logger, f"二次检查    : {config.get('check_time_second', '-')}", collector=collector)

    if not account_asset_info:
        print("没有资产数据返回")
        return None  # 或者 return [] 或直接 return，视你的需求而定

    proportion = parse_proportion(config.get('proportion', 1.0))
    total_asset = float(account_asset_info[0])
    cash = float(account_asset_info[1])
    op_asset = proportion * total_asset

    emit(logger, "")
    emit(logger, f"总资产：{total_asset:.2f}，操作资金（proportion×总资产）：{op_asset:.2f}", collector=collector)

    emit(logger, "")
    emit(logger, "************************ 卖出计划 ************************", collector=collector)
    sell_plan = []
    sell_total_money = 0.0

    for stock in merged_sell:
        name = stock["name"]
        ratio = float(stock["ratio"]) / 100

        # 首先尝试使用 draft 中已有的 code（如果存在），否则再用映射函数查找
        provided_code = stock.get("code") if isinstance(stock, dict) else None
        if provided_code:
            emit(logger, f"找到 draft 中的 code：{provided_code} 用于 {name}", level="debug", collector=collector)
            code = provided_code
        else:
            code = get_stock_code(name)
            emit(logger, f"使用映射表查找 code：{code} 用于 {name}", level="debug", collector=collector)

        norm_code = normalize_code(code)

        pos = None
        for p in positions:
            p_code = getattr(p, "stock_code", None) if not isinstance(p, dict) else p.get("stock_code")
            if normalize_code(p_code) == norm_code:
                pos = p
                break

        stock_op_money = op_asset * ratio

        if pos:
            market_value = float(getattr(pos, "market_value", 0) if not isinstance(pos, dict) else pos.get("market_value", 0))
            can_use_volume = int(getattr(pos, "can_use_volume", 0) if not isinstance(pos, dict) else pos.get("can_use_volume", 0))
            avg_price = float(getattr(pos, "avg_price", 0) if not isinstance(pos, dict) else pos.get("avg_price", 0))
            volume = int(getattr(pos, "volume", 0) if not isinstance(pos, dict) else pos.get("volume", 0))
        else:
            market_value = 0.0
            can_use_volume = 0
            avg_price = 0.0
            volume = 0

        actual_lots = 0
        sell_money = 0.0

        if can_use_volume == 0:
            emit(logger, f"[错误] 【{name}】当前没有可用持仓量！", level="error", collector=collector)
        elif market_value == 0:
            emit(logger, f"[错误] 【{name}】当前市值为0，无法计算卖出金额！", level="error", collector=collector)
        else:
            ratio_mv = stock_op_money / market_value if market_value > 0 else 0
            if 0.8 <= ratio_mv <= 1.2:
                actual_lots = (can_use_volume // 100) * 100
                sell_money = market_value
                emit(logger, f"【{name}】计划卖出全部可用持仓量：{actual_lots}", collector=collector)
            elif ratio_mv > 1.2:
                actual_lots = (can_use_volume // 100) * 100
                sell_money = market_value
                emit(logger, f"[警告] 当前操作金额大于市值120%，将卖出全部可用持仓量 {actual_lots}，但仓位可能不足以满足计划", level="warning", collector=collector)
            else:
                if avg_price > 0:
                    lots = math.ceil(stock_op_money / avg_price / 100) * 100
                    actual_lots = min(lots, can_use_volume)
                    sell_money = actual_lots * avg_price
                    emit(logger, f"【{name}】按计划金额卖出：{actual_lots}（按均价 {avg_price:.2f} 计算）", collector=collector)
                else:
                    emit(logger, f"[错误] 【{name}】无法获取均价，无法计算卖出数量", level="error", collector=collector)

            sell_total_money += sell_money

        sell_plan.append({
            "name": name,
            "lots": 99999,
            "actual_lots": actual_lots if can_use_volume else 0,
            "code": norm_code
        })

        emit(
            logger,
            f"  - 名称:{name} 代码:{norm_code or '-'} 操作比例:{ratio:.4f} 当前持仓:{volume} 可用:{can_use_volume} 市值:{market_value:.2f} 计划卖出数量:{actual_lots if can_use_volume else 0}",
            collector=collector
        )

    emit(logger, "")
    emit(logger, "************************ 买入计划 ************************", collector=collector)
    buy_plan = []
    buy_total_money = 0.0

    for stock in merged_buy:
        name = stock["name"]
        ratio = float(stock["ratio"]) / 100

        # 同样优先使用 draft 中已有 code，其次使用映射查找
        provided_code = stock.get("code") if isinstance(stock, dict) else None
        if provided_code:
            emit(logger, f"找到 draft 中的 code：{provided_code} 用于 {name}", level="debug", collector=collector)
            code = provided_code
        else:
            code = get_stock_code(name)
            emit(logger, f"使用映射表查找 code：{code} 用于 {name}", level="debug", collector=collector)

        norm_code = normalize_code(code)
        if not norm_code:
            emit(
                logger,
                f"[错误] 买入计划中【{name}】没有找到有效股票代码，请检查配置！已跳过该买入任务，继续后续交易。",
                level="error",
                collector=collector
            )
            continue  # 跳过该股票，继续后续循环

        op_money = op_asset * ratio
        buy_total_money += op_money
        emit(
            logger,
            f"  - 名称:{name} 代码:{norm_code} 操作比例:{ratio:.4f} 计划买入金额:{op_money:.2f}",
            collector=collector
        )

        buy_plan.append({
            "name": name,
            "amount": int(op_money),
            "code": norm_code
        })

    emit(logger, "")
    emit(logger, "================================ 资金充足性校验 ================================", collector=collector)
    total_available = cash + sell_total_money - buy_total_money
    emit(logger, f"可用资金：{cash:.2f}，预计卖出回笼资金：{sell_total_money:.2f}，预计买入资金：{buy_total_money:.2f}", collector=collector)
    emit(logger, f"可用+卖出-买入后资金余额：{total_available:.2f}", collector=collector)
    if total_available < 0:
        emit(
            logger,
            f"[错误] 资金不足警告：预计可用资金不足以支持整体交易计划，缺口 {abs(total_available):.2f}",
            level="error",
            collector=collector
        )

    # ======================== 日志写入和落盘部分改进 ========================
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

    emit(logger, f"交易计划已保存到 {trade_plan_file}", collector=collector)

    return collector.text if collector else None