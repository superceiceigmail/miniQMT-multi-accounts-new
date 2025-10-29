import sys
import pathlib
import os
import json
from datetime import datetime
from decimal import Decimal

# 确保项目根在 sys.path（从 scripts 目录运行也能正确导入 gui 包）
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from gui.reconcile_report import generate_reconcile_report

def convert_decimals(obj):
    # 递归把 Decimal 转为 float（便于 JSON 序列化）
    if isinstance(obj, Decimal):
        try:
            return float(obj)
        except Exception:
            return str(obj)
    if isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_decimals(i) for i in obj]
    return obj

def atomic_write_json(path, data, indent=2, ensure_ascii=False):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=ensure_ascii, indent=indent)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def main(account_id="8886006288", require_today=False, out_dir="reconcile_reports"):
    report = generate_reconcile_report(account_id, require_today=require_today)
    report_conv = convert_decimals(report)

    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    filename = f"reconcile_{account_id}_{ts}.json"
    out_path = os.path.join(out_dir, filename)

    atomic_write_json(out_path, report_conv)
    print(f"已保存对账报告到: {out_path}")

if __name__ == "__main__":
    # 若需用其它 account 或只看今日，可在命令行修改这两行
    main(account_id="8886006288", require_today=False)