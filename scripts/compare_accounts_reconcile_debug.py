#!/usr/bin/env python3
"""
Deep diagnostic for reconcile calculations across accounts.

Usage (from repo root):
  python scripts/compare_accounts_reconcile_debug.py <account_id_1> [<account_id_2> ...]

Example:
  python scripts/compare_accounts_reconcile_debug.py 8886086288 8886006288

What it does:
 - Imports gui.reconcile_ui helpers and prints detailed per-account breakdown:
   total_asset, proportion, per-allocation holdings and expected contribution,
   draft contributions, expected_by_code/name summaries, and reconcile_for_account rows.
 - When two accounts are provided, prints ratios for quick comparison.
"""
import sys
import os
from decimal import Decimal
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, repo_root)

try:
    import gui.reconcile_ui as ru
except Exception as e:
    print("ERROR: cannot import gui.reconcile_ui:", e)
    raise

def fmt_d(v):
    try:
        return "{:.2f}".format(float(v))
    except Exception:
        return str(v)

def analyze(account_id):
    print("\n" + "="*80)
    print(f"ANALYZE ACCOUNT: {account_id}")
    print("="*80)

    # clear mama cache to ensure fresh read
    try:
        ru._MAMA_CACHE = None
    except Exception:
        pass

    allocation_list = ru.load_allocation_list()
    strategies = ru.load_parsed_strategies()
    asset = ru.load_account_asset_latest(account_id)
    positions = ru.load_account_positions_latest(account_id)

    print(f" allocation entries: {len(allocation_list)}")
    print(f" parsed strategies: {len(strategies)}")
    print(f" asset snapshot present: {'yes' if asset else 'no'}")
    if asset:
        total_asset = Decimal(str(asset.get('total_asset') or asset.get('m_dAsset') or 0))
        print(" total_asset:", fmt_d(total_asset))
    else:
        total_asset = Decimal('0')
        print(" total_asset: MISSING")

    # proportion (global loader)
    try:
        prop = ru._load_mama_proportion()
    except Exception as e:
        prop = None
        print(" _load_mama_proportion() raised:", e)
    print(" loaded proportion:", prop)

    # Build current_by_code/name
    current_by_code = {}
    current_by_name = {}
    for p in (positions or []):
        raw_code = (p.get('stock_code') or p.get('code') or '').strip()
        name = p.get('stock_name') or p.get('stock') or ''
        try:
            mv = Decimal(str(p.get('market_value') or 0))
        except Exception:
            mv = Decimal('0')
        if raw_code:
            current_by_code[raw_code] = {'name': name, 'market_value': mv, 'raw': p}
            base = raw_code.split('.')[0] if '.' in raw_code else raw_code
            if base not in current_by_code:
                current_by_code[base] = {'name': name, 'market_value': mv, 'raw': p}
        if name:
            cur = current_by_name.get(name, Decimal('0'))
            current_by_name[name] = cur + mv

    print(f" positions count: {len(positions or [])}")
    print(" sample current_by_code keys:", list(current_by_code.keys())[:10])
    print(" current_by_name (name -> mv) sample:")
    for nm, mv in list(current_by_name.items())[:20]:
        print("  ", nm, "->", fmt_d(mv))

    # Per-allocation breakdown
    expected_by_code = {}
    expected_by_name = {}
    per_alloc_contribs = []  # list of (alloc_cfg, strategy_name or None, list of holdings with (name,pct,expected_money,code))
    for cfg in allocation_list:
        json_name = (cfg.get('策略名称') or '').strip()
        try:
            config_pct = float(cfg.get('配置仓位', 0)) / 100.0
        except Exception:
            config_pct = 0.0
        # find matched strategy (use same heuristics as reconcile_for_account)
        matched = None
        if hasattr(ru, "find_strategy_by_id_and_bracket") and ru.find_strategy_by_id_and_bracket:
            try:
                matched = ru.find_strategy_by_id_and_bracket(cfg, strategies)
            except Exception:
                matched = None
        else:
            for s in strategies:
                web_full_name = (s.get('name') or s.get('title') or '').strip()
                if web_full_name.endswith(json_name) and json_name:
                    matched = s
                    break
        holdings_info = []
        if matched:
            holdings = ru._extract_holdings_from_strategy_item(matched)
            for name, pct in holdings:
                if not name or pct is None:
                    continue
                try:
                    frac = float(pct) / 100.0
                except Exception:
                    frac = 0.0
                exp_money = (Decimal(str(frac * config_pct)) * total_asset * Decimal(str(prop))) if total_asset else Decimal('0')
                code = ru.resolve_name_to_code(name) if hasattr(ru, "resolve_name_to_code") else None
                holdings_info.append((name, pct, exp_money, code))
                # aggregate
                if code:
                    base = code.split('.')[0] if '.' in code else code
                    expected_by_code[base] = expected_by_code.get(base, Decimal('0')) + exp_money
                else:
                    expected_by_name[name] = expected_by_name.get(name, Decimal('0')) + exp_money
        per_alloc_contribs.append((cfg, (matched.get('name') if matched else None), holdings_info))

    # print allocations contributions (only those that contribute > 0)
    print("\nPer-allocation contributions (showing non-zero holdings):")
    for cfg, sname, holdings in per_alloc_contribs:
        has_nonzero = any((h[2] and h[2] != 0) for h in holdings)
        if not has_nonzero:
            continue
        print(f"  Alloc: {cfg.get('策略名称')}  配置仓位={cfg.get('配置仓位')}  matched_strategy={sname}")
        for name, pct, exp_money, code in holdings:
            print(f"    holding: {name:20} pct={pct} -> expected={fmt_d(exp_money)} code={code}")

    # Draft entries
    print("\nDraft entries (tradeplan):")
    draft = ru._load_trade_plan_draft()
    entries = ru._extract_entries_from_draft(draft) if draft else []
    print(" draft entries count:", len(entries))
    for ent in entries:
        name = ent.get('name')
        if 'pct' in ent and ent.get('pct') is not None:
            pct = ent.get('pct')
            amt = (Decimal(str(pct)) / Decimal('100')) * total_asset * Decimal(str(prop)) if total_asset else Decimal('0')
            print(f"  draft pct: {name} pct={pct} -> amt={fmt_d(amt)}")
            # aggregate like reconcile_for_account would
            mapped_code = None
            core_map = ru._load_core_stock_code_map()
            if core_map and name in core_map:
                mapped_code = core_map.get(name)
            if not mapped_code and __import__('re').fullmatch(r'\d{6}(\.(SH|SZ))?', str(name), __import__('re').IGNORECASE):
                mapped_code = name
            if not mapped_code:
                mapped_code = ru.resolve_name_to_code(name)
            if mapped_code:
                base = mapped_code.split('.')[0] if '.' in mapped_code else mapped_code
                expected_by_code[base] = expected_by_code.get(base, Decimal('0')) + amt
            else:
                expected_by_name[name] = expected_by_name.get(name, Decimal('0')) + amt
        elif 'amount' in ent and ent.get('amount') is not None:
            amt = Decimal(str(ent.get('amount'))) * Decimal(str(prop))
            print(f"  draft amount: {name} amount={ent.get('amount')} -> after proportion={fmt_d(amt)}")
            mapped_code = None
            core_map = ru._load_core_stock_code_map()
            if core_map and name in core_map:
                mapped_code = core_map.get(name)
            if not mapped_code and __import__('re').fullmatch(r'\d{6}(\.(SH|SZ))?', str(name), __import__('re').IGNORECASE):
                mapped_code = name
            if not mapped_code:
                mapped_code = ru.resolve_name_to_code(name)
            if mapped_code:
                base = mapped_code.split('.')[0] if '.' in mapped_code else mapped_code
                expected_by_code[base] = expected_by_code.get(base, Decimal('0')) + amt
            else:
                expected_by_name[name] = expected_by_name.get(name, Decimal('0')) + amt

    # Summaries
    sum_expected_code = sum(expected_by_code.values()) if expected_by_code else Decimal('0')
    sum_expected_name = sum(expected_by_name.values()) if expected_by_name else Decimal('0')
    print("\nExpected summary:")
    print(" expected_by_code count:", len(expected_by_code), " sum:", fmt_d(sum_expected_code))
    for k, v in sorted(expected_by_code.items(), key=lambda x: x[1], reverse=True)[:30]:
        print("  ", k, fmt_d(v))
    print(" expected_by_name count:", len(expected_by_name), " sum:", fmt_d(sum_expected_name))
    for k, v in sorted(expected_by_name.items(), key=lambda x: x[1], reverse=True)[:30]:
        print("  ", k, fmt_d(v))

    # final reconcile rows (reuse reconcile_for_account if available, else mimic)
    print("\nFinal rows from reconcile_for_account() (if available):")
    try:
        ru._MAMA_CACHE = None
        res = ru.reconcile_for_account(account_id)
        print(" reconcile_for_account returned rows count:", len(res.get('rows', [])))
        for r in res.get('rows', [])[:50]:
            print("  ", r.get('stock_code'), r.get('stock_name')[:20], " expected=", fmt_d(r.get('expected_money')), " current=", fmt_d(r.get('current_market_value')), " diff=", fmt_d(r.get('diff_money')))
    except Exception as e:
        print(" reconcile_for_account() failed:", e)
        res = {}

    return {
        'account_id': account_id,
        'total_asset': total_asset,
        'sum_expected_code': sum_expected_code,
        'sum_expected_name': sum_expected_name,
        'expected_by_code': expected_by_code,
        'expected_by_name': expected_by_name,
        'reconcile_rows': res.get('rows') if res else None,
    }

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/compare_accounts_reconcile_debug.py <account1> [<account2> ...]")
        sys.exit(1)
    results = {}
    for aid in sys.argv[1:]:
        results[aid] = analyze(aid)

    # if two accounts provided, print ratio comparisons
    if len(sys.argv[1:]) >= 2:
        aids = list(sys.argv[1:])
        a1 = results[aids[0]]
        a2 = results[aids[1]]
        print("\n" + "="*80)
        print("COMPARE ACCOUNTS:", aids[0], "vs", aids[1])
        try:
            ratio_total_asset = float(a1['total_asset'] / a2['total_asset']) if a2['total_asset'] else None
        except Exception:
            ratio_total_asset = None
        print(" total_asset ratio (a1/a2):", ratio_total_asset)
        try:
            ratio_expected = float((a1['sum_expected_code'] + a1['sum_expected_name']) / (a2['sum_expected_code'] + a2['sum_expected_name'])) if (a2['sum_expected_code'] + a2['sum_expected_name']) else None
        except Exception:
            ratio_expected = None
        print(" expected sum ratio (a1/a2):", ratio_expected)