# debug_reconcile_values.py
# 调试 reconcile_for_account 的中间数据，打印 allocation 匹配、是否被日期过滤、以及 per-stock expected_money 聚合结果
import os, json
from decimal import Decimal
from pprint import pprint

# import helpers from project
from gui.reconcile_ui import load_allocation_list, load_parsed_strategies, load_account_asset_latest, load_account_positions_latest, _extract_holdings_from_strategy_item, resolve_name_to_code
# try to import reconcile_for_account and inspect signature
try:
    from gui.reconcile_ui import reconcile_for_account
    import inspect
    print("reconcile_for_account signature:", inspect.signature(reconcile_for_account))
except Exception:
    reconcile_for_account = None
    print("reconcile_for_account not importable or missing.")

# load data
allocs = load_allocation_list()
strats = load_parsed_strategies()
asset = load_account_asset_latest("8886006288")
positions = load_account_positions_latest("8886006288")

print(">>> allocation entries:", len(allocs))
print(">>> parsed strategies count:", len(strats))
print(">>> asset total_asset:", asset.get('total_asset') if asset else None)
print(">>> positions count:", len(positions))
print()

# helper: try matching same logic as reconcile_for_account (but show details)
def find_match(cfg, strategies):
    from yunfei_ball.yunfei_connect_follow import find_strategy_by_id_and_bracket
    try:
        m = find_strategy_by_id_and_bracket(cfg, strategies)
    except Exception:
        m = None
    if m:
        return m, "find_strategy_by_id_and_bracket"
    # id-prefix heuristic
    sid = str(cfg.get('策略ID') or cfg.get('策略Id') or cfg.get('id') or '')
    if sid:
        prefix = sid[:-1] if len(sid)>1 else sid
        import re
        for s in strategies:
            web_full_name = (s.get('name') or s.get('title') or '')
            mm = re.search(r"L?(\d+):", web_full_name)
            if mm and mm.group(1).startswith(prefix):
                return s, "id_prefix"
    # name.endsWith heuristic
    target = (cfg.get('策略名称') or cfg.get('name') or '').strip()
    if target:
        for s in strategies:
            web_full_name = (s.get('name') or s.get('title') or '').strip()
            if web_full_name.endswith(target) and target:
                return s, "name_endswith"
    return None, None

# iterate allocations and compute per-allocation expected money
total_asset = Decimal(str(asset.get('total_asset') or asset.get('m_dAsset') or 0)) if asset else Decimal('0')
expected_by_code = {}
expected_by_name = {}
skipped_by_date = []
included_allocs = []

from datetime import datetime

for i, cfg in enumerate(allocs, 1):
    name = cfg.get('策略名称')
    sid = cfg.get('策略ID')
    cfg_pct = cfg.get('配置仓位', 0)
    try:
        cfg_frac = float(cfg_pct) / 100.0
    except Exception:
        cfg_frac = 0.0
    matched, how = find_match(cfg, strats)
    print(f"[{i:02d}] alloc name={name!r} id={sid!r} cfg_pct={cfg_pct} matched_by={how} matched_exists={bool(matched)}")
    if not matched:
        continue
    # show matched title and time
    mtitle = matched.get('name') or matched.get('title') or ''
    mtime = matched.get('time') or matched.get('date') or ''
    print("    matched title:", mtitle)
    print("    matched time:", mtime)
    holdings = _extract_holdings_from_strategy_item(matched)
    print("    holdings parsed:", holdings)
    included_allocs.append((cfg, matched, holdings))
    # compute expected per-holding for this allocation
    for nm, pct in holdings:
        if nm is None or pct is None:
            continue
        frac = float(pct)/100.0
        expected_money = Decimal(str(frac * cfg_frac)) * total_asset
        code = resolve_name_to_code(nm)
        if code:
            expected_by_code[code] = expected_by_code.get(code, Decimal('0')) + expected_money
        else:
            expected_by_name[nm] = expected_by_name.get(nm, Decimal('0')) + expected_money
        print(f"      -> {nm} pct={pct} expected_this={expected_money:.2f} code={code}")

print("\n>>> Aggregated expected_by_code (sample 30):")
pprint({k: float(v) for k,v in list(expected_by_code.items())[:30]})
print("\n>>> Aggregated expected_by_name (sample 30):")
pprint({k: float(v) for k,v in list(expected_by_name.items())[:30]})

print("\n>>> included allocation count:", len(included_allocs))