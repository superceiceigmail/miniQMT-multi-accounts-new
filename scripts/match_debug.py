# match_debug.py
# Debug allocation <-> parsed strategies matching.
# Save to project root and run: python match_debug.py
import json
import os
from pprint import pprint

# imports from project
try:
    from gui.reconcile_ui import load_allocation_list, load_parsed_strategies, _extract_holdings_from_strategy_item
except Exception:
    # fallback if gui package path differs
    import sys
    sys.path.append(os.path.abspath('..'))
    from gui.reconcile_ui import load_allocation_list, load_parsed_strategies, _extract_holdings_from_strategy_item

try:
    from yunfei_ball.yunfei_connect_follow import find_strategy_by_id_and_bracket
except Exception:
    find_strategy_by_id_and_bracket = None

def match_by_id_prefix(cfg, strategies):
    sid = str(cfg.get('策略ID') or cfg.get('策略Id') or cfg.get('id') or '')
    if not sid:
        return None
    prefix = sid[:-1] if len(sid) > 1 else sid
    for s in strategies:
        web_full_name = (s.get('name') or s.get('title') or '')
        # try extract L12345: style id from title
        import re
        m = re.search(r"L?(\d+):", web_full_name)
        if m:
            if m.group(1).startswith(prefix):
                return s
    return None

def match_by_name_ends(cfg, strategies):
    target = (cfg.get('策略名称') or cfg.get('name') or '').strip()
    if not target:
        return None
    for s in strategies:
        web_full_name = (s.get('name') or s.get('title') or '').strip()
        if web_full_name.endswith(target) and target:
            return s
    return None

def main():
    allocs = load_allocation_list()
    strats = load_parsed_strategies()
    print("allocation count:", len(allocs))
    print("parsed strategies count:", len(strats))
    print()

    # Show first 12 parsed strategy titles for inspection
    print("Parsed strategy titles (first 12):")
    for s in strats[:12]:
        print(" -", s.get('name') or s.get('title') or s.get('time') or '')

    for i, cfg in enumerate(allocs, 1):
        name = cfg.get('策略名称') or cfg.get('name') or ''
        sid = cfg.get('策略ID') or cfg.get('id') or ''
        print("\n[%02d] Allocation: name=%r  id=%r  配置仓位=%r  批次=%r" % (i, name, sid, cfg.get('配置仓位'), cfg.get('交易批次')))
        matched = None
        # try library matcher first if available
        if find_strategy_by_id_and_bracket:
            try:
                matched = find_strategy_by_id_and_bracket(cfg, strats)
            except Exception as e:
                print(" find_strategy_by_id_and_bracket raised:", e)
                matched = None
        if not matched:
            matched = match_by_id_prefix(cfg, strats)
            if matched:
                print(" matched by id prefix heuristic")
        if not matched:
            matched = match_by_name_ends(cfg, strats)
            if matched:
                print(" matched by name.endswith heuristic")

        if not matched:
            print(" NOT matched. Showing sample parsed titles to help diagnosis:")
            for s in strats[:20]:
                print("  *", s.get('name') or s.get('title') or '')
            continue

        # show matched info
        print(" MATCHED -> title:", matched.get('name') or matched.get('title'))
        # show parsed time/date if present
        t = matched.get('time') or matched.get('date') or ''
        print("  parsed time/date:", t)
        # show holdings parsed
        holdings = _extract_holdings_from_strategy_item(matched)
        print("  extracted holdings (name, pct):")
        pprint(holdings)

if __name__ == "__main__":
    main()