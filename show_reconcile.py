# show_reconcile.py
# Safe JSON dump for reconcile_for_account results: convert Decimal -> float
import json
from gui.reconcile_ui import reconcile_for_account
from decimal import Decimal

def convert_decimals(obj):
    # recursively convert Decimal to float
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

account_id = "8886006288"
try:
    res = reconcile_for_account(account_id)
    res_conv = convert_decimals(res)
    print(json.dumps(res_conv, ensure_ascii=False, indent=2))
except Exception as e:
    print("reconcile_for_account 抛出异常:", e)
    raise