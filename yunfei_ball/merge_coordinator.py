import os
import json
import hashlib
import time
from .tradeplan_io import (
    list_strategy_files, read_json, atomic_write_json, mark_processed, file_lock_for
)

def merge_tradeplans(account_id: str, batch: int, setting_dir: str):
    """
    读取 setting_dir 中匹配 batch 的 per-strategy draft 文件并合并为一个 merged draft 文件。
    按 account_id 过滤（如果 account_id 为 None 则回退到按 batch 合并）。
    即使没有任何 per-strategy 草稿文件，也会生成一个空的 merged 草稿（meta.empty=True）。
    返回 merged_draft_path 或 None（写入失败时）。
    """
    pattern_batch = f"batch{batch}"
    files = []
    try:
        for fn in os.listdir(setting_dir):
            if fn.endswith('.json') and fn.startswith('yunfei_trade_plan_draft_batch') and pattern_batch in fn and 'merged' not in fn:
                if account_id:
                    # 只有包含 acct{account_id} 的文件才归属于此账户
                    if f"acct{account_id}" not in fn:
                        continue
                files.append(os.path.join(setting_dir, fn))
    except Exception:
        files = []

    files.sort()

    merged = {
        "sell_stocks_info": [],
        "buy_stocks_info": [],
        "meta": {
            "merged_from": [],
            "batch_no": batch,
            "account_id": account_id,
            "created_at": time.strftime('%Y-%m-%dT%H:%M:%S'),
            "empty": False
        }
    }

    # 读每个文件（加锁读取）
    for f in files:
        try:
            with file_lock_for(f):
                obj = read_json(f)
            merged['sell_stocks_info'].extend(obj.get('sell_stocks_info', []))
            merged['buy_stocks_info'].extend(obj.get('buy_stocks_info', []))
            merged['meta']['merged_from'].append(os.path.basename(f))
        except Exception as e:
            print(f"警告：读取 draft 文件 {f} 失败：{e}", flush=True)

    if not merged['meta']['merged_from']:
        merged['meta']['empty'] = True

    merged_hash = hashlib.sha1(json.dumps(merged, sort_keys=True).encode()).hexdigest()[:8]
    ts = time.strftime('%Y%m%dT%H%M%S')
    acct_part = f"_acct{account_id}" if account_id else ""
    empty_part = "_empty" if merged['meta'].get('empty') else ""
    merged_filename = f"yunfei_trade_plan_draft_batch{batch}_merged{acct_part}{empty_part}_{ts}_{merged_hash}.json"
    merged_path = os.path.join(setting_dir, merged_filename)

    try:
        with file_lock_for(merged_path):
            atomic_write_json(merged_path, merged)
    except Exception as e:
        print(f"错误：写入 merged 草稿失败: {e}", flush=True)
        return None

    # 归档已处理的 per-strategy 草稿（在移动前加锁，避免并发 mark）
    for f in files:
        try:
            with file_lock_for(f):
                mark_processed(f)
        except Exception:
            pass

    print(f"已生成合并后的草稿: {merged_path}", flush=True)
    return merged_path