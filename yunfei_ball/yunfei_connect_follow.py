# yunfei_ball/yunfei_connect_follow.py
# 已调整：在 parse 后对策略项进行 normalize，访问字段改为 .get，修正 sample_amount 计算等。

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

def load_name_to_code_map(json_path):
    if not os.path.exists(json_path):
        print(f"错误：代码索引文件未找到于 {json_path}")
        return {}
    with open(json_path, 'r', encoding='utf-8') as f:
        code_map = json.load(f)
    name_to_code = {}
    for code, namelist in code_map.items():
        if len(code) == 6:
            code_with_sh = code + ".SH"
        else:
            code_with_sh = code
        for name in namelist:
            if name not in name_to_code:
                name_to_code[name] = code_with_sh
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

def handle_trade_operation(op_block_html, name_to_code, batch_no, ratio, sample_amount, strategy_id=None):
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
        strategy_id=strategy_id
    )
    print("已生成交易计划草稿:", draft_plan_file_path, flush=True)
    return draft_plan_file_path

name_to_code = load_name_to_code_map(CODE_INDEX_PATH)

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
    print(f"批次{batch_no}任务已启动, 目标时间: {batch_time}, 当前时间: {datetime.now()}, 策略数: {len(batch_cfgs)}", flush=True)

    if hasattr(account, "account_id"):
        account_id_str = getattr(account, "account_id")
    else:
        account_id_str = config.get('account_id', 'unknown')

    today_str = datetime.now().strftime('%Y-%m-%d')
    today_date = datetime.strptime(today_str, '%Y-%m-%d').date()
    session = None
    max_retries = 10
    retry_count = 0

    batch_status_at_start = load_batch_status(account_id_str)
    if batch_status_at_start.get(str(batch_no)):
        print(f"批次{batch_no}今日已执行（账户 {account_id_str}），跳过。", flush=True)
        return

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

            if not is_logged_in(resp.text):
                print("登录失效，重新登录...", flush=True)
                session = None
                while session is None:
                    session = login()
                    if session is None:
                        print("无法登录，15秒后重试", flush=True)
                        time.sleep(15)
                continue

            # ------------ parse and normalize -------------
            strategies_raw = parse_b_follow_page(resp.text)

            try:
                strategies = normalize_strategies(strategies_raw)
            except Exception as e_norm:
                print("normalize_strategies 失败:", e_norm, flush=True)
                # fallback: best-effort convert
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

            # write debug sample to file to assist troubleshooting
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

            # sanity keys print
            try:
                sample_keys = [list(s.keys()) for s in strategies[:8]]
                print("Parsed strategies sample keys:", sample_keys, flush=True)
            except Exception:
                pass

            # ------------ end parse / normalize -------------
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
                                                                      config_amount, sample_amount, strategy_id=strat_id)
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
                    print(f"策略【{s.get('name','(unknown)')}】日期: {s.get('date','')} < 今日日期: {today_str}，尚未更新...", flush=True)

            if all_cfgs_checked:
                print(f"批次{batch_no}所有策略信息已更新到今日或未来，开始合并并生成最终交易计划。", flush=True)
                setting_dir = os.path.join(os.path.dirname(__file__), "trade_plan", "setting")
                try:
                    expected_n = len([cfg for cfg in batch_cfgs if cfg])
                except Exception:
                    expected_n = None
                wait_for_drafts(setting_dir, batch_no, expected_count=expected_n, timeout=30, poll_interval=0.5)

                merged_draft = merge_tradeplans(account_id_str, batch_no, setting_dir)
                if not merged_draft:
                    print("未发现任何策略草稿，跳过生成最终交易计划。", flush=True)
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
            # 将详细异常写入 debug 便于后续分析
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