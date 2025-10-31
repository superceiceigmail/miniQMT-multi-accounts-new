"""
processor/trade_plan_generation.py

生成最终交易计划（final trade plan）的模块。
此版本统一使用 utils.code_normalizer.normalize_code 来处理代码后缀，
并且在根据账户持仓做可售数量判断时使用 match_available_code_in_dict 做变体匹配，
以避免 .SH/.SZ 后缀不一致导致无法匹配的问题。
"""

import os
import json
import math
import logging
from typing import Dict, Any, List, Optional

from utils.code_normalizer import normalize_code, match_available_code_in_dict, canonical_variants

logger = logging.getLogger(__name__)

def emit(logger_, msg: str, level: str = "info", collector: Optional[list] = None):
    if level == "error":
        logger_.error(msg)
    elif level == "warning":
        logger_.warning(msg)
    else:
        logger_.info(msg)
    if collector is not None:
        collector.append(msg)

def _load_json(path: str) -> Any:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def print_trade_plan(
    config: Dict[str, Any],
    account_asset_info: Any,
    positions: Any,
    trade_date: str,
    setting_file_path: str,
    trade_plan_file: str,
    logger_: Optional[logging.Logger] = None,
    collector: Optional[list] = None
):
    """
    Generate the final trade plan JSON file.

    Parameters expected:
      - config: account config dict (may contain account_id, etc.)
      - account_asset_info: account asset tuple or dict (used for total asset)
      - positions: list/dict of current positions (from positions_to_dict)
      - trade_date: 'YYYY-MM-DD'
      - setting_file_path: path to draft/setting json describing desired operations
      - trade_plan_file: output path for final trade plan
    """
    lg = logger_ or logger

    try:
        draft = _load_json(setting_file_path)
    except Exception as e:
        emit(lg, f"读取草稿文件失败: {setting_file_path} => {e}", level="error", collector=collector)
        raise

    # Normalize input positions into a dict keyed by normalized code variants
    position_available: Dict[str, int] = {}
    position_market_values: Dict[str, float] = {}
    position_raw_map: Dict[str, dict] = {}

    # positions may be a list of dicts or a dict mapping codes->info
    if isinstance(positions, dict):
        iter_items = positions.items()
    elif isinstance(positions, list):
        iter_items = []
        for p in positions:
            # accept different field names
            code = p.get('stock_code') or p.get('code') or p.get('stock') or p.get('stock_code', '')
            iter_items.append((code, p))
    else:
        iter_items = []

    for code_key, info in iter_items:
        if not code_key:
            continue
        norm_key = normalize_code(code_key)
        # try to read available volume from a few possible fields
        avail = None
        if isinstance(info, dict):
            avail = info.get('m_nCanUseVolume') or info.get('can_use') or info.get('qty_available') or info.get('m_iCanUse') or info.get('m_iHoldQty') or info.get('m_dQty') or info.get('qty')
            mv = info.get('m_dFVal') or info.get('m_dMarketValue') or info.get('mkt_value') or info.get('market_value') or info.get('m_fVal') or info.get('m_dVal')
            try:
                avail = int(avail) if avail is not None else 0
            except Exception:
                try:
                    avail = int(float(avail))
                except Exception:
                    avail = 0
            try:
                mv = float(mv) if mv is not None else 0.0
            except Exception:
                mv = 0.0
        else:
            avail = 0
            mv = 0.0

        position_available[norm_key] = int(avail or 0)
        position_market_values[norm_key] = float(mv or 0.0)
        position_raw_map[norm_key] = info or {}

    # Total asset extraction
    total_asset = None
    try:
        # account_asset_info might be xt trader object or tuple/dict
        if isinstance(account_asset_info, (list, tuple)):
            # earlier code sometimes used tuple with total_asset at index 0
            if len(account_asset_info) >= 1:
                total_asset = float(account_asset_info[0] or 0.0)
        elif isinstance(account_asset_info, dict):
            total_asset = float(account_asset_info.get('total_asset') or account_asset_info.get('m_dAsset') or account_asset_info.get('m_dTotal') or 0.0)
        else:
            # try attribute access
            total_asset = float(getattr(account_asset_info, 'm_dTotal', 0.0) or getattr(account_asset_info, 'm_dAssets', 0.0) or 0.0)
    except Exception:
        total_asset = None

    emit(lg, "===== 原始交易计划草稿 =====", collector=collector)
    emit(lg, json.dumps(draft, ensure_ascii=False, indent=2), collector=collector)

    # The draft format expected (from generate_trade_plan_draft) typically contains:
    # {
    #   "sell": [ { "name": "...", "code": "159949", "ratio": "1.58", "sample_amount": 123.0 }, ... ],
    #   "buy":  [ { "name": "...", "code": "511880.SH", "amount": 1000.0 }, ... ],
    #   ...
    # }
    sell_plan = []
    buy_plan = []

    # Helper to read numeric safely
    def _to_float(x):
        try:
            return float(x)
        except Exception:
            return 0.0

    # Build sell plan: try to compute actual_lots based on available quantity and desired ratio/amount
    for s in draft.get('sell', []):
        name = s.get('name') or s.get('stock') or ''
        raw_code = s.get('code') or s.get('stock_code') or ''
        norm_code = normalize_code(raw_code)
        ratio = _to_float(s.get('ratio') or s.get('pct') or s.get('weight') or 0.0)
        # desired lots may be represented in draft as 'lots' or a placeholder
        desired_lots = int(s.get('lots') or s.get('plan_lots') or 99999)
        market_value = float(s.get('market_value') or 0.0)

        # Attempt to find available volume: first by normalized code, then by variants
        matched_key = match_available_code_in_dict(norm_code, position_available)
        can_use_volume = position_available.get(matched_key, 0) if matched_key else 0

        actual_lots = 0
        board_lot = int(s.get('board_lot') or 100)

        if can_use_volume == 0:
            emit(lg, f"[错误] 【{name}】当前没有可用持仓量！", level="error", collector=collector)
        elif market_value == 0 and total_asset:
            # if market_value absent, but we have total_asset & ratio we might estimate
            emit(lg, f"[警告] 【{name}】市值信息缺失，使用可用量估算。", level="warning", collector=collector)
            actual_lots = (can_use_volume // board_lot) * board_lot
        else:
            # Compute planned money for this sell if provided (sample_amount or ratio × total_asset)
            stock_op_money = _to_float(s.get('sample_amount') or 0.0)
            if not stock_op_money and total_asset and ratio:
                stock_op_money = float(total_asset) * (ratio / 1.0) if ratio < 1 else float(total_asset) * (ratio / 100.0)
            if market_value > 0:
                ratio_mv = stock_op_money / market_value if market_value > 0 else 0
                # If planned amount near market value then sell all available
                if 0.8 <= ratio_mv <= 1.2:
                    actual_lots = (can_use_volume // board_lot) * board_lot
                else:
                    # Otherwise, compute how many shares correspond to stock_op_money at current price if provided
                    price = None
                    if market_value and s.get('volume'):
                        # if market_value corresponds to volume × price we can estimate price = market_value / holding_volume
                        try:
                            holding_volume = int(s.get('holding_volume') or position_raw_map.get(matched_key, {}).get('m_iHoldQty') or 0)
                            if holding_volume:
                                price = market_value / holding_volume
                        except Exception:
                            price = None
                    if price and stock_op_money:
                        qty = int(stock_op_money // price)
                        actual_lots = (qty // board_lot) * board_lot
                    else:
                        # fallback: sell nothing (we don't guess)
                        actual_lots = 0

        sell_plan.append({
            "name": name,
            "code": norm_code,
            "lots": desired_lots,
            "actual_lots": int(actual_lots or 0)
        })

        emit(lg, f"  - 名称:{name} 代码:{norm_code or '-'} 操作比例:{ratio:.4f} 当前持仓:{position_raw_map.get(matched_key,{}).get('m_iHoldQty') or 0} "
                  f"可用:{can_use_volume} 市值:{position_market_values.get(matched_key,0.0):.2f} 计划卖出数量:{int(actual_lots or 0)}", collector=collector)

    emit(lg, "", collector=collector)
    emit(lg, "************************ 买入计划 ************************", collector=collector)

    # Build buy plan: draft buy entries may contain amount or ratio
    for b in draft.get('buy', []):
        name = b.get('name') or b.get('stock') or ''
        raw_code = b.get('code') or b.get('stock_code') or ''
        norm_code = normalize_code(raw_code)
        amount = _to_float(b.get('amount') or b.get('sample_amount') or b.get('target_amount') or 0.0)
        buy_plan.append({
            "name": name,
            "code": norm_code,
            "amount": int(amount)
        })
        emit(lg, f"  - 名称:{name} 代码:{norm_code or '-'} 计划买入金额:{amount:.2f}", collector=collector)

    # Basic funds sufficiency check (very small sanity check)
    available_cash = None
    try:
        if isinstance(account_asset_info, dict):
            available_cash = float(account_asset_info.get('available_cash') or account_asset_info.get('m_dCash') or 0.0)
        else:
            available_cash = float(getattr(account_asset_info, 'm_dCash', 0.0) or 0.0)
    except Exception:
        available_cash = 0.0

    total_buy_amount = sum([float(x.get('amount', 0.0)) for x in buy_plan])
    emit(lg, f"可用资金：{available_cash:.2f}，预计买入资金：{total_buy_amount:.2f}", collector=collector)

    final_plan = {
        "meta": {
            "generated_at": trade_date,
            "total_asset": total_asset,
            "available_cash": available_cash
        },
        "sell": sell_plan,
        "buy": buy_plan
    }

    # Persist final trade plan
    try:
        os.makedirs(os.path.dirname(trade_plan_file), exist_ok=True)
        with open(trade_plan_file, 'w', encoding='utf-8') as f:
            json.dump(final_plan, f, ensure_ascii=False, indent=2)
        emit(lg, f"交易计划已保存到 {trade_plan_file}", collector=collector)
    except Exception as e:
        emit(lg, f"保存交易计划失败: {e}", level="error", collector=collector)
        raise

    return final_plan