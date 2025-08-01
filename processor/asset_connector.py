from xtquant.xttype import StockAccount
from tabulate import tabulate
import os
import json

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
        print("没有资产数据返回")
        return None
    else:
        cash = asset.cash
        frozen_cash = asset.frozen_cash
        market_value = asset.market_value
        total_asset = asset.total_asset

        def percent(val, total):
            return f"{(val / total * 100):.1f}%" if total > 0 else "0.0%"

        def bar(val, total, length=20):
            if total <= 0:
                return "□" * length
            pct = val / total
            blocks = int(pct * length + 0.5)
            return "■" * blocks + "□" * (length - blocks)

        percent_cash = percent(cash, total_asset)
        percent_frozen = percent(frozen_cash, total_asset)
        percent_market = percent(market_value, total_asset)

        bar_cash = bar(cash, total_asset)
        bar_frozen = bar(frozen_cash, total_asset)
        bar_market = bar(market_value, total_asset)

        # 保存核心账户信息到 template_account_info/template_account_asset_info.json
        if account_id == "8886006288":
            save_dir = "template_account_info"
            save_path = os.path.join(save_dir, "template_account_asset_info.json")
            os.makedirs(save_dir, exist_ok=True)
            asset_dict = {
                "account_id": asset.account_id,
                "cash": cash,
                "frozen_cash": frozen_cash,
                "market_value": market_value,
                "total_asset": total_asset,
                "percent_cash": percent_cash,
                "percent_frozen": percent_frozen,
                "percent_market": percent_market,
            }
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(asset_dict, f, ensure_ascii=False, indent=2)

        # 使用 tabulate 格式化资产表
        headers = ["资金账号", "可用金额", "冻结金额", "持仓市值", "总资产"]
        table = [[
            asset.account_id,
            f"{cash:.2f}",
            f"{frozen_cash:.2f}",
            f"{market_value:.2f}",
            f"{total_asset:.2f}",
        ]]
        print("                                                                         ")
        print("================================账户资产信息================================")
        print(tabulate(table, headers, tablefmt="github", stralign="center"))
        print()
        # 各项占比可视化
        percent_table = [
            ["可用金额占比",   bar_cash,   percent_cash],
            ["冻结金额占比",   bar_frozen, percent_frozen],
            ["持仓市值占比",   bar_market, percent_market]
        ]
        print(tabulate(percent_table, headers=["类型", "占比可视化", "占比"], tablefmt="github", stralign="center"))

        return total_asset, cash, frozen_cash, market_value, percent_cash, percent_frozen, percent_market