import os
import json
import hashlib
import time
from yunfei_ball.tradeplan_io import (
    list_strategy_files, read_json, atomic_write_json, mark_processed, file_lock_for
)

def merge_tradeplans(account_id: str, batch: int, setting_dir: str):
    """
    读取 setting_dir 中匹配 batch 的 per-strategy draft 文件并合并为一个 merged draft 文件。
    返回 merged_draft_path 或 None（无文件）。
    合并策略：简单合并 sell_stocks_info 与 buy_stocks_info 列表（保留来源 merged_from）。
    建议后续对合并进行 netting/去重/权重处理。
    """
    pattern_batch = f"batch{batch}"
    files = []
    try:
        for fn in os.listdir(setting_dir):
            if fn.endswith('.json') and fn.startswith('yunfei_trade_plan_draft_batch') and pattern_batch in fn and 'merged' not in fn:
                files.append(os.path.join(setting_dir, fn))
    except Exception:
        files = []

    files.sort()
    if not files:
        return None

    merged = {"sell_stocks_info": [], "buy_stocks_info": [], "meta": {"merged_from": [], "batch_no": batch, "created_at": time.strftime('%Y-%m-%dT%H:%M:%S')}}
    # 读每个文件（加锁读取）
    for f in files:
        try:
            with file_lock_for(f):
                obj = read_json(f)
            merged['sell_stocks_info'].extend(obj.get('sell_stocks_info', []))
            merged['buy_stocks_info'].extend(obj.get('buy_stocks_info', []))
            merged['meta']['merged_from'].append(os.path.basename(f))
        except Exception as e:
            # 读取单个文件失败不影响其它文件
            print(f"警告：读取 draft 文件 {f} 失败：{e}")

    # 生成 merged 文件名（包含 hash）
    merged_hash = hashlib.sha1(json.dumps(merged, sort_keys=True).encode()).hexdigest()[:8]
    ts = time.strftime('%Y%m%dT%H%M%S')
    merged_filename = f"yunfei_trade_plan_draft_batch{batch}_merged_{ts}_{merged_hash}.json"
    merged_path = os.path.join(setting_dir, merged_filename)

    # 原子写 merged 文件（加锁）
    with file_lock_for(merged_path):
        atomic_write_json(merged_path, merged)

    # 归档已处理的 per-strategy 草稿
    for f in files:
        try:
            mark_processed(f)
        except Exception:
            pass

    print(f"已生成合并后的草稿: {merged_path}")
    return merged_path