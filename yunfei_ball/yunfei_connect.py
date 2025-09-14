import os
import time
import random
import requests
import re
import json
import threading
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from collections import defaultdict

USERNAME = 'ceicei'
PASSWORD = 'ceicei628'
LOGIN_URL = 'https://www.ycyflh.com/F2/login.aspx'
BASE_URL = 'https://www.ycyflh.com'
SAVE_DIR = 'yunfei_core_strategies'
INPUT_JSON = 'allocation.json'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
}

# =========== 1. 定义五个时间点（24小时制） ===============
SCHEDULE_TIMES = [
    "09:33:00",
    "13:00:05",
    "14:31:00",
    "14:50:05",
]

def get_value_by_name(soup, name):
    tag = soup.find('input', {'name': name})
    return tag['value'] if tag else ''

def is_logged_in(html_text):
    return ("退出" in html_text or "个人资料" in html_text or "Hi," in html_text)

def login():
    session = requests.Session()
    session.headers.update(HEADERS)
    resp = session.get(LOGIN_URL)
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
    login_resp = session.post(LOGIN_URL, data=data)
    if not is_logged_in(login_resp.text):
        print("登录失败，请检查用户名密码或表单字段。")
        return None
    print("登录成功")
    return session

def extract_operation_and_holdings(html):
    soup = BeautifulSoup(html, 'lxml')
    main_text = soup.get_text('\n', strip=True)

    # 操作类型和操作区块
    op_block_match = re.search(r'订阅.*?\n(.*?)\n*【目前持仓】', main_text, re.S)
    op_block = op_block_match.group(1).strip() if op_block_match else ""
    # 操作区块持仓明细
    op_proportions = re.findall(r'(?:继续持有|买入|卖出)\s*([^\(\s;]+)[\(（]?([\d\.]+)?%?[\)）]?', op_block)
    operation_list = []
    for s, p in op_proportions:
        p_clean = p.strip() + "%" if p and p.strip() else ""
        operation_list.append({"symbol": s.strip(), "proportion": p_clean})

    # 持仓区块
    holdings_list = []
    holdings_div = None
    for div in soup.find_all('div'):
        if '【目前持仓】' in div.text:
            holdings_div = div
            break
    if holdings_div:
        all_text = holdings_div.get_text(separator="\n", strip=True)
        for line in all_text.splitlines():
            m = re.match(r'([^\s：:]+)[：:]\s*([\d\.]+)%', line)
            if m:
                holdings_list.append({
                    "symbol": m.group(1).strip(),
                    "proportion": m.group(2).strip() + "%"
                })

    # 提取策略操作日期
    date_match = re.search(r'(\d{4}-\d{1,2}-\d{1,2})', main_text)
    op_date = date_match.group(1) if date_match else ""

    return {
        "operation_block": operation_list,
        "holdings_block": holdings_list,
        "operation_date": op_date
    }

def fetch_strategy_once(session, cfg):
    sid = str(cfg["策略ID"])
    url = f"{BASE_URL}/F2/c_detail.aspx?id={sid}"
    headers = HEADERS.copy()
    headers['Referer'] = BASE_URL + "/F2/b_ranking.aspx"
    resp = session.get(url, headers=headers, timeout=10)
    resp.encoding = resp.apparent_encoding
    # 登录失效重登
    if not is_logged_in(resp.text):
        session = login()
        if session is None:
            raise RuntimeError("登录失败")
        resp = session.get(url, headers=headers, timeout=10)
        resp.encoding = resp.apparent_encoding
    page_info = extract_operation_and_holdings(resp.text)
    return page_info

def combine_positions(strategy_cfgs, all_ops):
    # 汇总同名标的的仓位
    combined = defaultdict(lambda: {"仓位": 0.0, "策略": []})
    for cfg, op in zip(strategy_cfgs, all_ops):
        strategy_name = cfg.get("策略名称", "")
        strategy_id = cfg.get("策略ID")
        allocation = float(cfg.get("配置仓位", 0))
        for item in op["operation_block"]:
            symbol = item["symbol"]
            prop_str = item.get("proportion", "").replace("%", "")
            if not prop_str:
                continue
            try:
                prop = float(prop_str)
            except:
                continue
            position = allocation * prop / 100
            combined[symbol]["仓位"] += position
            combined[symbol]["策略"].append({"策略名称": strategy_name, "策略ID": strategy_id, "标的": symbol, "仓位": position})
    # 合并输出
    result = []
    for symbol, info in combined.items():
        result.append({
            "标的": symbol,
            "合并仓位": round(info["仓位"], 2),
            "明细": info["策略"]
        })
    return result

def print_batch_plan(batch_no, batch_time, combined_positions):
    print(f"\n====== 第{batch_no}批次({batch_time}) 合并交易计划 ======")
    for item in combined_positions:
        print(f"标的: {item['标的']}，合并仓位: {item['合并仓位']}%")
        for detail in item["明细"]:
            print(f"    策略名称: {detail['策略名称']}，策略ID: {detail['策略ID']}，单策略仓位: {round(detail['仓位'], 2)}%")
    print("=" * 60)

def fetch_batch(batch_no, batch_time, strategy_cfgs):
    print(f"\n------ 批次{batch_no} 开始，时间点: {batch_time}, 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ------")
    session = login()
    if session is None:
        print("无法登录，跳过本批次")
        return

    today_str = datetime.now().strftime("%Y-%m-%d")
    max_retry = 10
    retry = 0
    finished = [False] * len(strategy_cfgs)
    all_ops = [None] * len(strategy_cfgs)

    while retry < max_retry and not all(finished):
        for idx, cfg in enumerate(strategy_cfgs):
            if finished[idx]:
                continue
            try:
                op = fetch_strategy_once(session, cfg)
                # 只关心操作日期为今日的
                if op["operation_date"] == today_str:
                    all_ops[idx] = op
                    finished[idx] = True
                else:
                    print(f'策略{cfg.get("策略名称")} 操作日期[{op["operation_date"]}]不是今日[{today_str}]，重试...')
            except Exception as e:
                print(f"策略{cfg.get('策略名称')} 抓取异常: {e}")
        if not all(finished):
            retry += 1
            print(f"第{retry}次未全部拉到，20秒后重试...")
            time.sleep(20)
        else:
            break

    # 打印本批次已拉到的
    valid_cfgs = [cfg for idx, cfg in enumerate(strategy_cfgs) if all_ops[idx] is not None]
    valid_ops = [op for op in all_ops if op is not None]
    combined = combine_positions(valid_cfgs, valid_ops)
    print_batch_plan(batch_no, batch_time, combined)

def run_scheduler():
    # 读取json配置
    with open(INPUT_JSON, 'r', encoding='utf-8') as f:
        strategy_cfgs = json.load(f)
    now = datetime.now()
    for idx, tstr in enumerate(SCHEDULE_TIMES, 1):
        schedule_time = datetime.strptime(now.strftime('%Y-%m-%d') + ' ' + tstr, '%Y-%m-%d %H:%M:%S')
        if schedule_time < now:
            # 今天已过，顺延到明天
            schedule_time += timedelta(days=1)
        delta = (schedule_time - now).total_seconds()
        print(f"第{idx}批次将于{schedule_time.strftime('%Y-%m-%d %H:%M:%S')}启动，距离现在{int(delta)}秒")
        threading.Timer(delta, fetch_batch, args=(idx, tstr, strategy_cfgs)).start()
    print("全部定时任务已安排。")

if __name__ == '__main__':
    run_scheduler()
    # 主线程常驻，直到所有定时任务结束
    while True:
        time.sleep(60)