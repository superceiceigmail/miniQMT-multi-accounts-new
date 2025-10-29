from xtquant.xttype import StockAccount
import math
from tabulate import tabulate
import os
import json
import logging
import datetime

def _atomic_write_json(path, data):
    """
    原子写 JSON：先写入临时文件再替换目标文件，避免中间状态文件。
    （与 asset_connector.py 中的实现保持一致，独立定义以避免循环依赖）
    """
    import tempfile
    dirpath = os.path.dirname(path)
    os.makedirs(dirpath, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dirpath, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise

def print_positions(trader, account_id, code_to_name_dict, account_asset_info):
    """
    打印指定资金账号的当前持仓情况，并展示每只股票的仓位占比，使用 tabulate 库美化表格。
    额外：将持仓信息以 JSON 文件保存到 account_data/positions/position_{account_id}.json，
    文件中包含 last_update 字段，方便后续读取每个账号的最新持仓信息。
    :param trader: XtQuantTrader 对象，用于查询交易数据。
    :param account_id: 资金账号（字符串）。
    :param code_to_name_dict: 股票代码到名称的映射字典。
    :param account_asset_info: 账户资产信息元组（含total_asset在第一个位置）
    :return: List of position objects (原始返回) ；同时也返回 result (stock_code, percent_position) 列表
    """

    if not account_asset_info:
        print("没有资产数据返回")
        return None  # 或者 return [] 取决于你的需求

    # 解包total_asset
    total_asset = account_asset_info[0]

    # 创建资金账号对象
    account = StockAccount(account_id)

    # 查询持仓数据
    positions = trader.query_stock_positions(account)

    result = []
    table = []
    headers = ["股票名称", "股票代码", "持仓量", "可用量", "成本价", "市值", "仓位占比"]

    def nan_to_none(x):
        if isinstance(x, float):
            if math.isnan(x) or math.isinf(x):
                return None
        return x

    if not positions:
        logging.warning("没有持仓数据返回")
    else:
        for position in positions:
            stock_code = getattr(position, "stock_code", "")
            stock_name = code_to_name_dict.get(stock_code.split('.')[0], '未知股票')
            volume = getattr(position, "volume", 0)
            can_use_volume = getattr(position, "can_use_volume", 0)
            avg_price = getattr(position, "avg_price", None)
            market_value = getattr(position, "market_value", None)

            # 仓位占比公式：可用量 * 成本价 / 总资产
            if total_asset and total_asset > 0 and avg_price is not None and isinstance(avg_price, (int, float)) and avg_price > 0 and can_use_volume > 0:
                percent_position = math.ceil((can_use_volume * avg_price / total_asset) * 10000) / 100.0
            else:
                percent_position = 0.0

            table.append([
                stock_name,
                stock_code,
                volume,
                can_use_volume,
                f"{avg_price:.2f}" if avg_price is not None and isinstance(avg_price, (int, float)) and not (math.isnan(avg_price) or math.isinf(avg_price)) else "nan",
                f"{market_value:.2f}" if market_value is not None else "0.00",
                f"{percent_position:.2f}"
            ])

            result.append((stock_code, percent_position))

        # 将每个账号的持仓保存到 account_data/positions/position_{account_id}.json
        try:
            save_dir = os.path.join("account_data", "positions")
            os.makedirs(save_dir, exist_ok=True)
            save_path = os.path.join(save_dir, f"position_{account_id}.json")
            positions_list = []
            for p in positions:
                avg_price = nan_to_none(getattr(p, "avg_price", None))
                market_value = nan_to_none(getattr(p, "market_value", None))
                positions_list.append({
                    "stock_code": getattr(p, "stock_code", ""),
                    "stock_name": code_to_name_dict.get(getattr(p, "stock_code", "").split('.')[0], '未知股票'),
                    "volume": getattr(p, "volume", 0),
                    "can_use_volume": getattr(p, "can_use_volume", 0),
                    "avg_price": avg_price,
                    "market_value": market_value
                })
            data_to_save = {
                "last_update": datetime.datetime.now().isoformat(),
                "positions": positions_list
            }
            _atomic_write_json(save_path, data_to_save)
            logging.info(f"已写入账户持仓文件: {save_path} account_id={account_id} positions_count={len(positions_list)}")
        except Exception as e:
            logging.exception(f"写入账户持仓文件失败: {e}")

        # 兼容旧逻辑：如果是模板账号，仍然写入 template_account_info 和前端目录（保留原有行为）
        try:
            if account_id == "8886006288":
                save_dir = "template_account_info"
                save_path = os.path.join(save_dir, "template_account_position_info.json")
                os.makedirs(save_dir, exist_ok=True)
                data_to_save_template = {
                    "last_update": datetime.datetime.now().isoformat(),
                    "positions": positions_list
                }
                with open(save_path, "w", encoding="utf-8") as f:
                    json.dump(data_to_save_template, f, ensure_ascii=False, indent=2)
                # 额外保存到前端 public 目录
                fe_save_dir = r"C:\Users\ceicei\PycharmProjects\miniQMT-frontend\public\template_account_info"
                fe_save_path = os.path.join(fe_save_dir, "template_account_position_info.json")
                os.makedirs(fe_save_dir, exist_ok=True)
                with open(fe_save_path, "w", encoding="utf-8") as f:
                    json.dump(data_to_save_template, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.exception(f"写入 template/前端 持仓文件失败: {e}")

        logging.info("                                                                         ")
        logging.info("================================账户持仓信息================================")
        logging.info("\n" + tabulate(table, headers, tablefmt="github", stralign="center"))

    return positions