import os
import sys
import time
import random
import requests
import re
import json
import threading
import subprocess
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from collections import defaultdict
from requests.exceptions import SSLError

USERNAME = 'ceicei'
PASSWORD = 'ceicei628'
LOGIN_URL = 'https://www.ycyflh.com/F2/login.aspx'
BASE_URL = 'https://www.ycyflh.com'
INPUT_JSON = 'allocation.json'
BATCH_STATUS_FILE = "pending_batches.json"
CODE_INDEX_PATH = "code_index.json"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
}

SCHEDULE_TIMES = [
    "10:15:00",
    "13:01:05",
    "14:32:00",
    "14:52:05",
]

SAMPLE_ACCOUNT_AMOUNT = 730000  # 样板账号金额

############################
# 代码映射与买卖操作处理函数
############################

def load_name_to_code_map(json_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        code_map = json.load(f)
    name_to_code = {}
    for code, namelist in code_map.items():
        for name in namelist:
            if name not in name_to_code:
                name_to_code[name] = code
    return name_to_code

def add_code_to_operation(operation_text, name_to_code):
    """
    将操作字符串中的证券名称加上代码后缀，如“买入 国债指数;”=>“买入 国债指数(511880);”
    只替换买入/卖出/调仓/换入/换出等常见操作。
    """
    def repl(m):
        action = m.group(1)
        asset = m.group(2)
        code = name_to_code.get(asset)
        if code:
            return f"{action} {asset}({code})"
        else:
            return f"{action} {asset}"
    # 支持中英文分号
    return re.sub(r'(买入|卖出|调仓|换入|换出)\s*([^\s;；，,.]+)', repl, operation_text)

def handle_trade_operation(op_block_html, name_to_code):
    """处理买卖操作，第一步：打印带代码的操作信息（后续对接真实交易）"""
    op_text = BeautifulSoup(op_block_html, 'lxml').get_text()
    op_text_with_code = add_code_to_operation(op_text, name_to_code)
    print("买卖操作明细：")
    print(op_text_with_code)
    # todo: 后续在这里对接真实交易逻辑

# 全局加载代码映射
name_to_code = load_name_to_code_map(CODE_INDEX_PATH)

##########################
# 下面是原有业务逻辑
##########################

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
        with open(BATCH_STATUS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
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
        subprocess.run('reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" /v ProxyServer /f', shell=True)
        subprocess.run('reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" /v ProxyEnable /f', shell=True)
        print("已关闭所有 geph 进程并重置系统代理设置")
    except Exception as e:
        print("关闭 geph 或重置代理失败:", e)

def login():
    session = requests.Session()
    session.trust_env = False  # 禁用系统代理
    session.headers.update(HEADERS)
    try:
        resp = session.get(LOGIN_URL, proxies={})  # 禁用代理
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
    if '买入' in text or '卖出' in text:
        return '买卖'
    if '空仓' in text:
        return '空仓'
    if '继续持有' in text:
        return '继续持有'
    return '未知'

def get_bracket_content(s):
    # 支持中英文括号
    m = re.search(r"(?:\(|（)(.*?)(?:\)|）)", s)
    return m.group(1) if m else ""

def find_strategy_by_id_and_bracket(cfg, strategies):
    json_id = str(cfg['策略ID'])
    json_id_prefix = json_id[:-1] if len(json_id) > 1 else json_id
    json_bracket = get_bracket_content(cfg['策略名称'])
    for s in strategies:
        # 先找ID前缀
        id_match = re.search(r"L?(\d+):", s['name'])
        if not id_match:
            continue
        web_id = id_match.group(1)
        if web_id.startswith(json_id_prefix):
            web_bracket = get_bracket_content(s['name'])
            # 括号内容一致才算同一策略
            if json_bracket and web_bracket and json_bracket == web_bracket:
                return s
    return None

def run_scheduler_with_staggered_batches():
    with open(INPUT_JSON, 'r', encoding='utf-8') as f:
        strategy_cfgs = json.load(f)
    batch_groups = defaultdict(list)
    for cfg in strategy_cfgs:
        batch = cfg.get("交易批次", 1)
        batch_groups[batch].append(cfg)
    batch_cfgs_map = {b: clist for b, clist in batch_groups.items()}
    batch_status = load_batch_status()
    now = datetime.now()
    timers = []
    for idx, tstr in enumerate(SCHEDULE_TIMES, 1):
        schedule_time = datetime.strptime(now.strftime('%Y-%m-%d') + ' ' + tstr, '%Y-%m-%d %H:%M:%S')
        delta = (schedule_time - now).total_seconds()
        random_delay = random.uniform(3, 5)
        batch_cfgs = batch_cfgs_map.get(idx, [])
        if batch_status.get(str(idx)):
            continue  # 已采集，无需安排
        if schedule_time < now:
            print(f"第{idx}批次时间已过，立即补抓，策略：{[c['策略名称'] for c in batch_cfgs]}")
            threading.Thread(target=fetch_and_check_batch, args=(idx, tstr, batch_cfgs, batch_status)).start()
        else:
            print(f"第{idx}批次将于{schedule_time.strftime('%Y-%m-%d %H:%M:%S')}启动，距离现在{int(delta)}秒，策略：{[c['策略名称'] for c in batch_cfgs]}，附加延迟{random_delay:.2f}秒")
            t = threading.Timer(delta + random_delay, fetch_and_check_batch, args=(idx, tstr, batch_cfgs, batch_status))
            timers.append(t)
            t.start()
    print("全部定时任务已安排。")
    for t in timers:
        t.join()

def fetch_and_check_batch(batch_no, batch_time, batch_cfgs, batch_status):
    today_str = datetime.now().strftime('%Y-%m-%d')
    session = None
    while session is None:
        session = login()
        if session is None:
            print("无法登录，15秒后重试")
            time.sleep(15)

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
            found_today = False
            for cfg in batch_cfgs:
                s = find_strategy_by_id_and_bracket(cfg, strategies)
                if not s:
                    print(f"策略【{cfg['策略名称']}】未找到！")
                    continue
                if s['date'] == today_str:
                    found_today = True
                    action = extract_operation_action(s['operation_block'])
                    if action == '继续持有' or action == '空仓':
                        print(f"策略【{s['name']}】操作为{action}，跳过")
                        continue
                    config_amount = cfg.get('配置仓位', 0)
                    sample_amount = round(config_amount * SAMPLE_ACCOUNT_AMOUNT, 2)
                    print(f"\n>>> 策略【{s['name']}】 操作时间: {s['time']}")
                    # 新增：用带代码的买卖明细函数
                    handle_trade_operation(s['operation_block'], name_to_code)
                    print(f"配置仓位: {config_amount}，样板操作金额: {sample_amount}")
                    print("当前持仓:")
                    for h in s['holding_block']:
                        print("  " + h)
                    print("==============")
                else:
                    print(f"策略【{s['name']}】不是今日[{today_str}]操作，30秒后刷新重试...")
            if found_today:
                batch_status[str(batch_no)] = True
                save_batch_status(batch_status)
                break
            print("本批次部分策略还未更新到今日，30秒后重试")
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
    print("\n==================== 今日策略汇总 ====================")
    for batch in sorted(batch_dict.keys()):
        print(f"\n#### 交易批次 {batch}")
        for cfg in batch_dict[batch]:
            s = find_strategy_by_id_and_bracket(cfg, strategies)
            name = cfg['策略名称']
            if not s:
                print(f"策略【{name}】未找到！")
                continue
            # 1. 变更操作
            if s['date'] == today_str and extract_operation_action(s['operation_block']) == '买卖':
                config_amount = cfg.get('配置仓位', 0)
                sample_amount = round(config_amount * SAMPLE_ACCOUNT_AMOUNT/100, 2)
                # 用带代码的买卖明细
                handle_trade_operation(s['operation_block'], name_to_code)
                print(f"  配置仓位: {config_amount}，样板操作金额: {sample_amount}")
            # 2. 最终持仓
            print(f"【{name}】当前持仓:")
            if s['holding_block']:
                for h in s['holding_block']:
                    print("  " + h)
            else:
                print("  （无持仓信息）")
    print("\n==================== 汇总结束 ========================")

if __name__ == '__main__':
    run_scheduler_with_staggered_batches()
    collect_today_strategies()