# show_alloc_encoding.py
# 尝试用常见编码解码 yunfei_ball/allocation.json 并显示能否被 json.loads 正确解析
from pathlib import Path
import json

p = Path("../yunfei_ball/allocation.json")
if not p.exists():
    print("文件不存在：", p)
    raise SystemExit(1)

b = p.read_bytes()
candidates = ["utf-8", "utf-8-sig", "gb18030", "gbk", "latin1"]
for enc in candidates:
    try:
        s = b.decode(enc)
        print(f"\n--- decode with {enc} ---")
        # show head (escape newlines)
        print(s[:600].replace("\n", "\\n"))
        try:
            j = json.loads(s)
            if isinstance(j, list) and len(j) > 0:
                print("json.loads OK. first entry keys:", list(j[0].keys()))
            else:
                print("json.loads OK but not a non-empty list (or empty). type:", type(j))
        except Exception as e:
            print("json.loads failed:", e)
    except Exception as e:
        print(f"decode with {enc} failed: {e}")