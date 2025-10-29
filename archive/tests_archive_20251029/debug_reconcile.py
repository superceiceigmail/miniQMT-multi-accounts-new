# debug_reconcile.py
# 调试 reconcile_account：调用并打印完整返回（并把 items 与结果保存到文件）
import json
from yunfei_ball.yunfei_login import login
from yunfei_ball.yunfei_fetcher import fetch_b_follow
from yunfei_ball.yunfei_reconcile import reconcile_account

def main():
    print("1) 短速抓取 items...")
    r = fetch_b_follow(force=True, parse=True)
    print("fetch warning:", r.get("warning"))
    items = r.get("items", [])
    print("items count:", len(items))
    with open("debug_out_items.json", "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print("saved items -> debug_out_items.json (first 5):")
    print(json.dumps(items[:5], ensure_ascii=False, indent=2))

    print("\n2) 尝试 login() 获取 session（若需要）...")
    session = login(username=None)
    print("login session:", bool(session))

    print("\n3) 调用 reconcile_account(...) 并保存完整返回到 debug_reconcile_result.json")
    try:
        # 调用与 GUI 相同签名（若 reconcile_account 支持 session 参数，可改为传 session）
        res = reconcile_account(account='test_account', account_snapshot=None, xt_trader=None, username=None, force_fetch=True, cache_ttl=0)
    except TypeError:
        # 若签名不同，尝试把 session 传入
        try:
            res = reconcile_account(session=session, account='test_account', force_fetch=True)
        except Exception as e:
            print("调用 reconcile_account 异常:", e)
            raise
    print("reconcile result keys:", list(res.keys()) if isinstance(res, dict) else type(res))
    with open("debug_reconcile_result.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print("saved reconcile result -> debug_reconcile_result.json")
    print("\nPreview of result:")
    print(json.dumps(res, ensure_ascii=False, indent=2)[:4000])

if __name__ == '__main__':
    main()