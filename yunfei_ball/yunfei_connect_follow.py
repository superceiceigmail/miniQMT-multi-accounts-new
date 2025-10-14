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
        for name in namelist:
            if name not in name_to_code:
                name_to_code[name] = code
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


def fetch_and_check_batch_with_trade_plan(batch_no, batch_time, batch_cfgs, config, account_asset_info, positions,
                                          generate_trade_plan_final_func):
    print(f"批次{batch_no}任务已启动, 目标时间: {batch_time}, 当前时间: {datetime.now()}, 策略数: {len(batch_cfgs)}", flush=True)

    today_str = datetime.now().strftime('%Y-%m-%d')
    today_date = datetime.strptime(today_str, '%Y-%m-%d').date()
    session = None
    max_retries = 10
    retry_count = 0

    batch_status_at_start = load_batch_status()
    if batch_status_at_start.get(str(batch_no)):
        print(f"批次{batch_no}今日已执行，跳过。")
        return

    # --- 新增去重字典 ---
    processed_strategy_keys = set()

    while session is None and retry_count < max_retries:
        session = login()
        if session is None:
            print(f"无法登录，{15}秒后重试 ({retry_count + 1}/{max_retries})")
            time.sleep(15)
            retry_count += 1

    if session is None:
        print(f"达到最大重试次数，批次{batch_no}任务失败退出。")
        return

    while True:
        try:
            resp = session.get(BASE_URL + '/F2/b_follow.aspx', headers=HEADERS, timeout=10, proxies={})
            resp.encoding = resp.apparent_encoding

            if not is_logged_in(resp.text):
                print("登录失效，重新登录...")
                session = None
                while session is None:
                    session = login()
                    if session is None:
                        print("无法登录，15秒后重试")
                        time.sleep(15)
                continue

            strategies = parse_b_follow_page(resp.text)
            all_cfgs_checked = True

            for cfg in batch_cfgs:
                s = find_strategy_by_id_and_bracket(cfg, strategies)
                if not s:
                    print(f"策略【{cfg['策略名称']}】未找到！")
                    all_cfgs_checked = False
                    continue

                strategy_date_str = s['date']
                try:
                    strategy_date = datetime.strptime(strategy_date_str, '%Y-%m-%d').date()
                except ValueError:
                    all_cfgs_checked = False
                    print(f"策略【{s['name']}】日期格式错误: {strategy_date_str}，跳过检查。")
                    continue

                # --- 构造唯一键避免重复处理 ---
                strategy_key = f"{cfg.get('策略ID','')}_{strategy_date_str}"
                # 只有第一次满足条件才处理
                if strategy_date >= today_date and strategy_key not in processed_strategy_keys:
                    print(f"策略【{s['name']}】 操作日期: {s['date']} >= 今日日期: {today_str}")
                    action = extract_operation_action(s['operation_block'])
                    if action == '买卖':
                        config_amount = cfg.get('配置仓位', 0)
                        sample_amount = round(config_amount * SAMPLE_ACCOUNT_AMOUNT, 2)

                        print(f"\n>>> 策略【{s['name']}】 操作时间: {s['time']}")
                        draft_plan_file_path = handle_trade_operation(s['operation_block'], name_to_code, batch_no,
                                                                      config_amount, sample_amount)
                        print(f"配置仓位: {config_amount}，样板操作金额: {sample_amount}")
                        print("当前持仓:")
                        for h in s['holding_block']:
                            print("  " + h)
                        print("==============")

                        trade_date = datetime.now().strftime('%Y-%m-%d')
                        account_id = config.get('account_id', 'unknown')
                        final_trade_plan_file = f"{TRADE_PLAN_DIR}/yunfei_trade_plan_final_{account_id}_{trade_date}_batch{batch_no}.json"

                        generate_trade_plan_final_func(
                            config=config,
                            account_asset_info=account_asset_info,
                            positions=positions,
                            trade_date=trade_date,
                            setting_file_path=draft_plan_file_path,
                            trade_plan_file=final_trade_plan_file
                        )
                        print("生成最终交易计划完毕:")
                        processed_strategy_keys.add(strategy_key)
                    else:
                        print(f"策略【{s['name']}】操作为{action}，跳过")
                        processed_strategy_keys.add(strategy_key)
                elif strategy_date >= today_date:
                    # 已处理过，直接跳过
                    continue
                else:
                    all_cfgs_checked = False
                    print(f"策略【{s['name']}】日期: {s['date']} < 今日日期: {today_str}，尚未更新...")

            if all_cfgs_checked:
                print(f"批次{batch_no}所有策略信息已更新到今日或未来，任务完成。")
                batch_status = load_batch_status()
                batch_status[str(batch_no)] = True
                save_batch_status(batch_status)
                break

            print("本批次部分策略还未更新到今日或未来，30秒后重试")
            time.sleep(30)

        except SSLError as e:
            print("遇到SSL错误:", e)
            kill_and_reset_geph()
            time.sleep(15)
            session = None
            while session is None:
                session = login()
                if session is None:
                    print("无法登录，15秒后重试")
                    time.sleep(15)
        except Exception as e:
            print("抓取异常", e)
            print("30秒后重试")
            time.sleep(30)

# ... 此处省略其他未改变的辅助函数 (load_batch_status, save_batch_status, login, etc.)
# ...
# ...
# ...
# 【为了简洁，以下辅助函数代码保持原样，无需修改】
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
    except Exception:
        data = {}
    data[today] = batch_status
    with open(BATCH_STATUS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


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


# 【修正】collect_today_strategies 采用 >= today_date 的逻辑
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
    strategies = parse_b_follow_page(resp.text)
    today_str = datetime.now().strftime('%Y-%m-%d')
    today_date = datetime.strptime(today_str, '%Y-%m-%d').date()
    print("\n==================== 今日策略汇总 ====================")
    for batch in sorted(batch_dict.keys()):
        print(f"\n#### 交易批次 {batch}")
        for cfg in batch_dict[batch]:
            s = find_strategy_by_id_and_bracket(cfg, strategies)
            name = cfg['策略名称']
            if not s:
                print(f"策略【{name}】未找到！")
                continue

            # 【核心修正】：判断策略更新日期是否为当日或晚于当日
            strategy_date_str = s.get('date', '')
            is_updated = False
            if strategy_date_str:
                try:
                    strategy_date = datetime.strptime(strategy_date_str, '%Y-%m-%d').date()
                    if strategy_date >= today_date:
                        is_updated = True
                except ValueError:
                    pass

            # 【修正】当日期 >= 今日 且 操作是买卖，则生成draft文件
            if is_updated and extract_operation_action(s['operation_block']) == '买卖':
                config_amount = cfg.get('配置仓位', 0)
                # 【修正】统一 sample_amount 的计算方式
                sample_amount = round(config_amount * SAMPLE_ACCOUNT_AMOUNT, 2)
                handle_trade_operation(s['operation_block'], name_to_code, batch, config_amount, sample_amount)
                print(f"  配置仓位: {config_amount}，样板操作金额: {sample_amount}")

            # 【修正】打印更新日期
            print(f"【{name}】更新日期: {strategy_date_str}，当前持仓:")
            if s['holding_block']:
                for h in s['holding_block']:
                    print("  " + h)
            else:
                print("  （无持仓信息）")
    print("\n==================== 汇总结束 ========================")


if __name__ == '__main__':
    collect_today_strategies()