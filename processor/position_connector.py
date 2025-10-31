"""
processor/position_connector.py

Helpers to query positions from trader and persist them to:
  account_data/positions/position_{account_id}.json

This version:
 - keeps compatibility with existing output format
 - enriches saved position entries with normalized code and base code fields:
     - stock_code_norm: normalized with suffix (e.g. 159949.SZ)
     - stock_code_base: 6-digit base (e.g. 159949)
 - ensures code->name lookup uses normalized base keys
 - uses atomic write for safety
"""
import os
import json
import math
import logging
import datetime
from typing import Any, Dict, List, Tuple

from xtquant.xttype import StockAccount

def _atomic_write_json(path: str, data: Any):
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

def print_positions(trader, account_id, code_to_name_dict: Dict[str, str], account_asset_info):
    """
    Query positions and print / save them.
    :param trader: xt_trader
    :param account_id: account id string
    :param code_to_name_dict: mapping base_code (no suffix) -> friendly name
    :param account_asset_info: tuple or data used to calculate percent positions
    :return: list of (stock_code, percent_position)
    """
    # extract total asset if present
    total_asset = None
    try:
        if isinstance(account_asset_info, (list, tuple)):
            if len(account_asset_info) >= 1:
                total_asset = float(account_asset_info[0] or 0.0)
        elif isinstance(account_asset_info, dict):
            total_asset = float(account_asset_info.get('total_asset') or account_asset_info.get('m_dAsset') or account_asset_info.get('m_dTotal') or 0.0)
        else:
            total_asset = float(getattr(account_asset_info, 'm_dTotal', 0.0) or getattr(account_asset_info, 'm_dAssets', 0.0) or 0.0)
    except Exception:
        total_asset = None

    account = StockAccount(account_id)

    try:
        positions = trader.query_stock_positions(account) or []
    except Exception as e:
        logging.warning("查询持仓失败: %s", e)
        positions = []

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
        positions_list = []
        for position in positions:
            try:
                # support object-like or dict-like
                stock_code = getattr(position, "stock_code", None) or getattr(position, "m_strStockCode", None) or getattr(position, "stock", None)
                if not stock_code and isinstance(position, dict):
                    stock_code = position.get('stock_code') or position.get('code') or position.get('stock')
                stock_code = str(stock_code).strip() if stock_code else ""
                stock_name = getattr(position, "stock_name", None) or getattr(position, "stock", None) or ""
                if not stock_name and isinstance(position, dict):
                    stock_name = position.get('stock_name') or position.get('stock') or ""
                # numeric fields
                volume = getattr(position, "volume", None) or getattr(position, "m_iHoldQty", None) or (position.get('volume') if isinstance(position, dict) else None) or 0
                can_use_volume = getattr(position, "can_use_volume", None) or getattr(position, "m_iCanUse", None) or getattr(position, "m_nCanUseVolume", None) or (position.get('can_use') if isinstance(position, dict) else None) or 0
                avg_price = getattr(position, "avg_price", None) or getattr(position, "m_dCostPrice", None) or (position.get('avg_price') if isinstance(position, dict) else None)
                market_value = getattr(position, "market_value", None) or getattr(position, "m_dMarketValue", None) or (position.get('market_value') if isinstance(position, dict) else None)
                # normalize numeric types
                try:
                    volume = int(volume or 0)
                except Exception:
                    try:
                        volume = int(float(volume))
                    except Exception:
                        volume = 0
                try:
                    can_use_volume = int(can_use_volume or 0)
                except Exception:
                    try:
                        can_use_volume = int(float(can_use_volume))
                    except Exception:
                        can_use_volume = 0
                try:
                    avg_price = float(avg_price) if avg_price is not None else None
                except Exception:
                    avg_price = None
                try:
                    market_value = float(market_value) if market_value is not None else None
                except Exception:
                    market_value = None

                # percent position calculation
                if total_asset and total_asset > 0 and avg_price is not None and isinstance(avg_price, (int, float)) and avg_price > 0 and volume > 0:
                    percent_position = math.ceil((volume * avg_price / total_asset) * 10000) / 100.0
                else:
                    percent_position = 0.0

                # enriched codes
                stock_code_base = stock_code.split('.')[0] if stock_code else ""
                try:
                    from utils.code_normalizer import normalize_code as _normalize_code
                    stock_code_norm = _normalize_code(stock_code) if stock_code else ""
                except Exception:
                    # fallback: keep as-is
                    stock_code_norm = stock_code

                # used name detection: prefer explicit name, else lookup from code_to_name_dict by base
                display_name = stock_name or code_to_name_dict.get(stock_code_base, '未知股票')

                # build saved entry (keep compatibility)
                entry = {
                    "stock_code": stock_code,
                    "stock_code_norm": stock_code_norm,
                    "stock_code_base": stock_code_base,
                    "stock_name": display_name,
                    "volume": volume,
                    "can_use_volume": can_use_volume,
                    "avg_price": avg_price,
                    "market_value": market_value
                }
                positions_list.append(entry)

                table.append([
                    display_name,
                    stock_code,
                    volume,
                    can_use_volume,
                    f"{avg_price:.2f}" if avg_price is not None else "nan",
                    f"{market_value:.2f}" if market_value is not None and market_value is not None else "0.00",
                    f"{percent_position:.2f}"
                ])
                result.append((stock_code, percent_position))
            except Exception as e:
                logging.exception("处理单个持仓项失败: %s", e)
                continue

        # persist to account_data/positions/position_{account_id}.json
        try:
            save_dir = os.path.join("account_data", "positions")
            os.makedirs(save_dir, exist_ok=True)
            save_path = os.path.join(save_dir, f"position_{str(account_id)}.json")
            data_to_save = {
                "last_update": datetime.datetime.now().isoformat(),
                "positions": positions_list
            }
            _atomic_write_json(save_path, data_to_save)
            logging.info("已写入账户持仓文件: %s account_id=%s positions_count=%d", save_path, str(account_id), len(positions_list))
        except Exception as e:
            logging.exception("写入账户持仓文件失败: %s", e)

    # optional: print table to console (keeps previous behaviour)
    try:
        from tabulate import tabulate
        logging.info("\n" + tabulate(table, headers=headers))
    except Exception:
        pass

    return result