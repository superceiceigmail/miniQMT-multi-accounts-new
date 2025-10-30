#!/usr/bin/env python3
"""
Check whether mama.proportion is actually applied in reconcile_for_account.
Usage:
  python scripts/check_proportion_effect.py <account_id>
Example:
  python scripts/check_proportion_effect.py 8886006288
"""
import sys, os, json
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, repo_root)

try:
    import gui.reconcile_ui as ru
except Exception as e:
    print("ERROR: cannot import gui.reconcile_ui:", e)
    raise

def run(account_id):
    # clear cache
    try:
        ru._MAMA_CACHE = None
    except Exception:
        pass

    print("MAMA_PATH:", ru.MAMA_PATH)
    prop = ru._load_mama_proportion()
    print("Loaded proportion (from _load_mama_proportion):", prop)

    # show raw file content for confirmation
    try:
        with open(ru.MAMA_PATH, 'r', encoding='utf-8') as f:
            print("mama.json content:", f.read())
    except Exception as e:
        print("Cannot read mama.json:", e)

    # run reconcile_for_account (local)
    try:
        res = ru.reconcile_for_account(account_id)
    except Exception as e:
        print("reconcile_for_account raised exception:", e)
        return

    print("\n--- reconcile_for_account rows (show expected,current) ---")
    for r in res.get('rows', [])[:200]:
        print(f"{r.get('stock_code')!s:12} | {str(r.get('stock_name'))[:30]:30} | expected={r.get('expected_money')} | current={r.get('current_market_value')} | diff={r.get('diff_money')}")

    # Compare with proportion forced to 1.0 (no discount)
    try:
        # monkeypatch loader to return 1.0 and clear caches
        orig_loader = ru._load_mama_proportion
        ru._MAMA_CACHE = None
        ru._load_mama_proportion = lambda: 1.0
        res_no_prop = ru.reconcile_for_account(account_id)
        print("\n--- reconcile_for_account rows WITH proportion=1.0 (comparison) ---")
        for r in res_no_prop.get('rows', [])[:200]:
            print(f"{r.get('stock_code')!s:12} | {str(r.get('stock_name'))[:30]:30} | expected_no_prop={r.get('expected_money')} | current={r.get('current_market_value')}")
    except Exception as e:
        print("Failed to run comparison with proportion=1.0:", e)
    finally:
        # restore
        try:
            ru._load_mama_proportion = orig_loader
            ru._MAMA_CACHE = None
        except Exception:
            pass

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/check_proportion_effect.py <account_id>")
        sys.exit(1)
    run(sys.argv[1])