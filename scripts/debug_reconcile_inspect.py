#!/usr/bin/env python3
"""
Diagnostic helper for reconcile anomalies.
Run from repo root:
  python tools/debug_reconcile_inspect.py 8886006288 2954.9
"""
import sys
import os
from decimal import Decimal

repo_root = os.path.abspath(os.path.dirname(__file__) + "/..")
sys.path.insert(0, repo_root)

try:
    import gui.reconcile_ui as ru
except Exception as e:
    print("无法导入 gui.reconcile_ui:", e)
    raise

def approx_eq(a, b, tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def inspect(account_id, target_value):
    print("加载 allocation.json ...")
    allocs = ru.load_allocation_list()
    print(f"allocation 条目数: {len(allocs)}")

    print("\n加载已解析策略（parsed strategies） ...")
    strategies = ru.load_parsed_strategies()
    print(f"parsed strategies 条目数: {len(strategies)}")

    print("\n计算来自 allocation+策略 的预期金额候选 (查找接近目标的项)...")
    total_asset = None
    asset = ru.load_account_asset_latest(account_id)
    if asset:
        total_asset = Decimal(str(asset.get('total_asset') or asset.get('m_dAsset') or 0))
    else:
        print("无法读取 account asset snapshot (account_data/assets/asset_{account}.json)")

    # Build a list of expected-money candidates: allocation * holding pct * total_asset
    candidates = []
    for cfg in allocs:
        try:
            config_pct = float(cfg.get('配置仓位', 0)) / 100.0
        except Exception:
            config_pct = 0.0
        # try to find matching strategy in parsed strategies (simple suffix match as reconcile_for_account does)
        json_name = (cfg.get('策略名称') or '').strip()
        matched = None
        for s in strategies:
            web_full_name = (s.get('name') or s.get('title') or '').strip()
            if json_name and web_full_name.endswith(json_name):
                matched = s
                break
        if not matched:
            continue
        holdings = ru._extract_holdings_from_strategy_item(matched)
        for name, pct in holdings:
            if not name or pct is None or not total_asset:
                continue
            try:
                frac = float(pct) / 100.0
            except Exception:
                frac = 0.0
            expected_money = (Decimal(str(frac * config_pct)) * total_asset).quantize(Decimal('0.01'))
            candidates.append({
                'strategy_name': matched.get('name'),
                'cfg_name': json_name,
                'holding_name': name,
                'holding_pct': pct,
                'config_pct': config_pct,
                'expected_money': float(expected_money),
            })

    # Also check trade plan draft entries (GUI draft)
    draft = ru._load_trade_plan_draft()
    draft_entries = ru._extract_entries_from_draft(draft) if draft else []
    draft_candidates = []
    for ent in draft_entries:
        if 'pct' in ent and ent.get('pct') is not None and total_asset:
            pct = float(ent.get('pct'))
            proportion = ru._load_mama_proportion()
            amt = float((Decimal(str(pct)) / Decimal('100') * total_asset * Decimal(str(proportion))).quantize(Decimal('0.01')))
            draft_candidates.append({'name': ent.get('name'), 'pct': pct, 'amount': amt})
        elif 'amount' in ent:
            draft_candidates.append({'name': ent.get('name'), 'amount': float(ent.get('amount'))})

    print(f"计算到的 allocation-based 预期持仓数: {len(candidates)}")
    hits = [c for c in candidates if approx_eq(c['expected_money'], target_value, tol=0.5)]
    print(f"与目标值 {target_value} 匹配的 allocation-based 条目: {len(hits)}")
    for h in hits:
        print(h)

    print("\n检查 draft entries 中接近目标的项:")
    for d in draft_candidates:
        if 'amount' in d and approx_eq(d['amount'], target_value, tol=0.5):
            print("draft match:", d)

    print("\n查看 account positions (account_data/positions/position_{id}.json) ...")
    positions = ru.load_account_positions_latest(account_id)
    print(f"positions count: {len(positions)}")
    pos_hits = []
    for p in positions:
        code = (p.get('stock_code') or p.get('code') or '').strip()
        name = p.get('stock_name') or p.get('stock') or ''
        try:
            mv = float(p.get('market_value') or p.get('mkt_value') or p.get('m_dFVal') or 0)
        except Exception:
            mv = None
        if mv is not None and approx_eq(mv, target_value, tol=0.5):
            pos_hits.append({'code': code, 'name': name, 'market_value': mv, 'raw': p})
    print(f"positions 中 market_value 接近 {target_value} 的条目数: {len(pos_hits)}")
    for ph in pos_hits:
        print(ph)

    print("\n构建 current_by_name/current_by_code（如 reconcile_for_account）并打印 name 累计值：")
    current_by_code = {}
    current_by_name = {}
    from decimal import Decimal as D
    for p in (positions or []):
        raw_code = (p.get('stock_code') or p.get('code') or '').strip()
        name = p.get('stock_name') or p.get('stock') or ''
        try:
            mv = D(str(p.get('market_value') or p.get('mkt_value') or 0))
        except Exception:
            mv = D('0')
        if raw_code:
            current_by_code[raw_code] = {'name': name, 'market_value': mv, 'raw': p}
            base = raw_code[:6]
            if base not in current_by_code:
                current_by_code[base] = {'name': name, 'market_value': mv, 'raw': p}
        if name:
            cur = current_by_name.get(name, D('0'))
            current_by_name[name] = cur + mv
    print("current_by_code keys sample:", list(current_by_code.keys())[:10])
    print("current_by_name (name -> market_value):")
    for nm, mv in current_by_name.items():
        print(f"  {nm!r}: {float(mv)}")

    # show name->code resolution for suspects
    suspect_names = set()
    for h in hits:
        suspect_names.add(h['holding_name'])
    for d in draft_candidates:
        if 'amount' in d and approx_eq(d['amount'], target_value, tol=0.5):
            suspect_names.add(d.get('name'))
    print("\n对 suspect name 尝试 resolve_name_to_code:")
    for nm in suspect_names:
        resolved = ru.resolve_name_to_code(nm)
        print(f"  {nm!r} -> {resolved}")

    print("\n运行 reconcile_for_account 并打印 both / yunfei_only / positions_only（如果可用）:")
    try:
        res = ru.reconcile_for_account(account_id)
        import json
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    except Exception as e:
        print("调用 reconcile_for_account 失败:", e)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python tools/debug_reconcile_inspect.py <account_id> <target_value>")
        sys.exit(1)
    acct = sys.argv[1]
    tgt = float(sys.argv[2])
    inspect(acct, tgt)