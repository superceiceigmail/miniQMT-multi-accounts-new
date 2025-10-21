# utils/asset_helpers.py
# 将各种 xtquant 返回的持仓/账户对象转换成 dict/list/tuple 结构，便于下游以下标或 key 方式访问

from typing import Any, Dict, List, Tuple


def positions_to_dict(pos: Any) -> List[Dict]:
    """
    将不同表示的持仓/账户对象宽松转换为 list[dict]。
    - 如果已经是 dict：返回 [dict]（保持列表化）
    - 如果已经是 list/tuple（可迭代）：尝试将每个元素转换成 dict 并返回 list
    - 如果对象提供 to_dict / as_dict / toJSON 等方法，优先使用（并确保返回 list 或 dict）
    - 否则尝试收集非私有、非可调用属性作为键值返回为 dict
    返回结果始终是 list（下游可直接 for p in positions）
    """
    if pos is None:
        return []

    # 如果已经是 list/tuple，处理每个元素
    try:
        from collections.abc import Iterable
        if isinstance(pos, (list, tuple)):
            result = []
            for item in pos:
                if isinstance(item, dict):
                    result.append(item)
                else:
                    d = {}
                    for name in dir(item):
                        if name.startswith("_"):
                            continue
                        try:
                            val = getattr(item, name)
                        except Exception:
                            continue
                        if callable(val):
                            continue
                        d[name] = val
                    result.append(d)
            return result
    except Exception:
        pass

    # 如果对象本身是 dict（单个 dict），返回 [dict]
    if isinstance(pos, dict):
        return [pos]

    # 如果对象提供 to_dict/as_dict 等，优先尝试转换（若返回 list/dict，标准化为 list）
    for method in ("to_dict", "as_dict", "toJSON", "to_json"):
        if hasattr(pos, method) and callable(getattr(pos, method)):
            try:
                converted = getattr(pos, method)()
                if isinstance(converted, list):
                    return converted
                if isinstance(converted, dict):
                    return [converted]
            except Exception:
                # 忽略转换异常，继续尝试其他方式
                pass

    # 最后退回到读取公共属性，把整个对象变成单个 dict 返回在 list 中
    d = {}
    for name in dir(pos):
        if name.startswith("_"):
            continue
        try:
            val = getattr(pos, name)
        except Exception:
            continue
        if callable(val):
            continue
        d[name] = val
    return [d]


def account_asset_to_tuple(asset: Any) -> Tuple[float, float, float, float, str, str, str]:
    """
    将 xtquant 的账户资产对象（XtAsset 或类似）转换为 processor/asset_connector.print_account_asset 返回的元组格式：
      (total_asset, cash, frozen_cash, market_value, percent_cash, percent_frozen, percent_market)
    percent_* 是字符串带 % 符号，与 print_account_asset 输出一致。
    如果传入已经是 tuple/list，则尽量原样返回（做基本校验）。
    """
    # 如果已经是 tuple/list 且长度 >= 4，直接尝试使用（尽量保持兼容）
    if isinstance(asset, (list, tuple)) and len(asset) >= 4:
        total_asset = float(asset[0])
        cash = float(asset[1])
        frozen_cash = float(asset[2])
        market_value = float(asset[3])
        def pct(v, tot):
            try:
                return f"{(v / tot * 100):.1f}%" if tot > 0 else "0.0%"
            except Exception:
                return "0.0%"
        return (
            total_asset,
            cash,
            frozen_cash,
            market_value,
            pct(cash, total_asset),
            pct(frozen_cash, total_asset),
            pct(market_value, total_asset)
        )

    # 常见属性名兼容
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
        # 某些实现没有 total 字段，按 cash + frozen + market_value 退回计算
        try:
            total_asset = float(getattr(asset, "m_dAsset", cash + frozen_cash + market_value))
        except Exception:
            total_asset = float((cash or 0.0) + (frozen_cash or 0.0) + (market_value or 0.0))

    try:
        total_asset = float(total_asset)
    except Exception:
        total_asset = 0.0
    try:
        cash = float(cash or 0.0)
    except Exception:
        cash = 0.0
    try:
        frozen_cash = float(frozen_cash or 0.0)
    except Exception:
        frozen_cash = 0.0
    try:
        market_value = float(market_value or 0.0)
    except Exception:
        market_value = 0.0

    def pct_str(v, tot):
        try:
            return f"{(v / tot * 100):.1f}%" if tot > 0 else "0.0%"
        except Exception:
            return "0.0%"

    percent_cash = pct_str(cash, total_asset)
    percent_frozen = pct_str(frozen_cash, total_asset)
    percent_market = pct_str(market_value, total_asset)

    return (total_asset, cash, frozen_cash, market_value, percent_cash, percent_frozen, percent_market)