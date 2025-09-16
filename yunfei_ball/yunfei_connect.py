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

SCHEDULE_TIMES = [
    "14:52:00",
    "13:00:05",
    "14:30:33",
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

    # 操作区块
    op_block_match = re.search(r'订阅.*?\n(.*?)\n*【目前持仓】', main_text, re.S)
    op_block = op_block_match.group(1).strip() if op_block_match else ""

    # 操作区块持仓明细
    op_proportions = re.findall(r'(?:继续持有|买入|卖出)\s*([^\(\s;]+)[\(（]?([\d\.]+)?%?[\)）]?', op_block)
    operation_list = []
    for s, p in op_proportions:
        p_clean = p.strip() + "%" if p and p.strip() else ""
        operation_list.append({"symbol": s.strip(), "proportion": p_clean})

    # 仓位变化形式，如“xxx 仓位0%→32.58%”
    wzs = re.findall(r'([^\s;；\(\)]+)\s*仓位\s*([\d\.]+)%→([\d\.]+)%', op_block)
    operation_wz = []
    for symbol, from_p, to_p in wzs:
        from_p = float(from_p)
        to_p = float(to_p)
        if from_p < to_p:
            operation_wz.append({"symbol": symbol, "action": "买入", "from": from_p, "to": to_p, "proportion": to_p - from_p})
        elif from_p > to_p:
            operation_wz.append({"symbol": symbol, "action": "卖出", "from": from_p, "to": to_p, "proportion": from_p - to_p})

    # 继续持有内容
    continue_hold = re.findall(r'继续持有\s*([^\(\s;]+)[\(（]?([\d\.]+)?%?[\)）]?', op_block)

    # 提取买入卖出明细
    buy_sell_trades = []
    # 买入明细
    for match in re.findall(r'买入\s*([^\s;；\(\)]+)[\(（]?([\d\.]+)?%?[\)）]?', op_block):
        symbol, p = match
        p = float(p) if p else 0.0
        buy_sell_trades.append({"symbol": symbol, "action": "买入", "proportion": p})
    # 卖出明细
    for match in re.findall(r'卖出\s*([^\s;；\(\)]+)[\(（]?([\d\.]+)?%?[\)）]?', op_block):
        symbol, p = match
        p = float(p) if p else 0.0
        buy_sell_trades.append({"symbol": symbol, "action": "卖出", "proportion": p})

    # 合并仓位变化和买卖明细（仓位变化优先，避免重复）
    op_symbols = set([o['symbol'] for o in operation_wz])
    for t in buy_sell_trades:
        if t['symbol'] not in op_symbols:
            operation_wz.append(t)

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
        "operation_block": operation_wz,  # 只保留需要切换的内容
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

def combine_switch_trades(strategy_cfgs, all_ops):
    """
    合并所有策略的买卖计划，买卖相抵
    """
    trade_plan = {}  # symbol: {'买入': total, '卖出': total}
    for cfg, op in zip(strategy_cfgs, all_ops):
        allocation = float(cfg.get("配置仓位", 0))
        for trade in op["operation_block"]:
            symbol = trade["symbol"]
            direction = trade["action"]
            prop = float(trade["proportion"])
            real = allocation * prop / 100
            if symbol not in trade_plan:
                trade_plan[symbol] = {'买入': 0.0, '卖出': 0.0}
            trade_plan[symbol][direction] += real
    # 买卖相抵
    plan = []
    for symbol, v in trade_plan.items():
        buy, sell = v['买入'], v['卖出']
        diff = buy - sell
        if abs(diff) < 1e-6:
            continue
        if diff > 0:
            plan.append({"symbol": symbol, "action": "买入", "amount": round(diff, 2)})
        else:
            plan.append({"symbol": symbol, "action": "卖出", "amount": round(-diff, 2)})
    return plan

def print_strategy_info(cfg, op):
    print(f"\n>>> 策略【{cfg.get('策略名称', '')}】(ID: {cfg.get('策略ID', '')}) 操作日期: {op.get('operation_date', '')}")
    print("--- 需要切换部分 ---")
    if op.get("operation_block"):
        for item in op.get("operation_block", []):
            print(f"  [{item.get('action', '')}] 标的: {item.get('symbol', '')}，目标仓位变化: {item.get('proportion', '')}%")
    else:
        print("  无需要切换内容")
    print("--- 当前持仓 ---")
    if op.get("holdings_block"):
        for item in op.get("holdings_block", []):
            print(f"  标的: {item.get('symbol', '')}，仓位: {item.get('proportion', '')}")
    else:
        print("  无持仓内容")
    print("==============")

def print_trade_plan(batch_no, batch_time, plan):
    print(f"\n====== 第{batch_no}批次({batch_time}) 合并交易计划 ======")
    for item in plan:
        print(f"标的：{item['symbol']}，{item['action']} {item['amount']}%")
    print("=" * 60)

def fetch_batch(batch_no, batch_time, strategy_cfgs):
    print(f"\n------ 批次{batch_no} 开始，时间点: {batch_time}, 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ------")
    if not strategy_cfgs:
        print("本批次无策略，跳过。")
        return

    today_str = datetime.now().strftime('%Y-%m-%d')
    session = login()
    if session is None:
        print("无法登录，跳过本批次")
        return

    for idx, cfg in enumerate(strategy_cfgs):
        print(f"\n>>> 处理第 {idx+1} 个策略")
        print("策略配置：", json.dumps(cfg, ensure_ascii=False, indent=2))  # 打印json中策略信息

        retry_count = 0
        max_retry = 20
        while retry_count < max_retry:
            try:
                op = fetch_strategy_once(session, cfg)
                if op["operation_date"] == today_str:
                    print_strategy_info(cfg, op)  # 打印操作相关信息
                    # 只对本策略生成交易计划，不合并
                    plan = combine_switch_trades([cfg], [op])
                    print_trade_plan(batch_no, batch_time, plan)
                    break  # 处理下一个策略
                else:
                    print(f"策略 {cfg.get('策略名称')} 操作日期[{op['operation_date']}]不是今日[{today_str}]，重试...")
            except Exception as e:
                print(f"策略 {cfg.get('策略名称')} 抓取异常: {e}")
            retry_count += 1
            if retry_count < max_retry:
                print("20秒后重试该策略...")
                time.sleep(20)
        else:
            print(f"策略 {cfg.get('策略名称')} 达到最大重试次数，跳过。")
        # 批次策略之间岔开 1~2 秒（防并发，模拟人工）
        delay = random.uniform(1, 2)
        print(f"策略间延迟 {delay:.2f} 秒")
        time.sleep(delay)

def run_scheduler_with_staggered_batches():
    # 读取json配置
    with open(INPUT_JSON, 'r', encoding='utf-8') as f:
        strategy_cfgs = json.load(f)
    # 按交易批次分组
    batch_groups = defaultdict(list)
    for cfg in strategy_cfgs:
        batch = cfg.get("交易批次", 1)
        batch_groups[batch].append(cfg)
    now = datetime.now()
    timers = []
    for idx, tstr in enumerate(SCHEDULE_TIMES, 1):
        schedule_time = datetime.strptime(now.strftime('%Y-%m-%d') + ' ' + tstr, '%Y-%m-%d %H:%M:%S')
        if schedule_time < now:
            schedule_time += timedelta(days=1)
        delta = (schedule_time - now).total_seconds()
        random_delay = random.uniform(3, 5)  # 3~5秒的随机延迟
        batch_cfgs = batch_groups.get(idx, [])
        print(f"第{idx}批次将于{schedule_time.strftime('%Y-%m-%d %H:%M:%S')}启动，距离现在{int(delta)}秒，本批次{len(batch_cfgs)}个策略，附加延迟{random_delay:.2f}秒")
        t = threading.Timer(delta + random_delay, fetch_batch, args=(idx, tstr, batch_cfgs))
        timers.append(t)
        t.start()
    print("全部定时任务已安排。")
    # 主线程常驻，直到所有定时任务结束
    for t in timers:
        t.join()

if __name__ == '__main__':
    run_scheduler_with_staggered_batches()