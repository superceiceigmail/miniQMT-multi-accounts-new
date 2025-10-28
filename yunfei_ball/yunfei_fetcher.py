# yunfei_ball/yunfei_fetcher.py
# 抓取并解析 yunfei 的 b_follow 页面，带文件缓存（TTL）与 filelock 并发保护。
# 提供 fetch_b_follow(session=None, username=None, force=False, ttl=600) -> dict
# 并导出 parse_b_follow_page(html)

import os
import time
import json
import glob
import re
from datetime import datetime, timezone
from typing import Optional
from filelock import FileLock
import requests
from bs4 import BeautifulSoup

# 从 login 模块复用常量/登录入口
from .yunfei_login import login, LOGIN_URL, BASE_URL, HEADERS

# 缓存与运行时路径（与原来目录结构兼容）
BASE_DIR = os.path.dirname(__file__)
RUNTIME_DIR = os.path.join(BASE_DIR, "runtime")
os.makedirs(RUNTIME_DIR, exist_ok=True)

# 缓存文件（按用户名区分）
def _cache_path_for_user(username: str):
    safe = username if username else "default"
    return os.path.join(RUNTIME_DIR, f"cache_b_follow_{safe}.json")

def _lock_path_for_user(username: str):
    safe = username if username else "default"
    return os.path.join(RUNTIME_DIR, f"cache_b_follow_{safe}.lock")

DEFAULT_TTL = 600  # 10 minutes

def _now_ts():
    return int(time.time())

def _read_cache(path: str):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def _write_cache(path: str, payload: dict):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

def fetch_b_follow(session: Optional[requests.Session] = None, username: Optional[str] = None, force: bool = False, ttl: int = DEFAULT_TTL) -> dict:
    """
    抓取并解析 /F2/b_follow.aspx，返回结构：
    {
      "fetched_at": 169... (unix ts),
      "fetched_at_iso": "2025-10-28T13:28:00Z",
      "strategies": [ ... ]  # parse_b_follow_page 的返回
      "html": "... optional raw html"
    }
    - session: 可传入已登录的 session；若 None 会尝试 login(username)
    - force: 如果为 True 则绕过缓存强制抓取
    - ttl: 缓存生存时间（秒）
    """
    if username is None:
        username = "default"

    cache_path = _cache_path_for_user(username)
    lock_path = _lock_path_for_user(username)
    # 尝试读取缓存（在未取得锁的情况下也可读取）
    cached = _read_cache(cache_path)
    if not force and cached:
        try:
            age = int(time.time()) - int(cached.get('fetched_at', 0))
        except Exception:
            age = ttl + 1
        if age <= ttl:
            return cached  # 直接返回缓存

    # 需要抓取：加文件锁，避免并发重复抓取
    lock = FileLock(lock_path, timeout=10)
    with lock:
        # 再次检查缓存（防止竞争）
        cached = _read_cache(cache_path)
        if not force and cached:
            try:
                age = int(time.time()) - int(cached.get('fetched_at', 0))
            except Exception:
                age = ttl + 1
            if age <= ttl:
                return cached

        # 确保有 session
        if session is None:
            session = login(username=username)

        if session is None:
            # 无法登录：如果有旧缓存则退回旧缓存并带 warning
            if cached:
                cached['warning'] = 'login_failed_used_stale_cache'
                return cached
            raise RuntimeError("无法登录云飞，且无可用缓存。")

        try:
            resp = session.get(BASE_URL + '/F2/b_follow.aspx', headers=HEADERS, timeout=15, proxies={})
            resp.encoding = resp.apparent_encoding
            html = resp.text
            strategies = parse_b_follow_page(html)
            payload = {
                'fetched_at': int(time.time()),
                'fetched_at_iso': datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
                'strategies': strategies,
                'html': html
            }
            _write_cache(cache_path, payload)
            return payload
        except Exception as e:
            # 网络异常：如果有旧缓存则退回旧缓存并带 warning
            if cached:
                cached['warning'] = f'fetch_failed_used_stale_cache:{e}'
                return cached
            raise

def parse_b_follow_page(html: str):
    """
    解析 b_follow 页面，返回与原来 parse_b_follow_page 兼容的策略字典列表：
    [
      { "name": "...", "date": "YYYY-MM-DD", "time": "YYYY-MM-DD HH:MM", "operation_block": "<div>...</div>" or text, "holding_block": [...] }
    ]
    """
    soup = BeautifulSoup(html, 'lxml')
    strategies = []
    for table in soup.find_all('table', {'border': '1'}):
        name = ''
        ttime = ''
        op_block = ''
        holding_block = ''
        th = table.find('th', attrs={'colspan': '2'})
        if not th:
            continue
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