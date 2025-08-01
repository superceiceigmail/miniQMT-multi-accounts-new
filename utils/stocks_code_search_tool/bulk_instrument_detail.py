import os
import json
import time
from xtquant import xtdata

def save_instrument_detail(stock_code, data, save_dir):
    # 路径必须与下方main里save_dir完全一致
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, f"{stock_code}.json")
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def code_range(start, end, suffix):
    for code in range(start, end + 1):
        yield f"{code:06d}.{suffix}"

def main():
    save_dir = "utils\stocks_code_search_tool\stocks_data/all_stocks_info"  # 路径名称保持和你已有文件夹完全一致
    error_log = []
    name_vs_code_path = os.path.join("utils\stocks_code_search_tool\stocks_data", "name_vs_code.json")
    # 先尝试读取已存在的 name_vs_code.json，支持断点续跑
    if os.path.exists(name_vs_code_path):
        with open(name_vs_code_path, "r", encoding="utf-8") as f:
            name_vs_code = json.load(f)
    else:
        name_vs_code = {}

    # 需要覆盖的全部区间
    code_ranges = [
        (600001, 605599, "SH"),   # 沪市主板
        (1, 3816, "SZ"),        # 深市主板
        (688001, 688999, "SH"),  # 沪市科创板
        (300001, 300999, "SZ"),  # 深市创业板
        (159001, 159999, "SZ"),   # 深市ETF
        (160001, 169999, "SZ"),   # 深市LOF
        (500001, 509999, "SH"),   # 沪市LOF
        (510001, 519999, "SH"),   # 沪市ETF
        (580001, 589999, "SH"),   # 沪市其他基金
        (900001, 900999, "SH"),   # 沪市B股
        (200001, 201999, "SZ"),   # 深市B股及部分基金
    ]

    update_count = 0
    BATCH_SAVE = 100

    for start, end, suffix in code_ranges:
        for code in code_range(start, end, suffix):
            try:
                data = xtdata.get_instrument_detail(code)
                if data and isinstance(data, dict) and data.get("InstrumentID"):
                    save_instrument_detail(code, data, save_dir)
                    name = data.get("InstrumentName", "")
                    if name and code not in name_vs_code:
                        name_vs_code[code] = name
                        update_count += 1
                        if update_count % BATCH_SAVE == 0:
                            with open(name_vs_code_path, "w", encoding="utf-8") as f:
                                json.dump(name_vs_code, f, ensure_ascii=False, indent=2)
                            print(f"Batch saved name_vs_code.json ({update_count} new names)")
                    print(f"Saved {code} {name}")
            except Exception as e:
                error_log.append((code, str(e)))
                print(f"Error {code}: {e}")
            time.sleep(0.005)

    # 最后再保存一次 name_vs_code.json
    with open(name_vs_code_path, "w", encoding="utf-8") as f:
        json.dump(name_vs_code, f, ensure_ascii=False, indent=2)

    if error_log:
        with open(os.path.join(save_dir, "error_log.txt"), "w", encoding="utf-8") as f:
            for code, err in error_log:
                f.write(f"{code}\t{err}\n")
        print(f"Some errors occurred. See {os.path.join(save_dir, 'error_log.txt')}")

if __name__ == "__main__":
    main()