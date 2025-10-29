# yunfei_ball/yunfei_connect_follow.py
# 已调整：主/从账号分离 fetch 行为 —— 非主账号在 use_master_fetch 模式下不再登录云飞，
# 并在收到主账号发布的 merged 草稿后检查 meta.empty，若为 True 则直接结束本批次。
import os
import sys
import time
import requests
import re
import json
import threading
import subprocess
import glob
import random
import shutil
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from collections import defaultdict
from requests.exceptions import SSLError

# 相对导入包内模块（现在都在 yunfei_ball 下）
from .generate_trade_plan_draft import generate_trade_plan_draft_func
from .merge_coordinator import merge_tradeplans

from utils.asset_helpers import positions_to_dict, account_asset_to_tuple

# 新：从拆分模块导入
from .yunfei_login import login, is_logged_in
from .yunfei_fetcher import parse_b_follow_page, fetch_b_follow

# 适配器
from .parse_adapter import normalize_strategies

# ---------- 固定主账号 ID（按你的要求写死） ----------
MASTER_ACCOUNT_ID = "8886006288"

USERNAME = 'ceicei'  # 保留以兼容旧逻辑
PASSWORD = 'ceicei628'
LOGIN_URL = 'https://www.ycyflh.com/F2/login.aspx'
BASE_URL = 'https://www.ycyflh.com'
INPUT_JSON = os.path.join(os.path.dirname(__file__), "allocation.json")
PENDING_BATCHES_BASE_DIR = os.path.join(os.path.dirname(__file__), "pending_batches_by_account")
CODE_INDEX_PATH = os.path.join(os.path.dirname(__file__), "code_index.json")
TRADE_PLAN_DIR = os.path.join(os.path.dirname(__file__), "trade_plan")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
}

SAMPLE_ACCOUNT_AMOUNT = 680000

# -------------------- fetch_cache 写盘 helpers --------------------
def _ensure_fetch_cache_dir():
    base = os.path.join(os.path.dirname(__file__), "fetch_cache")
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:
        pass
    return base

def _ts_to_filename(ts_iso: str):
    if not ts_iso:
        ts_iso = datetime.utcnow().isoformat()
    tsfn = ts_iso.replace(":", "").replace("-", "").replace("T", "_")
    tsfn = re.sub(r'[+\-]\d{2}(\d{2})?$', '', tsfn)
    tsfn = tsfn.split(".")[0]
    return tsfn

def _save_parsed_artifacts(strategies_raw, strategies_norm, html=None, ts_iso=None):
    base = _ensure_fetch_cache_dir()
    ts_iso = ts_iso or datetime.utcnow().isoformat()
    tsfn = _ts_to_filename(ts_iso)
    if html is not None:
        try:
            html_path = os.path.join(base, f"html_{tsfn}.html")
            with open(html_path, "w", encoding="utf-8") as fh:
                fh.write(html)
        except Exception:
            pass
        try:
            with open(os.path.join(base, "latest_html.html"), "w", encoding="utf-8") as fh:
                fh.write(html)
        except Exception:
            pass
    try:
        raw_path = os.path.join(base, f"strategies_raw_{tsfn}.json")
        with open(raw_path, "w", encoding="utf-8") as fr:
            json.dump(strategies_raw, fr, ensure_ascii=False, indent=2)
    except Exception:
        pass
    try:
        with open(os.path.join(base, "latest_strategies_raw.json"), "w", encoding="utf-8") as fr:
            json.dump(strategies_raw, fr, ensure_ascii=False, indent=2)
    except Exception:
        pass
    try:
        norm_path = os.path.join(base, f"strategies_normalized_{tsfn}.json")
        with open(norm_path, "w", encoding="utf-8") as fn:
            json.dump(strategies_norm, fn, ensure_ascii=False, indent=2)
    except Exception:
        pass
    try:
        with open(os.path.join(base, "latest_strategies_normalized.json"), "w", encoding="utf-8") as fn:
            json.dump(strategies_norm, fn, ensure_ascii=False, indent=2)
    except Exception:
        pass

# -------------------- end helpers --------------------

def load_name_to_code_map(json_path):
    if not os.path.exists(json_path):
        print(f"错误：代码索引文件未找到于 {json_path}")
        return {}
    with open(json_path, 'r', encoding='utf-8') as f:
        code_map = json.load(f)
    name_to_code = {}
    for code, namelist in code_map.items():
        code_str = str(code).strip()
        code_with_suffix = code_str
        if len(code_str) == 6 and code_str.isdigit():
            first = code_str[0]
            if first in ('5', '6'):
                code_with_suffix = code_str + ".SH"
            elif first == '1':
                code_with_suffix = code_str + ".SZ"
            else:
                code_with_suffix = code_str + ".SH"
        for name in namelist:
            if name not in name_to_code:
                name_to_code[name] = code_with_suffix
    return name_to_code

def add_code_to_operation(operation_text, name_to_code):
    def repl(m):
        action = m.group(1)
        asset = m.group(2)
        code = name_to_code.get(asset)
        if code:
            return f"{action} {asset}({code})"
        else:
            return f"{action} {asset}"
    return re.sub(r'(买入|卖出|调仓|换入|换出)\s*([^\s;\uff1b\uff0c,.]+)', repl, operation_text)

def handle_trade_operation(op_block_html, name_to_code, batch_no, ratio, sample_amount, strategy_id=None, account_id=None):
    op_text = BeautifulSoup(op_block_html, 'lxml').get_text()
    op_text_with_code = add_code_to_operation(op_text, name_to_code or {})
    print("买卖操作明细：", flush=True)
    print(op_text_with_code, flush=True)
    time.sleep(random.uniform(0.1, 0.5))
    draft_plan_file_path = generate_trade_plan_draft_func(
        batch_no,
        op_text_with_code,
        ratio,
        sample_amount,
        output_dir=os.path.join(os.path.dirname(__file__), "trade_plan", "setting"),
        strategy_id=strategy_id,
        account_id=account_id
    )
    print("已生成交易计划草稿:", draft_plan_file_path, flush=True)
    return draft_plan_file_path

name_to_code = load_name_to_code_map(CODE_INDEX_PATH)

# -------------------- 主/从账号共享发布目录（用于 master fetch 模式） --------------------
def _ensure_shared_publish_dir():
    base = os.path.join(os.path.dirname(__file__), "trade_plan", "shared")
    os.makedirs(base, exist_ok=True)
    return base

def publish_master_merged(merged_path: str, batch_no: int, master_id: str):
    shared = _ensure_shared_publish_dir()
    try:
        try:
            dst_copy = os.path.join(shared, os.path.basename(merged_path))
            shutil.copy2(merged_path, dst_copy)
        except Exception:
            dst_copy = merged_path
        pointer = {
            "merged_path": dst_copy,
            "batch_no": batch_no,
            "master_id": master_id,
            "published_at": datetime.now().isoformat()
        }
        pointer_path = os.path.join(shared, f"batch{batch_no}_merged_acct{master_id}.json")
        tmp = pointer_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(pointer, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, pointer_path)
        return pointer_path
    except Exception as e:
        print(f"发布 master merged 失败: {e}", flush=True)
        return None

def wait_for_master_merged(batch_no: int, master_id: str, timeout: int = 120, poll_interval: float = 1.0):
    shared = _ensure_shared_publish_dir()
    pointer_path = os.path.join(shared, f"batch{batch_no}_merged_acct{master_id}.json")
    start = time.time()
    while time.time() - start < timeout:
        if os.path.exists(pointer_path):
            try:
                with open(pointer_path, "r", encoding="utf-8") as f:
                    j = json.load(f)
                merged_path = j.get("merged_path")
                if merged_path and os.path.exists(merged_path):
                    return merged_path
                if merged_path:
                    return merged_path
            except Exception as e:
                print(f"读取 master pointer 失败：{e}", flush=True)
        time.sleep(poll_interval)
    return None

def is_merged_empty(merged_path: str) -> bool:
    """
    读取 merged draft 文件并判断 meta.empty（容错：读取失败返回 False，避免误判）
    """
    if not merged_path:
        return False
    try:
        with open(merged_path, 'r', encoding='utf-8') as f:
            j = json.load(f)
        meta = j.get('meta') or {}
        return bool(meta.get('empty', False))
    except Exception:
        return False

# -------------------- end shared publish helpers --------------------

def delayed_run(delay, *args, **kwargs):
    print(f"[delayed_run] Will run batch after {delay} seconds", flush=True)
    time.sleep(delay)
    fetch_and_check_batch_with_trade_plan(*args, **kwargs)

def monitor_timers(timers, timer_info_list):
    while any(t.is_alive() for t in timers):
        alive_count = sum(1 for t in timers if t.is_alive())
        print(f"\n[定时任务监控] 当前有 {alive_count} 个批次任务正在运行/等待。", flush=True)
        time.sleep(30)
    print("[定时任务监控] 所有定时任务已完成。", flush=True)

def get_batch_file(account_id: str) -> str:
    try:
        os.makedirs(PENDING_BATCHES_BASE_DIR, exist_ok=True)
    except Exception:
        fallback_dir = os.path.dirname(__file__)
        return os.path.join(fallback_dir, f"pending_batches_{account_id}.json")
    filename = f"pending_batches_{account_id}.json"
    return os.path.join(PENDING_BATCHES_BASE_DIR, filename)

def load_batch_status(account_id: str):
    today = datetime.now().strftime("%Y-%m-%d")
    path = get_batch_file(account_id)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get(today, {})
    except Exception:
        return {}

def save_batch_status(account_id: str, batch_status):
    today = datetime.now().strftime("%Y-%m-%d")
    path = get_batch_file(account_id)
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = {}
    except Exception:
        data = {}
    data[today] = batch_status
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def wait_for_drafts(setting_dir, batch_no, expected_count=None, timeout=30, poll_interval=0.5):
    pattern = os.path.join(setting_dir, f"yunfei_trade_plan_draft_batch{batch_no}_*.json")
    start = time.time()
    while True:
        files = sorted([f for f in glob.glob(pattern) if 'merged' not in os.path.basename(f)])
        if expected_count is not None:
            if len(files) >= expected_count:
                return files
        else:
            if time.time() - start >= timeout:
                return files
        if time.time() - start >= timeout:
            return files
        time.sleep(poll_interval)

def fetch_and_check_batch_with_trade_plan(
    batch_no, batch_time, batch_cfgs, config, account_asset_info, positions,
    generate_trade_plan_final_func, xt_trader, account
):
    """
    支持 use_master_fetch 模式：若启用且当前 account 不是 master（MASTER_ACCOUNT_ID），则不再登录/抓取云飞页面，
    而是等待 master 发布 merged 草稿（trade_plan/shared）。
    若 merged.meta.empty==True，则从账号直接短路标记批次完成，不生成 final plan。
    """
    print(f"批次{batch_no}任务已启动, 目标时间: {batch_time}, 当前时间: {datetime.now()}, 策略数: {len(batch_cfgs)}", flush=True)

    if hasattr(account, "account_id"):
        account_id_str = getattr(account, "account_id")
    else:
        account_id_str = config.get('account_id', 'unknown')

    # use_master 可由 config 控制，master id 固定为 MASTER_ACCOUNT_ID
    use_master = bool(config.get('use_master_fetch', True))
    master_id = MASTER_ACCOUNT_ID
    master_wait_timeout = int(config.get('master_wait_timeout', 180))
    #超时后自己去抓
    master_fallback_to_local_merge = bool(config.get('master_fallback_to_local_merge', True))

    today_str = datetime.now().strftime('%Y-%m-%d')
    today_date = datetime.strptime(today_str, '%Y-%m-%d').date()
    session = None
    max_retries = 10
    retry_count = 0

    batch_status_at_start = load_batch_status(account_id_str)
    if batch_status_at_start.get(str(batch_no)):
        print(f"批次{batch_no}今日已执行（账户 {account_id_str}），跳过。", flush=True)
        return

    # 如果启用 master 模式并且当前不是 master，直接等待 master 发布 merged 草稿
    if use_master and master_id and account_id_str != master_id:
        print(f"当前账号 {account_id_str} 为从账号（use_master_fetch 模式），将等待主账号 {master_id} 发布合并草稿（超时 {master_wait_timeout}s）", flush=True)
        merged_from_master = wait_for_master_merged(batch_no, master_id, timeout=master_wait_timeout)
        if not merged_from_master:
            print(f"[超时] 等待主账号合并草稿超时（batch {batch_no}）。", flush=True)
            if master_fallback_to_local_merge:
                print("配置允许回退到本地合并，尝试自行合并（此过程会进行本账号登录并抓取页面）", flush=True)
            else:
                print("不回退，标记本批次已完成并退出。", flush=True)
                batch_status = load_batch_status(account_id_str)
                batch_status[str(batch_no)] = True
                save_batch_status(account_id_str, batch_status)
                return
        else:
            print(f"已从主账号获取到合并草稿: {merged_from_master}", flush=True)
            # 如果 merged 文件被标注为空（empty），直接短路结束，不生成 final plan
            if is_merged_empty(merged_from_master):
                print(f"合并草稿标注为 empty（本批次无交易），账号 {account_id_str} 将标记完成并退出。", flush=True)
                batch_status = load_batch_status(account_id_str)
                batch_status[str(batch_no)] = True
                save_batch_status(account_id_str, batch_status)
                return

            # 否则继续用该 merged_draft 生成最终交易计划并执行
            merged_draft = merged_from_master
            trade_date = datetime.now().strftime('%Y-%m-%d')
            final_trade_plan_file = os.path.join(
                TRADE_PLAN_DIR,
                f"yunfei_trade_plan_final_{account_id_str}_{trade_date}_batch{batch_no}.json"
            )
            try:
                fresh_account_info = None
                fresh_positions = None
                try:
                    fresh_account_info = xt_trader.query_stock_asset(account)
                    fresh_positions = xt_trader.query_stock_positions(account)
                    print("已获取实时账户与持仓，用于生成最终交易计划。", flush=True)
                except Exception as e_query:
                    print(f"警告：查询实时账户/持仓失败，继续使用传入快照: {e_query}", flush=True)

                setting_file_path = merged_draft
                if fresh_account_info is not None and fresh_positions is not None:
                    fresh_account_tuple = account_asset_to_tuple(fresh_account_info)
                    fresh_positions_list = positions_to_dict(fresh_positions)
                    generate_trade_plan_final_func(
                        config=config,
                        account_asset_info=fresh_account_tuple,
                        positions=fresh_positions_list,
                        trade_date=trade_date,
                        setting_file_path=setting_file_path,
                        trade_plan_file=final_trade_plan_file
                    )
                else:
                    positions_list = positions_to_dict(positions)
                    generate_trade_plan_final_func(
                        config=config,
                        account_asset_info=account_asset_info,
                        positions=positions_list,
                        trade_date=trade_date,
                        setting_file_path=setting_file_path,
                        trade_plan_file=final_trade_plan_file
                    )

                print("生成最终交易计划完毕（从主账号合并草稿）:", flush=True)

                try:
                    with open(final_trade_plan_file, 'r', encoding='utf-8') as f:
                        trade_plan = json.load(f)
                except Exception as e_read:
                    print(f"读取最终交易计划失败: {e_read}", flush=True)
                    batch_status = load_batch_status(account_id_str)
                    batch_status[str(batch_no)] = True
                    save_batch_status(account_id_str, batch_status)
                    return

                print(f"将要执行的最终交易计划: {json.dumps(trade_plan, ensure_ascii=False)}", flush=True)

                try:
                    from processor.trade_plan_execution import execute_trade_plan
                    from filelock import FileLock
                    lock_dir = os.path.join(os.path.dirname(__file__), "runtime", "locks")
                    os.makedirs(lock_dir, exist_ok=True)
                    lock_path = os.path.join(lock_dir, f"account_{account_id_str}.lock")
                    with FileLock(lock_path, timeout=5):
                        print("开始执行 SELL 阶段（会提交卖单）...", flush=True)
                        execute_trade_plan(xt_trader, account, trade_plan, action='sell')
                        print("SELL 阶段已发出委托（异步），等待回调并刷新账户...", flush=True)
                        time.sleep(10.0)
                        try:
                            refreshed_account_info = xt_trader.query_stock_asset(account)
                            refreshed_positions = xt_trader.query_stock_positions(account)
                            print("已刷新执行后实时账户与持仓。", flush=True)
                            print(f"刷新后可用资金: {getattr(refreshed_account_info,'m_dCash', 'N/A')}", flush=True)
                        except Exception as e_refresh:
                            print(f"刷新执行后账户持仓失败: {e_refresh}", flush=True)
                            refreshed_account_info = None
                            refreshed_positions = None

                        # -------------- 新增：刷新后将实时数据写入本地快照（保证文件与实际一致） --------------
                        try:
                            # 尝试优先使用现有的保存工具（asset_connector / position_connector）
                            try:
                                from asset_connector import print_account_asset as _print_account_asset
                                from position_connector import print_positions as _print_positions
                            except Exception:
                                _print_account_asset = None
                                _print_positions = None

                            if _print_account_asset is not None:
                                try:
                                    # _print_account_asset 会使用 trader 查询并写入 account_data/assets/asset_{account}.json
                                    _print_account_asset(xt_trader, account_id_str)
                                    print(f"已将实时资产写入本地快照 for {account_id_str}", flush=True)
                                except Exception as e_w:
                                    print(f"写入资产快照失败: {e_w}", flush=True)
                            else:
                                print("未找到 asset_connector.print_account_asset，跳过保存资产快照", flush=True)

                            if _print_positions is not None:
                                try:
                                    # _print_positions 会使用 trader 查询并写入 account_data/positions/position_{account}.json
                                    _print_positions(xt_trader, account_id_str, {}, None)
                                    print(f"已将实时持仓写入本地快照 for {account_id_str}", flush=True)
                                except Exception as e_p:
                                    print(f"写入持仓快照失败: {e_p}", flush=True)
                            else:
                                print("未找到 position_connector.print_positions，跳过保存持仓快照", flush=True)
                        except Exception as e_save_all:
                            print(f"保存快照过程中出现异常: {e_save_all}", flush=True)
                        # -------------- 新增结束 --------------------------------------------------

                        print("开始执行 BUY 阶段（会提交买单）...", flush=True)
                        execute_trade_plan(xt_trader, account, trade_plan, action='buy')
                        print("BUY 阶段已发出委托（异步）。", flush=True)
                    batch_status = load_batch_status(account_id_str)
                    batch_status[str(batch_no)] = True
                    save_batch_status(account_id_str, batch_status)
                except Exception as e_exec:
                    print(f"自动执行交易计划失败: {e_exec}", flush=True)
                    batch_status = load_batch_status(account_id_str)
                    batch_status[str(batch_no)] = True
                    save_batch_status(account_id_str, batch_status)
            except Exception as e_gen:
                print(f"生成/执行最终交易计划失败: {e_gen}", flush=True)
                batch_status = load_batch_status(account_id_str)
                batch_status[str(batch_no)] = True
                save_batch_status(account_id_str, batch_status)
            return

    # ----------------- 下面是 master 或回退到本地合并时的原有逻辑（需要登录并抓取页面） -----------------
    processed_strategy_keys = set()
    draft_files_for_batch = []

    while session is None and retry_count < max_retries:
        session = login()
        if session is None:
            print(f"无法登录，{15}秒后重试 ({retry_count + 1}/{max_retries})", flush=True)
            time.sleep(15)
            retry_count += 1

    if session is None:
        print(f"达到最大重试次数，批次{batch_no}任务失败退出。", flush=True)
        return

    while True:
        try:
            resp = session.get(BASE_URL + '/F2/b_follow.aspx', headers=HEADERS, timeout=10, proxies={})
            resp.encoding = resp.apparent_encoding
            html = resp.text

            if not is_logged_in(html):
                print("登录失效，重新登录...", flush=True)
                session = None
                while session is None:
                    session = login()
                    if session is None:
                        print("无法登录，15秒后重试", flush=True)
                        time.sleep(15)
                continue

            strategies_raw = parse_b_follow_page(html)

            try:
                strategies = normalize_strategies(strategies_raw)
            except Exception as e_norm:
                print("normalize_strategies 失败:", e_norm, flush=True)
                strategies = []
                for it in (strategies_raw or []):
                    if not isinstance(it, dict):
                        strategies.append({
                            'name': str(it),
                            'date': '',
                            'time': '',
                            'operation_block': '',
                            'holding_block': []
                        })
                        continue
                    name = it.get('name') or it.get('title') or ''
                    time_str = it.get('time') or ''
                    date = (time_str.split()[0] if time_str else it.get('date') or '')
                    operation_block = it.get('operation_block') or it.get('op_text') or it.get('operation_html') or ''
                    holding_block = []
                    raw_holdings = it.get('holding_block') or it.get('holding') or it.get('holdings') or []
                    if isinstance(raw_holdings, str):
                        parts = [p.strip() for p in re.split(r'[\n;；,，/]', raw_holdings) if p.strip()]
                        holding_block.extend(parts)
                    elif isinstance(raw_holdings, list):
                        for h in raw_holdings:
                            if isinstance(h, dict):
                                hname = h.get('name','')
                                pct = h.get('pct') or h.get('percentage')
                                if pct is None:
                                    holding_block.append(hname)
                                else:
                                    holding_block.append(f"{hname}：{pct}%")
                            else:
                                holding_block.append(str(h))
                    else:
                        if raw_holdings:
                            holding_block.append(str(raw_holdings))
                    strategies.append({
                        'name': name,
                        'date': date,
                        'time': time_str,
                        'operation_block': operation_block,
                        'holding_block': holding_block,
                        '_raw': it
                    })

            try:
                dbg_path = os.path.join(os.path.dirname(__file__), 'debug_parsed_strategies.json')
                with open(dbg_path, 'w', encoding='utf-8') as f_dbg:
                    json.dump({
                        'fetched_at': datetime.now().isoformat(),
                        'strategies_raw_sample': (strategies_raw[:12] if isinstance(strategies_raw, list) else strategies_raw),
                        'strategies_normalized_sample': strategies[:12]
                    }, f_dbg, ensure_ascii=False, indent=2)
                print("Parsed strategies saved to", dbg_path, flush=True)
            except Exception as e_dump:
                print("写 debug_parsed_strategies.json 失败:", e_dump, flush=True)

            try:
                ts_iso = datetime.now().isoformat()
                _save_parsed_artifacts(strategies_raw, strategies, html=html, ts_iso=ts_iso)
                print("Full parsed strategies and html dumped to fetch_cache/", flush=True)
            except Exception as e_save:
                print("保存 full parsed strategies 失败:", e_save, flush=True)

            try:
                sample_keys = [list(s.keys()) for s in strategies[:8]]
                print("Parsed strategies sample keys:", sample_keys, flush=True)
            except Exception:
                pass

            all_cfgs_checked = True
            time.sleep(5)

            for cfg in batch_cfgs:
                s = find_strategy_by_id_and_bracket(cfg, strategies)
                if not s:
                    print(f"策略【{cfg.get('策略名称')}】未找到！", flush=True)
                    all_cfgs_checked = False
                    continue

                strategy_date_str = s.get('date','')
                try:
                    strategy_date = datetime.strptime(strategy_date_str, '%Y-%m-%d').date()
                except ValueError:
                    all_cfgs_checked = False
                    print(f"策略【{s.get('name','(unknown)')}】日期格式错误: {strategy_date_str}，跳过检查。", flush=True)
                    continue

                strategy_key = f"{cfg.get('策略ID','')}_{strategy_date_str}"
                if strategy_date >= today_date and strategy_key not in processed_strategy_keys:
                    print(f"策略【{s.get('name','(unknown)')}】 操作日期: {s.get('date','') } >= 今日日期: {today_str}", flush=True)
                    action = extract_operation_action(s.get('operation_block',''))
                    if action == '买卖':
                        config_amount = cfg.get('配置仓位', 0)
                        sample_amount = round(config_amount * SAMPLE_ACCOUNT_AMOUNT/100, 2)

                        print(f"\n>>> 策略【{s.get('name','(unknown)')}】 操作时间: {s.get('time','')}", flush=True)
                        strat_id = cfg.get('策略ID', None)
                        draft_plan_file_path = handle_trade_operation(s.get('operation_block',''), name_to_code, batch_no,
                                                                      config_amount, sample_amount, strategy_id=strat_id, account_id=account_id_str)
                        print(f"配置仓位: {config_amount}，样板操作金额: {sample_amount}", flush=True)
                        print("当前持仓:")
                        for h in s.get('holding_block', []):
                            print("  " + h, flush=True)
                        print("==============", flush=True)

                        if draft_plan_file_path:
                            draft_files_for_batch.append(draft_plan_file_path)

                        trade_date = datetime.now().strftime('%Y-%m-%d')
                        if hasattr(account, "account_id"):
                            account_id_str = getattr(account, "account_id")
                        else:
                            account_id_str = config.get('account_id', 'unknown')

                        processed_strategy_keys.add(strategy_key)
                    else:
                        print(f"策略【{s.get('name','(unknown)')}】操作为{action}，跳过", flush=True)
                        processed_strategy_keys.add(strategy_key)
                elif strategy_date >= today_date:
                    continue
                else:
                    all_cfgs_checked = False
                    print(f"策略【{s.get('name','(unknown)')}】日期: {s.get('date')} < 今日日期: {today_str}，尚未更新...", flush=True)

            if all_cfgs_checked:
                print(f"批次{batch_no}所有策略信息已更新到今日或未来，开始合并并生成最终交易计划。", flush=True)
                setting_dir = os.path.join(os.path.dirname(__file__), "trade_plan", "setting")
                try:
                    expected_n = len([cfg for cfg in batch_cfgs if cfg])
                except Exception:
                    expected_n = None
                wait_for_drafts(setting_dir, batch_no, expected_count=expected_n, timeout=30, poll_interval=0.5)

                merged_draft = merge_tradeplans(account_id_str, batch_no, setting_dir)

                # 主账号合并后发布（如果启用 master 模式）
                if merged_draft and use_master and master_id and account_id_str == master_id:
                    try:
                        publish_master_merged(merged_draft, batch_no, master_id)
                        print(f"主账号已发布合并草稿: {merged_draft}", flush=True)
                    except Exception as e:
                        print(f"发布合并草稿失败: {e}", flush=True)

                if not merged_draft:
                    print("未发现任何策略草稿，跳过生成最终交易计划。", flush=True)
                    batch_status = load_batch_status(account_id_str)
                    batch_status[str(batch_no)] = True
                    save_batch_status(account_id_str, batch_status)
                    break

                # 若 merged 标注为 empty，短路并标记批次完成
                if is_merged_empty(merged_draft):
                    print(f"合并草稿为 empty（本批次无交易），账号 {account_id_str} 将标记完成并退出。", flush=True)
                    batch_status = load_batch_status(account_id_str)
                    batch_status[str(batch_no)] = True
                    save_batch_status(account_id_str, batch_status)
                    break

                final_trade_plan_file = os.path.join(
                    TRADE_PLAN_DIR,
                    f"yunfei_trade_plan_final_{account_id_str}_{trade_date}_batch{batch_no}.json"
                )

                try:
                    fresh_account_info = None
                    fresh_positions = None
                    try:
                        fresh_account_info = xt_trader.query_stock_asset(account)
                        fresh_positions = xt_trader.query_stock_positions(account)
                        print("已获取实时账户与持仓，用于生成最终交易计划。", flush=True)
                    except Exception as e_query:
                        print(f"警告：查询实时账户/持仓失败，继续使用传入快照: {e_query}", flush=True)

                    setting_file_path = merged_draft
                    if fresh_account_info is not None and fresh_positions is not None:
                        fresh_account_tuple = account_asset_to_tuple(fresh_account_info)
                        fresh_positions_list = positions_to_dict(fresh_positions)
                        generate_trade_plan_final_func(
                            config=config,
                            account_asset_info=fresh_account_tuple,
                            positions=fresh_positions_list,
                            trade_date=trade_date,
                            setting_file_path=setting_file_path,
                            trade_plan_file=final_trade_plan_file
                        )
                    else:
                        positions_list = positions_to_dict(positions)
                        generate_trade_plan_final_func(
                            config=config,
                            account_asset_info=account_asset_info,
                            positions=positions_list,
                            trade_date=trade_date,
                            setting_file_path=setting_file_path,
                            trade_plan_file=final_trade_plan_file
                        )

                    print("生成最终交易计划完毕:", flush=True)

                    try:
                        with open(final_trade_plan_file, 'r', encoding='utf-8') as f:
                            trade_plan = json.load(f)
                    except Exception as e_read:
                        print(f"读取最终交易计划失败: {e_read}", flush=True)
                        batch_status = load_batch_status(account_id_str)
                        batch_status[str(batch_no)] = True
                        save_batch_status(account_id_str, batch_status)
                        break

                    print(f"将要执行的最终交易计划: {json.dumps(trade_plan, ensure_ascii=False)}", flush=True)

                    try:
                        from processor.trade_plan_execution import execute_trade_plan
                        from filelock import FileLock
                        lock_dir = os.path.join(os.path.dirname(__file__), "runtime", "locks")
                        os.makedirs(lock_dir, exist_ok=True)
                        lock_path = os.path.join(lock_dir, f"account_{account_id_str}.lock")
                        with FileLock(lock_path, timeout=5):
                            print("开始执行 SELL 阶段（会提交卖单）...", flush=True)
                            execute_trade_plan(xt_trader, account, trade_plan, action='sell')
                            print("SELL 阶段已发出委托（异步），等待回调并刷新账户...", flush=True)
                            time.sleep(10.0)
                            try:
                                refreshed_account_info = xt_trader.query_stock_asset(account)
                                refreshed_positions = xt_trader.query_stock_positions(account)
                                print("已刷新执行后实时账户与持仓。", flush=True)
                                print(f"刷新后可用资金: {getattr(refreshed_account_info,'m_dCash', 'N/A')}", flush=True)
                            except Exception as e_refresh:
                                print(f"刷新执行后账户持仓失败: {e_refresh}", flush=True)
                                refreshed_account_info = None
                                refreshed_positions = None

                            # -------------- 新增：刷新后将实时数据写入本地快照（保证文件与实际一致） --------------
                            try:
                                # 尝试优先使用现有的保存工具（asset_connector / position_connector）
                                try:
                                    from asset_connector import print_account_asset as _print_account_asset
                                    from position_connector import print_positions as _print_positions
                                except Exception:
                                    _print_account_asset = None
                                    _print_positions = None

                                if _print_account_asset is not None:
                                    try:
                                        _print_account_asset(xt_trader, account_id_str)
                                        print(f"已将实时资产写入本地快照 for {account_id_str}", flush=True)
                                    except Exception as e_w:
                                        print(f"写入资产快照失败: {e_w}", flush=True)
                                else:
                                    print("未找到 asset_connector.print_account_asset，跳过保存资产快照", flush=True)

                                if _print_positions is not None:
                                    try:
                                        _print_positions(xt_trader, account_id_str, {}, None)
                                        print(f"已将实时持仓写入本地快照 for {account_id_str}", flush=True)
                                    except Exception as e_p:
                                        print(f"写入持仓快照失败: {e_p}", flush=True)
                                else:
                                    print("未找到 position_connector.print_positions，跳过保存持仓快照", flush=True)
                            except Exception as e_save_all:
                                print(f"保存快照过程中出现异常: {e_save_all}", flush=True)
                            # -------------- 新增结束 --------------------------------------------------

                            print("开始执行 BUY 阶段（会提交买单）...", flush=True)
                            execute_trade_plan(xt_trader, account, trade_plan, action='buy')
                            print("BUY 阶段已发出委托（异步）。", flush=True)
                        batch_status = load_batch_status(account_id_str)
                        batch_status[str(batch_no)] = True
                        save_batch_status(account_id_str, batch_status)
                    except Exception as e_exec:
                        print(f"自动执行交易计划失败: {e_exec}", flush=True)
                        batch_status = load_batch_status(account_id_str)
                        batch_status[str(batch_no)] = True
                        save_batch_status(account_id_str, batch_status)
                except Exception as e_gen:
                    print(f"生成/执行最终交易计划失败: {e_gen}", flush=True)
                    batch_status = load_batch_status(account_id_str)
                    batch_status[str(batch_no)] = True
                    save_batch_status(account_id_str, batch_status)
                break

            print("本批次部分策略还未更新到今日或未来，20秒后重试", flush=True)
            time.sleep(20)

        except SSLError as e:
            print("遇到SSL错误:", e, flush=True)
            kill_and_reset_geph()
            time.sleep(15)
            session = None
            while session is None:
                session = login()
                if session is None:
                    print("无法登录，15秒后重试", flush=True)
                    time.sleep(15)
        except Exception as e:
            print("抓取异常", e, flush=True)
            try:
                err_path = os.path.join(os.path.dirname(__file__), "debug_fetch_exception.txt")
                with open(err_path, "a", encoding="utf-8") as ef:
                    ef.write(f"{datetime.now().isoformat()} - fetch exception: {repr(e)}\n")
            except Exception:
                pass
            print("30秒后重试", flush=True)
            time.sleep(30)

def extract_operation_action(op_html):
    if not op_html: return '继续持有'
    text = BeautifulSoup(op_html, 'lxml').get_text()
    if '买入' in text or '卖出' in text or '换入' in text or '换出' in text or '调仓' in text:
        return '买卖'
    if '空仓' in text:
        return '空仓'
    if '继续持有' in text:
        return '继续持有'
    return '未知'

def get_bracket_content(s):
    m = re.search(r"(?:\(|（)(.*?)(?:\)|）)", s)
    return m.group(1).strip() if m else ""

def find_strategy_by_id_and_bracket(cfg, strategies):
    json_name = cfg.get('策略名称','').strip()
    json_id = str(cfg.get('策略ID', '')).strip()
    for s in strategies:
        web_full_name = (s.get('name') or '').strip()
        if web_full_name.endswith(json_name) and json_name:
            return s
    if not json_id:
        return None
    json_id_prefix = json_id[:-1] if len(json_id) > 1 else json_id
    json_bracket = get_bracket_content(json_name)
    for s in strategies:
        web_full_name = (s.get('name') or '').strip()
        id_match = re.search(r"L?(\d+):", web_full_name)
        if not id_match:
            continue
        web_id = id_match.group(1)
        if web_id.startswith(json_id_prefix):
            web_bracket = get_bracket_content(web_full_name)
            if json_bracket and web_bracket and json_bracket == web_bracket:
                return s
    return None

def collect_today_strategies():
    with open(INPUT_JSON, 'r', encoding='utf-8') as f:
        strategy_cfgs = json.load(f)
    batch_dict = defaultdict(list)
    for cfg in strategy_cfgs:
        batch = cfg.get("交易批次", 1)
        batch_dict[batch].append(cfg)
    session = login()
    if not session:
        print("无法登录，无法汇总今日策略信息")
        return
    try:
        resp = session.get(BASE_URL + '/F2/b_follow.aspx', headers=HEADERS, timeout=10, proxies={})
        resp.encoding = resp.apparent_encoding
    except Exception as e:
        print("拉取策略页面失败：", e)
        return
    strategies_raw = parse_b_follow_page(resp.text)
    try:
        strategies = normalize_strategies(strategies_raw)
    except Exception:
        strategies = strategies_raw if isinstance(strategies_raw, list) else []
    today_str = datetime.now().strftime('%Y-%m-%d')
    today_date = datetime.strptime(today_str, '%Y-%m-%d').date()
    print("\n==================== 今日策略汇总 ====================")
    for batch in sorted(batch_dict.keys()):
        print(f"\n#### 交易批次 {batch}")
        for cfg in batch_dict[batch]:
            s = find_strategy_by_id_and_bracket(cfg, strategies)
            name = cfg.get('策略名称')
            if not s:
                print(f"策略【{name}】未找到！")
                continue
            strategy_date_str = s.get('date', '')
            is_updated = False
            if strategy_date_str:
                try:
                    strategy_date = datetime.strptime(strategy_date_str, '%Y-%m-%d').date()
                    if strategy_date >= today_date:
                        is_updated = True
                except ValueError:
                    pass
            if is_updated and extract_operation_action(s.get('operation_block','')) == '买卖':
                config_amount = cfg.get('配置仓位', 0)
                sample_amount = round(config_amount * SAMPLE_ACCOUNT_AMOUNT/100, 2)
                handle_trade_operation(s.get('operation_block',''), name_to_code, batch, config_amount, sample_amount, strategy_id=cfg.get('策略ID'))
                print(f"  配置仓位: {config_amount}，样板操作金额: {sample_amount}")
            print(f"【{name}】更新日期: {strategy_date_str}，当前持仓:")
            if s.get('holding_block'):
                for h in s.get('holding_block', []):
                    print("  " + h)
            else:
                print("  （无持仓信息）")
    print("\n==================== 汇总结束 ========================")

def kill_and_reset_geph():
    try:
        print("检测到SSL错误，尝试关闭迷雾通及重置系统代理！")
        for proc in ["geph4-client.exe", "gephgui-wry.exe", "geph4.exe"]:
            subprocess.run(['taskkill', '/F', '/IM', proc], check=False)
        subprocess.run('netsh winhttp reset proxy', shell=True)
        subprocess.run(
            'reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" /v ProxyServer /f',
            shell=True)
        subprocess.run(
            'reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" /v ProxyEnable /f',
            shell=True)
        print("已关闭所有 geph 进程并重置系统代理设置")
    except Exception as e:
        print("关闭 geph 或重置代理失败:", e, flush=True)

if __name__ == '__main__':
    collect_today_strategies()