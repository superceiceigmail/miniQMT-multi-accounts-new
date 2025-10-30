#!/usr/bin/env python3
"""
Inspect how a single instrument's expected_money is computed for an account.

Usage:
  python .\scripts\inspect_instrument.py <account_id> "<instrument_name>"

Example:
  python .\scripts\inspect_instrument.py 8886006288 "创业板50"
"""
import sys, os
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, repo_root)

from decimal import Decimal
import json

try:
    import gui.reconcile_ui as ru
except Exception as e:
    print("ERROR: cannot import gui.reconcile_ui:", e)
    raise

def inspect(account_id, instr_name):
    # clear caches to force fresh reads
    try:
        ru._MAMA_CACHE = None
    except Exception:
        pass
    try:
        # if cache is a dict, clear it; if variable, reset to {}
        if hasattr(ru, "_MAMA_PROPORTIONS_CACHE"):
            try:
                ru._MAMA_PROPORTIONS_CACHE = {}
            except Exception:
                try:
                    ru._MAMA_PROPORTIONS_CACHE = {}
                except Exception:
                    pass
    except Exception:
        pass

    print("Account:", account_id)
    asset = ru.load_account_asset_latest(account_id)
    print(" total_asset object:", asset)
    total_asset = Decimal(str(asset.get('total_asset') or asset.get('m_dAsset') or 0)) if asset else Decimal('0')
    print(" total_asset (Decimal):", total_asset)

    # proportions: try per-account loader if available, fallback to older APIs
    etf = yf = None
    try:
        if hasattr(ru, "_load_mama_proportions_for_account"):
            etf, yf = ru._load_mama_proportions_for_account(str(account_id))
        elif hasattr(ru, "_load_mama_proportions"):
            etf, yf = ru._load_mama_proportions()
        else:
            # single legacy loader
            single = ru._load_mama_proportion() if hasattr(ru, "_load_mama_proportion") else 1.0
            etf = yf = Decimal(str(single))
    except Exception as e:
        print("Failed to load proportions:", e)
        etf = yf = Decimal('1.0')
    print(" proportions -> ETF:", etf, " YF:", yf)

    # draft file
    draft = ru._load_trade_plan_draft()
    print("\ntrade_plan_draft.json (top-level keys):", list(draft.keys()) if isinstance(draft, dict) else draft)
    # show final_holdings entries if present
    final_holdings = draft.get('final_holdings') or draft.get('final_holdings_info') or draft.get('final_holdings_suggested')
    print(" final_holdings present:", bool(final_holdings))
    if final_holdings:
        for it in final_holdings:
            if str(it.get('name') or '').strip() == instr_name:
                print(" final_holdings entry for", instr_name, "=>", json.dumps(it, ensure_ascii=False))

    # extracted draft entries
    extracted = ru._extract_entries_from_draft(draft) if draft else []
    print("\n_extracted entries from draft (count):", len(extracted))
    for e in extracted:
        if e.get('name') and instr_name in str(e.get('name')):
            print(" extracted entry match:", e)

    # draft reference total
    ref = ru._find_reference_total_from_draft_or_assets(draft)
    print("\ndraft reference total (from draft/base or max asset):", ref)

    # compute allocation contributions for this instrument
    allocation_list = ru.load_allocation_list()
    strategies = ru.load_parsed_strategies()
    contrib_alloc = Decimal('0')
    contrib_alloc_details = []
    for cfg in allocation_list:
        try:
            config_pct = float(cfg.get('配置仓位', 0)) / 100.0
        except Exception:
            config_pct = 0.0
        matched = None
        if hasattr(ru, "find_strategy_by_id_and_bracket") and ru.find_strategy_by_id_and_bracket:
            try:
                matched = ru.find_strategy_by_id_and_bracket(cfg, strategies)
            except Exception:
                matched = None
        else:
            json_name = (cfg.get('策略名称') or '').strip()
            for s in strategies:
                web_full_name = (s.get('name') or s.get('title') or '').strip()
                if web_full_name.endswith(json_name) and json_name:
                    matched = s
                    break
        if not matched:
            continue
        holdings = ru._extract_holdings_from_strategy_item(matched)
        for name, pct in holdings:
            if not name or pct is None:
                continue
            if instr_name.strip() == str(name).strip():
                try:
                    frac = float(pct) / 100.0
                except Exception:
                    frac = 0.0
                # allocation uses proportion_YF
                val = (Decimal(str(frac * config_pct)) * total_asset * Decimal(str(yf))).quantize(Decimal('0.01'))
                contrib_alloc += val
                contrib_alloc_details.append({'alloc_cfg': cfg.get('策略名称'), 'config_pct': config_pct, 'holding_pct': pct, 'value': val})
    print("\nAllocation contributions for", instr_name, "count:", len(contrib_alloc_details))
    for d in contrib_alloc_details:
        print(" ", d)
    print(" total allocation contribution:", contrib_alloc)

    # draft contributions
    contrib_draft = Decimal('0')
    contrib_draft_details = []
    # build draft_entries same as reconcile_for_account
    draft_entries = []
    if draft:
        final_holdings = draft.get('final_holdings') or draft.get('final_holdings_info') or draft.get('final_holdings_suggested')
        if isinstance(final_holdings, list) and final_holdings:
            for it in final_holdings:
                name = it.get('name') or it.get('stock_name') or ''
                fp = it.get('final_pct') if it.get('final_pct') is not None else it.get('final_pct_suggested') if it.get('final_pct_suggested') is not None else None
                if fp is not None:
                    try:
                        pct_val = float(fp)
                        draft_entries.append({'name': name, 'pct': pct_val, 'src': 'final_holdings.final_pct'})
                    except Exception:
                        pass
        else:
            draft_entries = ru._extract_entries_from_draft(draft)

    draft_reference_total = ref
    for ent in draft_entries:
        if not ent.get('name') or instr_name not in str(ent.get('name')):
            continue
        if 'pct' in ent and ent.get('pct') is not None:
            pct_raw = Decimal(str(ent.get('pct')))
            pct_fraction = pct_raw / Decimal('100')
            val = (pct_fraction) * total_asset * Decimal(str(etf))
            contrib_draft += val
            contrib_draft_details.append({'src': ent.get('src','draft_pct'), 'pct_raw': pct_raw, 'value': val})
        elif 'amount' in ent and ent.get('amount') is not None:
            raw_amt = Decimal(str(ent.get('amount')))
            if draft_reference_total and draft_reference_total != Decimal('0') and draft_reference_total != total_asset:
                try:
                    scale = (total_asset / draft_reference_total)
                    val = (raw_amt * scale) * Decimal(str(etf))
                except Exception:
                    val = raw_amt * Decimal(str(etf))
            else:
                val = raw_amt * Decimal(str(etf))
            contrib_draft += val
            contrib_draft_details.append({'src': 'draft_amount', 'raw_amt': raw_amt, 'scaled_value': val, 'draft_ref': draft_reference_total})

    print("\nDraft contributions for", instr_name, "count:", len(contrib_draft_details))
    for d in contrib_draft_details:
        print(" ", d)
    print(" total draft contribution:", contrib_draft)

    # final reconcile_for_account row (if available)
    try:
        ru._MAMA_CACHE = None
    except Exception:
        pass
    try:
        # clear per-account cache if present
        try:
            ru._MAMA_PROPORTIONS_CACHE = {}
        except Exception:
            pass
    except Exception:
        pass

    try:
        res = ru.reconcile_for_account(account_id)
        rows = res.get('rows') or []
        for r in rows:
            nm = r.get('stock_name') or ''
            if instr_name in str(nm):
                print("\nFinal reconcile row for", instr_name, ":", r)
    except Exception as e:
        print("reconcile_for_account() failed:", e)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/inspect_instrument.py <account_id> \"<instrument_name>\"")
        sys.exit(1)
    aid = sys.argv[1]
    name = sys.argv[2]
    inspect(aid, name)