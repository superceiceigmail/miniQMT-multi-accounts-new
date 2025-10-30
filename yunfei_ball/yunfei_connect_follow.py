#!/usr/bin/env python3
# yunfei_ball/yunfei_connect_follow.py
# 负责从云飞页面抓取策略、生成草稿、合并并生成最终交易计划，以及（可选）自动执行
import os
import sys
import time
import requests
import re
import json
import threading
import subprocess
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from collections import defaultdict
from requests.exceptions import SSLError

from yunfei_ball.generate_trade_plan_draft import generate_trade_plan_draft_func
from utils.asset_helpers import positions_to_dict, account_asset_to_tuple

USERNAME = 'ceicei'
PASSWORD = 'ceicei628'
LOGIN_URL = 'https://www.ycyflh.com/F2/login.aspx'
BASE_URL = 'https://www.ycyflh.com'
INPUT_JSON = os.path.join(os.path.dirname(__file__), "allocation.json")
BATCH_STATUS_FILE = os.path.join(os.path.dirname(__file__), "pending_batches.json")
CODE_INDEX_PATH = os.path.join(os.path.dirname(__file__), "code_index.json")
TRADE_PLAN_DIR = os.path.join(os.path.dirname(__file__), "trade_plan")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
}

SAMPLE_ACCOUNT_AMOUNT = 730000


def load_name_to_code_map(json_path):
    if not os.path.exists(json_path):
        print(f"错误：代码索引文件未找到于 {json_path}")
        return {}
    with open(json_path, 'r', encoding='utf-8') as f:
        code_map = json.load(f)
    name_to_code = {}
    for code, namelist in code_map.items():
        # 自动补全 .SH
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


def handle_trade_operation(op_block_html, name_to_code, batch_no, ratio, sample_amount):
    op_text = BeautifulSoup(op_block_html, 'lxml').get_text()
    op_text_with_code = add_code_to_operation(op_text, name_to_code)
    print("买卖操作明细：")
    print(op_text_with_code)
    draft_plan_file_path = generate_trade_plan_draft_func(batch_no, op_text_with_code, ratio, sample_amount,
                                                          output_dir="yunfei_ball/setting")
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


# ------------------- 新增：合并草稿日期校验工具 -------------------
def _extract_date_from_draft_filename(path: str):
    """
    从文件名中提取 YYYYMMDD 部分并返回 'YYYY-MM-DD'，找不到则返回 None。
    期望的文件名样式例如: ..._20251029T105339_...json
    """
    if not path:
        return None
    try:
        m = re.search(r'_(\d{8})T\d{6}', os.path.basename(path))
        if not m:
            return None
        d = m.group(1)  # e.g. '20251029'
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    except Exception:
        return None


def _is_draft_for_trade_date(draft_path: str, trade_date: str) -> bool:
    """
    校验 draft_path 是否对应 trade_date（'YYYY-MM-DD'）。
    优先使用文件名中的时间戳；若文件名无时间戳则尝试读取 json 内的 plan_date 字段；
    最后回退到文件修改时间（文件 mtime）。
    """
    try:
        # 1) 从文件名提取
        fn_date = _extract_date_from_draft_filename(draft_path)
        if fn_date:
            return fn_date == trade_date

        # 2) 文件内 plan_date 字段
        if os.path.exists(draft_path):
            try:
                with open(draft_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                plan_date = data.get('plan_date') or data.get('trade_date') or None
                if isinstance(plan_date, str) and plan_date:
                    # 兼容 'YYYYMMDD' 或 'YYYY-MM-DD'
                    if re.match(r'^\d{8}$', plan_date):
                        plan_date = f"{plan_date[:4]}-{plan_date[4:6]}-{plan_date[6:]}"
                    return plan_date == trade_date
            except Exception:
                # 忽略解析错误，继续下一步回退机制
                pass

        # 3) 回退到文件修改时间（mtime）
        if os.path.exists(draft_path):
            mtime = os.path.getmtime(draft_path)
            file_date = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')
            return file_date == trade_date

    except Exception:
        pass

    return False
# ------------------- 新增结束 -------------------


def fetch_and_check_batch_with_trade_plan(
    batch_no, batch_time, batch_cfgs, config, account_asset_info, positions,
    generate_trade_plan_final_func, xt_trader, account
):
    """
    批次任务主逻辑：
    - 定时从云飞抓取策略页面
    - 对满足条件（date >= today 且 操作为买卖）的策略生成 draft
    - 使用实时持仓/资金（优先）或传入 snapshot 生成最终 trade_plan 并保存到 TRADE_PLAN_DIR
    - 可选：自动执行（先卖后买）
    """
    print(f"批次{batch_no}任务已启动, 目标时间: {batch_time}, 当前时间: {datetime.now()}, 策略数: {len(batch_cfgs)}", flush=True)

    today_str = datetime.now().strftime('%Y-%m-%d')
    today_date = datetime.strptime(today_str, '%Y-%m-%d').date()
    session = None
    max_retries = 10
    retry_count = 0

    batch_status_at_start = load_batch_status()
    if batch_status_at_start.get(str(batch_no)):
        print(f"批次{batch_no}今日已执行，跳过。", flush=True)
        return

    # --- 新增去重字典 ---
    processed_strategy_keys = set()

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

            strategies = parse_b_follow_page(resp.text)
            all_cfgs_checked = True
            time.sleep(5)

            for cfg in batch_cfgs:
                s = find_strategy_by_id_and_bracket(cfg, strategies)
                if not s:
                    print(f"策略【{cfg['策略名称']}】未找到！", flush=True)
                    all_cfgs_checked = False
                    continue

                strategy_date_str = s['date']
                try:
                    strategy_date = datetime.strptime(strategy_date_str, '%Y-%m-%d').date()
                except ValueError:
                    all_cfgs_checked = False
                    print(f"策略【{s['name']}】日期格式错误: {strategy_date_str}，跳过检查。", flush=True)
                    continue

                # --- 构造唯一键避免重复处理 ---
                strategy_key = f"{cfg.get('策略ID','')}_{strategy_date_str}"
                # 只有第一次满足条件才处理
                if strategy_date >= today_date and strategy_key not in processed_strategy_keys:
                    print(f"策略【{s['name']}】 操作日期: {s['date']} >= 今日日期: {today_str}", flush=True)
                    action = extract_operation_action(s['operation_block'])
                    if action == '买卖':
                        config_amount = cfg.get('配置仓位', 0)
                        sample_amount = round(config_amount * SAMPLE_ACCOUNT_AMOUNT, 2)

                        print(f"\n>>> 策略【{s['name']}】 操作时间: {s['time']}", flush=True)
                        draft_plan_file_path = handle_trade_operation(s['operation_block'], name_to_code, batch_no,
                                                                      config_amount, sample_amount)
                        print(f"配置仓位: {config_amount}，样板操作金额: {sample_amount}", flush=True)
                        print("当前持仓:")
                        for h in s['holding_block']:
                            print("  " + h, flush=True)
                        print("==============", flush=True)

                        trade_date = datetime.now().strftime('%Y-%m-%d')
                        # 优先使用 account 对象的 id（如果接收到的是 StockAccount）
                        if hasattr(account, "account_id"):
                            account_id_str = getattr(account, "account_id")
                        else:
                            account_id_str = config.get('account_id', 'unknown')

                        # 使用统一且明确的路径（包含 batch 编号）
                        final_trade_plan_file = os.path.join(
                            TRADE_PLAN_DIR,
                            f"yunfei_trade_plan_final_{account_id_str}_{trade_date}_batch{batch_no}.json"
                        )

                        # --- 重要：校验 draft 文件是否为当日草稿，避免误用过期合并草稿 ---
                        if not _is_draft_for_trade_date(draft_plan_file_path, trade_date):
                            print(f"警告：忽略过期或日期不匹配的草稿文件（{draft_plan_file_path}），期待日期: {trade_date}", flush=True)
                            # 标记已处理，避免重复尝试同一策略的过期草稿；也可选择不标记以继续等待
                            processed_strategy_keys.add(strategy_key)
                            continue

                        # 尝试使用最新持仓/资金生成 final plan（优先）
                        try:
                            fresh_account_info = None
                            fresh_positions = None
                            try:
                                fresh_account_info = xt_trader.query_stock_asset(account)
                                fresh_positions = xt_trader.query_stock_positions(account)
                                print("已获取实时账户与持仓，用于生成最终交易计划。", flush=True)
                            except Exception as e_query:
                                print(f"警告：查询实时账户/持仓失败，继续使用传入快照: {e_query}", flush=True)

                            if fresh_account_info is not None and fresh_positions is not None:
                                # 转换 fresh_account_info -> tuple（print_trade_plan 期望的格式）
                                fresh_account_tuple = account_asset_to_tuple(fresh_account_info)
                                # 转换 fresh_positions -> list[dict]
                                fresh_positions_list = positions_to_dict(fresh_positions)
                                generate_trade_plan_final_func(
                                    config=config,
                                    account_asset_info=fresh_account_tuple,
                                    positions=fresh_positions_list,
                                    trade_date=trade_date,
                                    setting_file_path=draft_plan_file_path,
                                    trade_plan_file=final_trade_plan_file
                                )
                            else:
                                # 退回使用传入的 snapshot（注意：main 已把 snapshot转换过，但这里以防）
                                positions_list = positions_to_dict(positions)
                                generate_trade_plan_final_func(
                                    config=config,
                                    account_asset_info=account_asset_info,
                                    positions=positions_list,
                                    trade_date=trade_date,
                                    setting_file_path=draft_plan_file_path,
                                    trade_plan_file=final_trade_plan_file
                                )
                        except Exception as e_gen:
                            print(f"生成最终交易计划失败: {e_gen}", flush=True)
                            processed_strategy_keys.add(strategy_key)
                            continue

                        print("生成最终交易计划完毕:", flush=True)

                        # ====== 自动执行：改为先卖出再买入（确保卖单被提交并释放资金） ======
                        try:
                            with open(final_trade_plan_file, 'r', encoding='utf-8') as f:
                                trade_plan = json.load(f)
                        except Exception as e_read:
                            print(f"读取最终交易计划失败: {e_read}", flush=True)
                            processed_strategy_keys.add(strategy_key)
                            continue

                        # 打印计划，方便核验
                        print(f"将要执行的最终交易计划: {json.dumps(trade_plan, ensure_ascii=False)}", flush=True)

                        try:
                            from processor.trade_plan_execution import execute_trade_plan

                            # ===== 卖出阶段 =====
                            print("开始执行 SELL 阶段（会提交卖单）...", flush=True)
                            execute_trade_plan(xt_trader, account, trade_plan, action='sell')
                            print("SELL 阶段已发出委托（异步），等待回调并刷新账户...", flush=True)

                            # 等待一段时间让异步委托回调到来并稍作缓冲
                            time.sleep(10.0)

                            # 刷新实时账户/持仓，获取卖出回笼后的可用资金与可售数量
                            try:
                                refreshed_account_info = xt_trader.query_stock_asset(account)
                                refreshed_positions = xt_trader.query_stock_positions(account)
                                print("已刷新执行后实时账户与持仓。", flush=True)
                                print(f"刷新后可用资金: {getattr(refreshed_account_info,'m_dCash', 'N/A')}", flush=True)
                            except Exception as e_refresh:
                                print(f"刷新执行后账户持仓失败: {e_refresh}", flush=True)
                                refreshed_account_info = None
                                refreshed_positions = None

                            # ===== 买入阶段 =====
                            print("开始执行 BUY 阶段（会提交买单）...", flush=True)
                            execute_trade_plan(xt_trader, account, trade_plan, action='buy')
                            print("BUY 阶段已发出委托（异步）。", flush=True)

                        except Exception as e_exec:
                            print(f"自动执行交易计划失败: {e_exec}", flush=True)

                        processed_strategy_keys.add(strategy_key)
                    else:
                        print(f"策略【{s['name']}】操作为{action}，跳过", flush=True)
                        processed_strategy_keys.add(strategy_key)
                elif strategy_date >= today_date:
                    # 已处理过，直接跳过
                    continue
                else:
                    all_cfgs_checked = False
                    print(f"策略【{s['name']}】日期: {s['date']} < 今日日期: {today_str}，尚未更新...", flush=True)

            if all_cfgs_checked:
                print(f"批次{batch_no}所有策略信息已更新到今日或未来，任务完成。", flush=True)
                batch_status = load_batch_status()
                batch_status[str(batch_no)] = True
                save_batch_status(batch_status)
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
            print("30秒后重试", flush=True)
            time.sleep(30)


# ----------------- 以下为辅助函数，保持原样 -----------------
def get_value_by_name(soup, name):
    tag = soup.find('input', {'name': name})
    return tag['value'] if tag else ''


def is_logged_in(html_text):
    return ("退出" in html_text or "个人资料" in html_text or "Hi," in html_text)


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
        print("关闭 geph 或重置代理失败:", e)


def login():
    session = requests.Session()
    session.trust_env = False
    session.headers.update(HEADERS)
    try:
        resp = session.get(LOGIN_URL, proxies={})
    except SSLError as e:
        print("遇到SSL错误:", e)
        kill_and_reset_geph()
        time.sleep(5)
        return None
    except Exception as e:
        print("其他网络异常:", e)
        return None
    soup = BeautifulSoup(resp.text, 'html.parser')
    viewstate = get_value_by_name(soup, '__VIEWSTATE')
    eventvalidation = get_value_by_name(soup, '__EVENTVALIDATION')
    viewstategen = get_value_by_name(soup, '__VIEWSTATEGENERATOR')
    data = {
        '__VIEWSTATE': viewstate,
        '__EVENTVALIDATION': eventvalidation,
        '__VIEWSTATEGENERATOR': viewstategen,
        'txt_name_2020_byf': USERNAME,
        'txt_pwd_2020_byf': PASSWORD,
        'ckb_UserAgreement': 'on',
        'btn_login': '登 录',
    }
    try:
        login_resp = session.post(LOGIN_URL, data=data, proxies={})
    except Exception as e:
        print("登录请求异常:", e)
        return None
    if not is_logged_in(login_resp.text):
        print("登录失败，请检查用户名密码或表单字段。")
        return None
    print("登录成功")
    return session


def parse_b_follow_page(html):
    soup = BeautifulSoup(html, 'lxml')
    strategies = []
    for table in soup.find_all('table', {'border': '1'}):
        name = ''
        ttime = ''
        op_block = ''
        holding_block = ''
        th = table.find('th', attrs={'colspan': '2'})
        if not th: continue
        a = th.find('a')
        if a:
            name = a.get_text(strip=True)
        else:
            name = th.get_text(strip=True)
        tds = table.find_all('td', attrs={'colspan': '2'})
        if len(tds) > 0:
            ttime_match = re.search(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]', tds[0].get_text())
            ttime = ttime_match.group(1) if ttime_match else ''
            divs = tds[0].find_all('div')
            if len(divs) > 1:
                op_block = ''.join(str(divs[1]))
            else:
                op_block = tds[0].get_text(separator=' ', strip=True)
        holdings_td = None
        for td in tds:
            if '目前持仓' in td.get_text():
                holdings_td = td
                break
        holding_lines = []
        if holdings_td:
            for line in holdings_td.stripped_strings:
                m = re.match(r'([^\s：:]+)[：:]\s*([\d\.]+)%', line)
                if m:
                    holding_lines.append(f"{m.group(1)}：{m.group(2)}%")
                elif '空仓' in line:
                    holding_lines.append('空仓')
        strategies.append({
            "name": name,
            "date": ttime.split()[0] if ttime else '',
            "time": ttime,
            "operation_block": op_block,
            "holding_block": holding_lines
        })
    return strategies


def extract_operation_action(op_html):
    if not op_html: return '继续持有'
    text = BeautifulSoup(op_html, 'lxml').get_text()
    # 修正：支持“换入/换出”
    if '买入' in text or '卖出' in text or '换入' in text or '换出' in text or '调仓' in text:
        return '买卖'
    if '空仓' in text:
        return '空仓'
    if '继续持有' in text:
        return '继续持有'
    return '未知'


def get_bracket_content(s):
    # 兼容中文和英文括号
    m = re.search(r"(?:\(|（)(.*?)(?:\)|）)", s)
    return m.group(1).strip() if m else ""


# 【最终修正】策略查找逻辑 - 优先使用 endswith，次要使用 ID+括号 匹配
def find_strategy_by_id_and_bracket(cfg, strategies):
    json_name = cfg['策略名称'].strip()  # 确保配置名称没有意外的空格
    json_id = str(cfg.get('策略ID', '')).strip()

    # 1. 最可靠的方法：尝试使用策略名称尾部进行灵活匹配 (忽略ID前缀和空格差异)
    for s in strategies:
        web_full_name = s['name'].strip()

        # 只要网页策略名称的结尾部分与配置中的名称完全一致，就认为是匹配成功
        if web_full_name.endswith(json_name):
            return s

    # 2. 回退到旧版逻辑：使用 ID 前缀和括号内容进行匹配
    if not json_id:
        return None

    # ID 匹配：匹配除了最后一位数字之外的 ID 前缀（旧版逻辑）
    json_id_prefix = json_id[:-1] if len(json_id) > 1 else json_id
    json_bracket = get_bracket_content(json_name)

    for s in strategies:
        # 从网页名称中提取 ID，例如 L105181:
        id_match = re.search(r"L?(\d+):", s['name'])
        if not id_match:
            continue
        web_id = id_match.group(1)

        # 匹配 ID 前缀
        if web_id.startswith(json_id_prefix):
            # 匹配括号内容
            web_bracket = get_bracket_content(s['name'])

            # 只有当括号内容都存在且相等时，才视为匹配成功
            if json_bracket and web_bracket and json_bracket == web_bracket:
                return s
    return None


# ------------- 批次状态存取 -------------
def load_batch_status():
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        with open(BATCH_STATUS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get(today, {})
    except Exception:
        return {}


def save_batch_status(batch_status):
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        if os.path.exists(BATCH_STATUS_FILE):
            with open(BATCH_STATUS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = {}
        data[today] = batch_status
        with open(BATCH_STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存批次状态失败: {e}", flush=True)


if __name__ == '__main__':
    collect = None
    try:
        collect = fetch_and_check_batch_with_trade_plan
    except Exception:
        pass
    # 示例：运行 collect_today_strategies 时会直接打印信息（本模块亦可单独调用 collect_today_strategies）
    # 如果作为脚本直接运行，可调用 collect_today_strategies()