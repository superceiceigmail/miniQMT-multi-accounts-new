"""
Generate a reconciliation report that splits results into three groups:
 - both: items present in both expected (yunfei) and current positions
 - yunfei_only: items only in expected (current market value treated as 0)
 - positions_only: items only in positions (expected treated as 0)

Usage:
  from gui.reconcile_report import generate_reconcile_report
  report = generate_reconcile_report("8886006288", require_today=False)
"""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from gui.reconcile_ui import (
    load_allocation_list,
    load_parsed_strategies,
    load_account_asset_latest,
    load_account_positions_latest,
    _extract_holdings_from_strategy_item,
    resolve_name_to_code,
)
from yunfei_ball.yunfei_connect_follow import find_strategy_by_id_and_bracket


def _canonical_variants(code: str):
    """Return candidate variants for a code: prefer explicit then .SH/.SZ then base"""
    if not code:
        return []
    code = code.strip()
    if "." in code:
        base, suf = code.split(".", 1)
        suf = suf.upper()
        return [f"{base}.{suf}", f"{base}.SH", f"{base}.SZ", base]
    # heuristics: prefer SH for 5/6/9, SZ for others (including 1)
    base = code
    if base and base[0] in ("5", "6", "9"):
        return [f"{base}.SH", f"{base}.SZ", base]
    else:
        return [f"{base}.SZ", f"{base}.SH", base]


def _find_current_mv_for_code(code_key: str, current_by_code: dict):
    """Try variants and return (market_value Decimal, matched_code_or_None)"""
    if not code_key:
        return Decimal("0"), None
    variants = _canonical_variants(code_key)
    for v in variants:
        if v in current_by_code:
            return current_by_code[v]["market_value"], v
    # last fallback: base without suffix
    base = code_key.split(".")[0]
    if base in current_by_code:
        return current_by_code[base]["market_value"], base
    return Decimal("0"), None


def generate_reconcile_report(account_id: str, require_today: bool = False):
    """
    Returns a dict:
      {
        "account_id": str,
        "total_asset": Decimal,
        "as_of": iso str,
        "both": [rows...],
        "yunfei_only": [rows...],
        "positions_only": [rows...]
      }

    Row fields:
      stock_code (str or None), stock_name, expected_money (Decimal),
      current_market_value (Decimal), diff_money (Decimal), percent_diff (Decimal or None)
    """
    allocation_list = load_allocation_list()
    strategies = load_parsed_strategies()
    asset = load_account_asset_latest(account_id)
    if not asset:
        raise RuntimeError(f"找不到账户资产文件 for {account_id}")
    total_asset = Decimal(str(asset.get("total_asset") or asset.get("m_dAsset") or 0))

    positions = load_account_positions_latest(account_id)
    # build current maps
    current_by_code = {}
    current_by_name = {}
    for p in (positions or []):
        code = (p.get("stock_code") or p.get("code") or "").strip()
        name = p.get("stock_name") or p.get("stock") or ""
        try:
            mv = Decimal(str(p.get("market_value") or 0))
        except Exception:
            mv = Decimal("0")
        if code:
            current_by_code[code] = {"name": name, "market_value": mv, "raw": p}
        if name:
            current_by_name[name] = current_by_name.get(name, Decimal("0")) + mv

    # compute expected_by_code and expected_by_name
    expected_by_code = {}
    expected_by_name = {}

    # optional date filtering
    if require_today:
        today_str = datetime.now().strftime("%Y-%m-%d")
        today_date = datetime.strptime(today_str, "%Y-%m-%d").date()
    else:
        today_date = None

    for cfg in allocation_list:
        try:
            config_pct = float(cfg.get("配置仓位", 0)) / 100.0
        except Exception:
            config_pct = 0.0

        # find matching strategy
        matched = None
        try:
            matched = find_strategy_by_id_and_bracket(cfg, strategies)
        except Exception:
            matched = None

        if not matched:
            # fallback by name endswith
            json_name = (cfg.get("策略名称") or "").strip()
            for s in strategies:
                web_full_name = (s.get("name") or s.get("title") or "").strip()
                if web_full_name.endswith(json_name) and json_name:
                    matched = s
                    break

        if not matched:
            continue

        # date filter if enabled
        if today_date:
            strategy_date_str = matched.get("date") or matched.get("time") or ""
            try:
                strategy_date = datetime.strptime(strategy_date_str.split()[0], "%Y-%m-%d").date() if strategy_date_str else None
            except Exception:
                strategy_date = None
            if not strategy_date or strategy_date < today_date:
                continue

        holdings = _extract_holdings_from_strategy_item(matched)
        for name, pct in holdings:
            if not name or pct is None:
                continue
            try:
                frac = float(pct) / 100.0
            except Exception:
                frac = 0.0
            expected_money = (Decimal(str(frac * config_pct)) * total_asset).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            code = resolve_name_to_code(name)  # may be None or a code string
            if code:
                prev = expected_by_code.get(code, Decimal("0"))
                expected_by_code[code] = (prev + expected_money).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:
                prev = expected_by_name.get(name, Decimal("0"))
                expected_by_name[name] = (prev + expected_money).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Now create grouped lists
    both = []
    yunfei_only = []
    positions_only = []

    # For expected codes, find matching current via variants and list as either both or yunfei_only
    processed_current_codes = set()

    for code, exp_money in expected_by_code.items():
        cur_mv, matched_code = _find_current_mv_for_code(code, current_by_code)
        name = None
        if matched_code:
            name = current_by_code[matched_code]["name"]
            processed_current_codes.add(matched_code)
        else:
            name = current_by_code.get(code, {}).get("name") or code
        diff = (exp_money - (cur_mv or Decimal("0"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        pctdiff = None
        try:
            pctdiff = (diff / exp_money * Decimal("100")).quantize(Decimal("0.1")) if exp_money != 0 else None
        except Exception:
            pctdiff = None
        row = {
            "stock_code": matched_code or code,
            "stock_name": name,
            "expected_money": exp_money,
            "current_market_value": cur_mv or Decimal("0"),
            "diff_money": diff,
            "percent_diff": pctdiff,
        }
        if matched_code:
            both.append(row)
        else:
            yunfei_only.append(row)

    # For expected_by_name entries (no code mapping), try match by name in current positions
    for name, exp_money in expected_by_name.items():
        cur_mv = Decimal(str(current_by_name.get(name, Decimal("0"))))
        diff = (exp_money - cur_mv).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        pctdiff = None
        try:
            pctdiff = (diff / exp_money * Decimal("100")).quantize(Decimal("0.1")) if exp_money != 0 else None
        except Exception:
            pctdiff = None
        row = {
            "stock_code": None,
            "stock_name": name,
            "expected_money": exp_money,
            "current_market_value": cur_mv,
            "diff_money": diff,
            "percent_diff": pctdiff,
        }
        # if name also appears in current_by_name, treat as both
        if name in current_by_name:
            both.append(row)
        else:
            yunfei_only.append(row)

    # Now add positions-only entries (positions with no expected counterpart)
    for code, info in current_by_code.items():
        if code in processed_current_codes:
            continue
        mv = info["market_value"]
        name = info.get("name") or code
        row = {
            "stock_code": code,
            "stock_name": name,
            "expected_money": Decimal("0"),
            "current_market_value": mv,
            "diff_money": (Decimal("0") - mv).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "percent_diff": None,
        }
        positions_only.append(row)

    # sort groups by absolute diff desc for easier inspection
    both.sort(key=lambda r: abs(r["diff_money"]), reverse=True)
    yunfei_only.sort(key=lambda r: abs(r["diff_money"]), reverse=True)
    positions_only.sort(key=lambda r: abs(r["diff_money"]), reverse=True)

    return {
        "account_id": account_id,
        "total_asset": total_asset,
        "as_of": datetime.utcnow().isoformat(),
        "both": both,
        "yunfei_only": yunfei_only,
        "positions_only": positions_only,
    }