# quick_debug_keys.py
# 快速诊断 allocation.json / parsed strategies / account_data 是否可用以及字段名情况
import json, os
from gui.reconcile_ui import load_parsed_strategies, load_account_asset_latest, load_account_positions_latest

ALLOCATION_PATH = os.path.join("yunfei_ball", "allocation.json")

def print_alloc_keys():
    try:
        with open(ALLOCATION_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print("读取 allocation.json 失败:", e)
        return

    if not data:
        print("allocation.json 为空或解析为 []")
        return

    print("allocation entries:", len(data))
    first = data[0]
    print("第1条 allocation keys:")
    for k in first.keys():
        print("  -", repr(k))
    # try show sample values for those keys
    print("\n第1条 allocation raw:")
    print(json.dumps(first, ensure_ascii=False, indent=2))

def print_parsed_strategies_sample():
    strats = load_parsed_strategies()
    print("\nparsed strategies count:", len(strats))
    if len(strats) > 0:
        for s in strats[:5]:
            title = s.get('name') or s.get('title') or s.get('time') or str(s)[:80]
            print(" - strategy title:", title)
            # try to show holdings quick
            holdings = s.get('holdings') or s.get('holding') or s.get('holding_block') or s.get('operation_block') or None
            print("   holdings (raw):", holdings)

def print_account_snapshots(account_id="8886006288"):
    asset = load_account_asset_latest(account_id)
    positions = load_account_positions_latest(account_id)
    print(f"\nasset file exists: {bool(asset)}")
    if asset:
        print(" asset total_asset:", asset.get('total_asset') or asset.get('m_dAsset') or None)
    print("positions count:", len(positions) if positions is not None else 0)
    if positions:
        print(" first positions sample:", positions[:5])

if __name__ == "__main__":
    print_alloc_keys()
    print_parsed_strategies_sample()
    print_account_snapshots("8886006288")