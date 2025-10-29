#!/usr/bin/env python3
# diag_match.py
# Diagnostic script to compare yunfei_ball/allocation.json (策略配置) with the currently
# fetched strategies from the website (via yunfei_ball.yunfei_fetcher.fetch_b_follow).
#
# Usage:
#  - From project root (where yunfei_ball is a package):
#      python diag_match.py
#  - Optional: if you already have a saved fetch result, put it as debug_out_items.json
#    in project root and the script will use it instead of performing a network fetch.
#
# Output:
#  - Prints summary of matched / unmatched entries.
#  - Writes diag_match_result.json with details (matched list and unmatched list).
#  - Writes debug_out_items.json when a fetch is performed.

import json
import os
import re
from collections import defaultdict
from typing import List, Dict

# Try to import fetcher from the package
try:
    from yunfei_ball.yunfei_fetcher import fetch_b_follow
except Exception:
    fetch_b_follow = None

ALLOCATION_PATH = os.path.join("../yunfei_ball", "allocation.json")
DEBUG_ITEMS_PATH = "../archive/tests_archive_20251029/debug_out_items.json"
DIAG_OUT = "diag_match_result.json"


def get_bracket_content(s: str) -> str:
    m = re.search(r"(?:\(|（)(.*?)(?:\)|）)", s)
    return m.group(1).strip() if m else ""


def extract_operation_action(op_html: str) -> str:
    """
    Determine action type from operation block text/html.
    Mirrors logic in connect_follow.extract_operation_action.
    """
    if not op_html:
        return "继续持有"
    # strip html tags if any
    text = re.sub(r"<[^>]+>", "", op_html)
    if any(k in text for k in ("买入", "卖出", "换入", "换出", "调仓")):
        return "买卖"
    if "空仓" in text:
        return "空仓"
    if "继续持有" in text:
        return "继续持有"
    return "未知"


def find_strategy_by_id_and_bracket(cfg: Dict, strategies: List[Dict]) -> Dict:
    """
    Attempt matching cfg (from allocation.json) to one of strategies (parsed page items).
    This implements the same heuristic as connect_follow.find_strategy_by_id_and_bracket:
      1) match if web_full_name.endswith(json_name)
      2) fallback: match by ID prefix and bracket content
    Returns the matched strategy dict or None.
    """
    json_name = cfg.get("策略名称", "").strip()
    json_id = str(cfg.get("策略ID", "")).strip()

    # 1) endswith match on web name
    for s in strategies:
        web_full_name = (s.get("name") or s.get("title") or "").strip()
        if web_full_name.endswith(json_name) and json_name:
            return s

    # 2) fallback: id prefix + bracket match
    if not json_id:
        return None
    json_id_prefix = json_id[:-1] if len(json_id) > 1 else json_id
    json_bracket = get_bracket_content(json_name)
    for s in strategies:
        web_full_name = (s.get("name") or s.get("title") or "").strip()
        id_match = re.search(r"L?(\d+):", web_full_name)
        if not id_match:
            continue
        web_id = id_match.group(1)
        if web_id.startswith(json_id_prefix):
            web_bracket = get_bracket_content(web_full_name)
            if json_bracket and web_bracket and json_bracket == web_bracket:
                return s
    return None


def normalize_strategy_item(it: Dict) -> Dict:
    """
    Ensure strategy item has the expected keys used by matching logic:
      - name (string)
      - date (YYYY-MM-DD string)  (attempt to extract from 'time' or 'date')
      - time (full timestamp string)
      - operation_block (text or html)
      - holding_block (list of strings)
    Works with both the 'old' and 'new' parser outputs.
    """
    name = it.get("name") or it.get("title") or ""
    time_str = it.get("time") or it.get("time_str") or ""
    date = (time_str.split()[0] if time_str else (it.get("date") or ""))
    operation_block = it.get("operation_block") or it.get("op_text") or it.get("operation_html") or ""
    # holdings may be list of dicts or list of strings
    holding_block = []
    raw_holdings = it.get("holding_block") or it.get("holding") or it.get("holdings") or it.get("holding_block_raw") or []
    if isinstance(raw_holdings, str):
        parts = [p.strip() for p in re.split(r'[\n;；,，/]', raw_holdings) if p.strip()]
        holding_block.extend(parts)
    elif isinstance(raw_holdings, list):
        for h in raw_holdings:
            if isinstance(h, dict):
                hname = h.get("name") or ""
                pct = h.get("pct")
                if pct is None:
                    pct = h.get("percentage")
                if pct is None:
                    holding_block.append(hname)
                else:
                    # format as legacy "名称：xx%"
                    try:
                        holding_block.append(f"{hname}：{float(pct)}%")
                    except Exception:
                        holding_block.append(f"{hname}：{pct}%")
            else:
                holding_block.append(str(h))
    else:
        if raw_holdings:
            holding_block.append(str(raw_holdings))
    # fallback to legacy fields if present
    if not holding_block and it.get("holding_block"):
        holding_block = it.get("holding_block")

    return {
        "name": name,
        "date": date,
        "time": time_str,
        "operation_block": operation_block,
        "holding_block": holding_block,
        # keep original for debugging
        "_raw": it
    }


def main():
    # load allocation.json
    if not os.path.exists(ALLOCATION_PATH):
        print(f"allocation.json not found at {ALLOCATION_PATH}. Please ensure file exists.")
        return
    try:
        cfgs = json.load(open(ALLOCATION_PATH, "r", encoding="utf-8"))
    except Exception as e:
        print("Failed to load allocation.json:", e)
        return
    print(f"Loaded {len(cfgs)} allocation entries from {ALLOCATION_PATH}.")

    # load or fetch items
    if os.path.exists(DEBUG_ITEMS_PATH):
        try:
            items = json.load(open(DEBUG_ITEMS_PATH, "r", encoding="utf-8"))
            print(f"Loaded {len(items)} items from {DEBUG_ITEMS_PATH}.")
        except Exception as e:
            print("Failed to load debug_out_items.json:", e)
            items = []
    else:
        if fetch_b_follow is None:
            print("fetch_b_follow not available (could not import). Please run this script from project root where yunfei_ball is importable.")
            return
        print("Fetching current strategies from site (this may require login)...")
        r = fetch_b_follow(force=True, parse=True)
        warn = r.get("warning")
        if warn:
            print("Fetch warning:", warn)
        items = r.get("items", [])
        try:
            with open(DEBUG_ITEMS_PATH, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            print(f"Saved fetched items to {DEBUG_ITEMS_PATH}.")
        except Exception:
            pass

    # normalize items
    strategies = [normalize_strategy_item(it) for it in items]
    names = [s.get("name") for s in strategies]
    print("Sample fetched strategy names (first 10):")
    for n in names[:10]:
        print(" -", n)

    # group allocation by batch
    batch_dict = defaultdict(list)
    for cfg in cfgs:
        batch = cfg.get("交易批次", 1)
        batch_dict[batch].append(cfg)

    matched = []
    unmatched = []
    matched_map = []  # tuples for output

    for batch_no in sorted(batch_dict.keys()):
        print(f"\n=== Batch {batch_no} ({len(batch_dict[batch_no])} configs) ===")
        for cfg in batch_dict[batch_no]:
            s = find_strategy_by_id_and_bracket(cfg, strategies)
            if s:
                action = extract_operation_action(s.get("operation_block", ""))
                matched.append((batch_no, cfg, s, action))
                print(f" MATCHED: {cfg.get('策略名称')} -> {s.get('name')}  date={s.get('date')}  action={action}")
                matched_map.append({
                    "batch": batch_no,
                    "config": cfg,
                    "matched_name": s.get("name"),
                    "matched_date": s.get("date"),
                    "action": action
                })
            else:
                unmatched.append((batch_no, cfg))
                print(f" UNMATCHED: {cfg.get('策略名称')}  ID={cfg.get('策略ID')}")

    print("\nSummary:")
    print("  matched:", len(matched))
    print("  unmatched:", len(unmatched))

    # write diagnostic file
    out = {
        "fetched_at": None,
        "matched": matched_map,
        "unmatched": [{"batch": b, "策略名称": c.get("策略名称"), "策略ID": c.get("策略ID")} for b, c in unmatched],
        "counts": {"total_cfgs": len(cfgs), "matched": len(matched), "unmatched": len(unmatched)}
    }
    try:
        with open(DIAG_OUT, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"\nDetailed diagnosis written to {DIAG_OUT}")
    except Exception as e:
        print("Failed to write diag output:", e)


if __name__ == "__main__":
    main()