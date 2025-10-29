# reconcile_check_keys.py
# Compare expected_by_code keys vs current positions codes and show mismatches/details.
import json
from decimal import Decimal
from pprint import pprint
from gui.reconcile_ui import load_allocation_list, load_parsed_strategies, load_account_asset_latest, load_account_positions_latest, _extract_holdings_from_strategy_item, resolve_name_to_code
from yunfei_ball.yunfei_connect_follow import find_strategy_by_id_and_bracket

def build_expected_by_code(account_id="8886006288"):
    allocs = load_allocation_list()
    strats = load_parsed_strategies()
    asset = load_account_asset_latest(account_id)
    total_asset = Decimal(str(asset.get('total_asset') or asset.get('m_dAsset') or 0)) if asset else Decimal('0')
    expected_by_code = {}
    expected_by_name = {}
    for cfg in allocs:
        try:
            cfg_pct = float(cfg.get('配置仓位', 0)) / 100.0
        except Exception:
            cfg_pct = 0.0
        # match
        matched = None
        try:
            matched = find_strategy_by_id_and_bracket(cfg, strats)
        except Exception:
            matched = None
        if not matched:
            # try simple heuristics
            sid = str(cfg.get('策略ID') or cfg.get('策略Id') or cfg.get('id') or '')
            if sid:
                prefix = sid[:-1] if len(sid)>1 else sid
                import re
                for s in strats:
                    web_full_name = (s.get('name') or s.get('title') or '')
                    m = re.search(r"L?(\d+):", web_full_name)
                    if m and m.group(1).startswith(prefix):
                        matched = s
                        break
            if not matched:
                target = (cfg.get('策略名称') or cfg.get('name') or '').strip()
                if target:
                    for s in strats:
                        web_full_name = (s.get('name') or s.get('title') or '').strip()
                        if web_full_name.endswith(target) and target:
                            matched = s
                            break
        if not matched:
            continue
        holdings = _extract_holdings_from_strategy_item(matched)
        for nm, pct in holdings:
            if not nm or pct is None:
                continue
            frac = float(pct)/100.0
            expected_money = Decimal(str(frac * cfg_pct)) * total_asset
            code = resolve_name_to_code(nm)
            if code:
                expected_by_code[code] = expected_by_code.get(code, Decimal('0')) + expected_money
            else:
                expected_by_name[nm] = expected_by_name.get(nm, Decimal('0')) + expected_money
    return expected_by_code, expected_by_name

def build_current_positions_map(account_id="8886006288"):
    positions = load_account_positions_latest(account_id)
    current_by_code = {}
    current_by_name = {}
    for p in (positions or []):
        code = (p.get('stock_code') or p.get('code') or '').strip()
        name = p.get('stock_name') or p.get('stock') or ''
        mv = Decimal(str(p.get('market_value') or 0))
        if code:
            current_by_code[code] = {'name': name, 'market_value': mv, 'raw': p}
        if name:
            current_by_name[name] = current_by_name.get(name, Decimal('0')) + mv
    return current_by_code, current_by_name

def main():
    account_id = "8886006288"
    expected_by_code, expected_by_name = build_expected_by_code(account_id)
    current_by_code, current_by_name = build_current_positions_map(account_id)

    exp_codes = set(expected_by_code.keys())
    cur_codes = set(current_by_code.keys())

    print("EXPECTED codes count:", len(exp_codes))
    print("CURRENT position codes count:", len(cur_codes))
    print()

    print("EXPECTED sample (code -> expected_money float):")
    pprint({k: float(v) for k,v in list(expected_by_code.items())[:50]})
    print()
    print("CURRENT sample (code -> market_value float):")
    pprint({k: float(v['market_value']) for k,v in list(current_by_code.items())[:50]})
    print()

    inter = exp_codes & cur_codes
    only_in_expected = exp_codes - cur_codes
    only_in_current = cur_codes - exp_codes

    print("Intersection count:", len(inter))
    print("Only in expected (count):", len(only_in_expected))
    print("Only in current (count):", len(only_in_current))
    print()

    if inter:
        print("Intersection examples (code, expected, current):")
        for c in sorted(list(inter))[:30]:
            print(c, float(expected_by_code.get(c,0)), float(current_by_code.get(c,{}).get('market_value',0)))
    if only_in_expected:
        print("\nCodes only in expected (first 50):")
        for c in sorted(list(only_in_expected))[:50]:
            print(c, " expected=", float(expected_by_code[c]))
    if only_in_current:
        print("\nCodes only in current positions (first 50):")
        for c in sorted(list(only_in_current))[:50]:
            print(c, " current_mv=", float(current_by_code[c]['market_value']))

    print("\nExpected_by_name sample (for names without code mapping):")
    pprint({k: float(v) for k,v in list(expected_by_name.items())[:50]})

if __name__ == "__main__":
    main()