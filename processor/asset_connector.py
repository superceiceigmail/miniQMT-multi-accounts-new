from xtquant.xttype import StockAccount
from tabulate import tabulate
import os
import json
import logging
import tempfile

def _atomic_write_json(path, data):
    """
    原子写 JSON：先写入临时文件再替换目标文件，避免中间状态文件。
    """
    dirpath = os.path.dirname(path)
    os.makedirs(dirpath, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dirpath, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # 原子替换
        os.replace(tmp_path, path)
    except Exception:
        # 若失败，确保临时文件被清理
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise

def print_account_asset(trader, account_id):
    """
    打印指定资金账号的账户资产信息，并用方形分块符号可视化各项占比，同时返回金额和占比。
    :param trader: XtQuantTrader 对象，用于查询交易数据。
    :param account_id: 资金账号（字符串）。
    :return: (total_asset, cash, frozen_cash, market_value, percent_cash, percent_frozen, percent_market)
    """
    # 创建资金账号对象
    account = StockAccount(account_id)

    # 查询账户资产
    asset = trader.query_stock_asset(account)

    if not asset:
        logging.warning("没有资产数据返回")
        return None
    else:
        # 兼容属性名（根据返回对象可能不同）
        # 优先使用存在的属性名
        cash = getattr(asset, "cash", None)
        if cash is None:
            cash = getattr(asset, "m_dCash", 0.0)
        frozen_cash = getattr(asset, "frozen_cash", None)
        if frozen_cash is None:
            frozen_cash = getattr(asset, "m_dFrozen", 0.0)
        market_value = getattr(asset, "market_value", None)
        if market_value is None:
            market_value = getattr(asset, "m_dMarketValue", 0.0)
        total_asset = getattr(asset, "total_asset", None)
        if total_asset is None:
            total_asset = getattr(asset, "m_dAsset", cash + frozen_cash + market_value)

        # 格式化与计算函数
        def percent(val, total):
            try:
                return f"{(val / total * 100):.1f}%" if total > 0 else "0.0%"
            except Exception:
                return "0.0%"

        def bar(val, total, length=20):
            try:
                if total <= 0:
                    return "□" * length
                pct = val / total
                blocks = int(pct * length + 0.5)
                blocks = max(0, min(length, blocks))
                return "■" * blocks + "□" * (length - blocks)
            except Exception:
                return "□" * length

        percent_cash = percent(cash, total_asset)
        percent_frozen = percent(frozen_cash, total_asset)
        percent_market = percent(market_value, total_asset)

        bar_cash = bar(cash, total_asset)
        bar_frozen = bar(frozen_cash, total_asset)
        bar_market = bar(market_value, total_asset)

        # 构建资产信息字典
        asset_dict = {
            "account_id": str(getattr(asset, "account_id", account_id)),
            "cash": round(float(cash or 0.0), 2),
            "frozen_cash": round(float(frozen_cash or 0.0), 2),
            "market_value": round(float(market_value or 0.0), 2),
            "total_asset": round(float(total_asset or 0.0), 2),
            "percent_cash": percent_cash,
            "percent_frozen": percent_frozen,
            "percent_market": percent_market,
        }

        # 控制写入模板的期望账号（可通过环境变量覆盖）
        EXPECTED_TEMPLATE_ACCOUNT_ID = os.getenv("EXPECTED_TEMPLATE_ACCOUNT_ID", "8886006288")
        should_save_template = (str(account_id) == EXPECTED_TEMPLATE_ACCOUNT_ID) or (asset_dict["account_id"] == EXPECTED_TEMPLATE_ACCOUNT_ID)

        # 保存核心账户信息到 template_account_info/template_account_asset_info.json（仅针对期望账号）
        try:
            if should_save_template:
                save_dir = "template_account_info"
                save_path = os.path.join(save_dir, "template_account_asset_info.json")
                _atomic_write_json(save_path, asset_dict)
                logging.info(f"已写入本地模板: {save_path} account_id={asset_dict['account_id']} total_asset={asset_dict['total_asset']}")
            else:
                logging.info(f"跳过写入本地模板（非期望账号 {EXPECTED_TEMPLATE_ACCOUNT_ID}），当前 account_id={asset_dict['account_id']}")
        except Exception as e:
            logging.exception(f"写入本地模板失败: {e}")

        # 仅在 should_save_template 为 True 时才写入前端 public 目录（避免任意账号覆盖前端文件）
        try:
            if should_save_template:
                fe_save_dir = r"C:\Users\ceicei\PycharmProjects\miniQMT-frontend\public\template_account_info"
                fe_save_path = os.path.join(fe_save_dir, "template_account_asset_info.json")
                _atomic_write_json(fe_save_path, asset_dict)
                logging.info(f"已写入前端模板: {fe_save_path} account_id={asset_dict['account_id']} total_asset={asset_dict['total_asset']}")
            else:
                logging.info(f"跳过写入前端模板（非期望账号 {EXPECTED_TEMPLATE_ACCOUNT_ID}）")
        except Exception as e:
            logging.exception(f"写入前端模板失败: {e}")

        # 使用 tabulate 格式化资产表
        headers = ["资金账号", "可用金额", "冻结金额", "持仓市值", "总资产"]
        table = [[
            asset_dict["account_id"],
            f"{asset_dict['cash']:.2f}",
            f"{asset_dict['frozen_cash']:.2f}",
            f"{asset_dict['market_value']:.2f}",
            f"{asset_dict['total_asset']:.2f}",
        ]]
        logging.info("                                                                         ")
        logging.info("================================账户资产信息================================")
        logging.info("\n" + tabulate(table, headers, tablefmt="github", stralign="center"))
        logging.info("")  # 空行
        # 各项占比可视化
        percent_table = [
            ["可用金额占比",   bar_cash,   percent_cash],
            ["冻结金额占比",   bar_frozen, percent_frozen],
            ["持仓市值占比",   bar_market, percent_market]
        ]
        logging.info("\n" + tabulate(percent_table, headers=["类型", "占比可视化", "占比"], tablefmt="github", stralign="center"))

        return asset_dict["total_asset"], asset_dict["cash"], asset_dict["frozen_cash"], asset_dict["market_value"], asset_dict["percent_cash"], asset_dict["percent_frozen"], asset_dict["percent_market"]