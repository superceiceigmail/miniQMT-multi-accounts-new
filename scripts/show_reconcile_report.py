# scripts/show_reconcile_report.py （顶部加入下列三行）
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


import json
from decimal import Decimal
from gui.reconcile_report import generate_reconcile_report

def convert(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: convert(v) for k,v in obj.items()}
    if isinstance(obj, list):
        return [convert(i) for i in obj]
    return obj

if __name__ == "__main__":
    account_id = "8886006288"
    report = generate_reconcile_report(account_id, require_today=False)
    print(json.dumps(convert(report), ensure_ascii=False, indent=2))