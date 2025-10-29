#!/usr/bin/env python3
# 强制为匹配到且 action=='买卖' 的策略生成 per-strategy draft（跳过日期判断）
# 修正：传入正确的 name_to_code 映射，避免 NoneType 错误。

import json, os, time
from yunfei_ball.yunfei_fetcher import fetch_b_follow, parse_b_follow_page
from yunfei_ball.yunfei_connect_follow import find_strategy_by_id_and_bracket, handle_trade_operation, name_to_code
from collections import defaultdict

ALLOCATION_PATH = os.path.join("../../yunfei_ball", "allocation.json")
SETTING_DIR = os.path.join("../../yunfei_ball", "trade_plan", "setting")
os.makedirs(SETTING_DIR, exist_ok=True)

def extract_action(op_html):
    if not op_html:
        return "继续持有"
    import re
    txt = re.sub(r"<[^>]+>", "", op_html)
    if any(k in txt for k in ("买入", "卖出", "换入", "换出", "调仓")):
        return "买卖"
    if "空仓" in txt:
        return "空仓"
    if "继续持有" in txt:
        return "继续持有"
    return "未知"

def main():
    print("1) 读取 allocation.json ...")
    cfgs = json.load(open(ALLOCATION_PATH, "r", encoding="utf-8"))

    print("2) 抓取网页并解析当前策略 ... (需要登录状态)")
    r = fetch_b_follow(force=True, parse=True)
    if r.get("warning"):
        print("fetch warning:", r["warning"])
    items = r.get("items", [])
    print("  fetched items:", len(items))

    # normalize parse output into legacy structure expected by find_strategy
    strategies = []
    for it in items:
        name = it.get("title") or it.get("name") or ""
        time_str = it.get("time") or ""
        date = time_str.split()[0] if time_str else it.get("date","")
        operation_block = it.get("op_text") or it.get("operation_block") or ""
        holding_block = []
        for h in it.get("holdings", []):
            if isinstance(h, dict):
                hname = h.get("name","")
                pct = h.get("pct")
                if pct is None:
                    holding_block.append(hname)
                else:
                    holding_block.append(f"{hname}：{pct}%")
            else:
                holding_block.append(str(h))
        strategies.append({
            "name": name,
            "date": date,
            "time": time_str,
            "operation_block": operation_block,
            "holding_block": holding_block,
            "_raw": it
        })

    batched = defaultdict(list)
    for cfg in cfgs:
        batched[cfg.get("交易批次", 1)].append(cfg)

    total_generated = 0
    SAMPLE_ACCOUNT_AMOUNT = 680000
    for batch_no, cfgs_in in batched.items():
        for cfg in cfgs_in:
            s = find_strategy_by_id_and_bracket(cfg, strategies)
            if not s:
                print(f"[跳过] 未匹配到策略: {cfg.get('策略名称')}")
                continue
            action = extract_action(s.get("operation_block",""))
            if action != "买卖":
                print(f"[跳过] 匹配到但非买卖动作: {cfg.get('策略名称')} -> action={action}")
                continue
            config_amount = cfg.get("配置仓位", 0)
            sample_amount = round(config_amount * SAMPLE_ACCOUNT_AMOUNT/100, 2)
            print(f"[生成草稿] {cfg.get('策略名称')} (batch {batch_no}) sample_amount={sample_amount}")
            try:
                # 使用模块级 name_to_code（非 None）
                draft = handle_trade_operation(s.get("operation_block"), name_to_code, batch_no, config_amount, sample_amount, strategy_id=cfg.get("策略ID"))
                print("  draft:", draft)
                total_generated += 1
            except Exception as e:
                print("  生成草稿失败:", e)
    print(f"完成。共尝试生成草稿: {total_generated} 个。请查看 {SETTING_DIR} 目录下的结果。")

if __name__ == '__main__':
    main()