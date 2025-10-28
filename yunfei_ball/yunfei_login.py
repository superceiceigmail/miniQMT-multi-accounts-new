#!/usr/bin/env python3
# yunfei_ball/yunfei_login.py
# Minimal, robust login following the pattern in superceiceigmail/yunfeireview:
#  - use a single requests.Session
#  - GET login page, keep hidden inputs (__VIEWSTATE etc.)
#  - POST login with full headers (Referer/Origin)
#  - small random sleep after POST to allow server-side session stabilization
#  - try to follow simple JS/meta redirects (best-effort)
#  - verify login by requesting the protected page /F2/b_follow.aspx

import os
import time
import random
import re
from typing import Optional
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.ycyflh.com"
LOGIN_URL = BASE_URL + "/F2/login.aspx"
FOLLOW_URL = BASE_URL + "/F2/b_follow.aspx"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Connection": "keep-alive",
}

DEFAULT_USERNAME = os.environ.get("YUNFEI_USERNAME", "ceicei")
DEFAULT_PASSWORD = os.environ.get("YUNFEI_PASSWORD", "ceicei628")

def get_value_by_name(soup: BeautifulSoup, name: str) -> str:
    tag = soup.find("input", {"name": name})
    return tag.get("value", "") if tag else ""

def is_logged_in(html_text: str) -> bool:
    if not html_text:
        return False
    return ("退出" in html_text or "个人资料" in html_text or "Hi," in html_text)

def _try_follow_js_redirect(html: str, session: requests.Session) -> Optional[requests.Response]:
    # Best-effort: follow simple window.location or meta refresh
    try:
        m = re.search(r'window\.location(?:\.href)?\s*=\s*[\'"]([^\'"]+)[\'"]', html)
        if m:
            url = m.group(1)
            if url.startswith("/"):
                url = BASE_URL + url
            return session.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        m2 = re.search(
            r'<meta[^>]*http-equiv=["\']refresh["\'][^>]*content=["\']\s*\d+\s*;\s*url=([^"\']+)["\']',
            html,
            flags=re.IGNORECASE
        )
        if m2:
            url = m2.group(1)
            if url.startswith("/"):
                url = BASE_URL + url
            return session.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
    except Exception:
        pass
    return None

def login(username: Optional[str] = None, password: Optional[str] = None, max_retries: int = 2) -> Optional[requests.Session]:
    """
    Try to login and return a logged-in requests.Session or None.
    Steps:
      - GET login page, parse hidden fields
      - POST login with preserved hidden fields and common headers
      - wait short random delay (2-4.5s)
      - attempt to follow possible JS/meta redirect
      - GET FOLLOW_URL and verify is_logged_in
    """
    if username is None:
        username = DEFAULT_USERNAME
    if password is None:
        password = DEFAULT_PASSWORD

    attempt = 0
    while attempt < max_retries:
        attempt += 1
        session = requests.Session()
        session.trust_env = False  # avoid using system proxies unintentionally
        session.headers.update(HEADERS)
        try:
            resp = session.get(LOGIN_URL, timeout=15)
        except Exception:
            time.sleep(1)
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        # collect form inputs (preserve hidden fields like __VIEWSTATE)
        data = {}
        for inp in soup.find_all("input"):
            name = inp.get("name")
            if not name:
                continue
            if name == "txt_name_2020_byf":
                data[name] = username
            elif name == "txt_pwd_2020_byf":
                data[name] = password
            else:
                data[name] = inp.get("value", "")

        # ensure agreement and submit button if not present
        data.setdefault("ckb_UserAgreement", "on")
        data.setdefault("btn_login", "登 录")

        headers_post = dict(session.headers)
        headers_post.update({
            "Referer": LOGIN_URL,
            "Origin": BASE_URL,
            "Content-Type": "application/x-www-form-urlencoded",
        })

        try:
            login_resp = session.post(LOGIN_URL, data=data, headers=headers_post, timeout=15, allow_redirects=True)
        except Exception:
            time.sleep(1 + attempt)
            continue

        # small human-like delay
        time.sleep(random.uniform(2.0, 4.5))

        # try to follow simple JS/meta redirect
        follow = _try_follow_js_redirect(login_resp.text, session)
        if follow is not None:
            check_resp = follow
        else:
            try:
                check_resp = session.get(FOLLOW_URL, headers=HEADERS, timeout=15, allow_redirects=True)
            except Exception:
                check_resp = None

        if not check_resp:
            time.sleep(1)
            continue

        # detect anti-bot/limit pages quickly
        snippet = check_resp.text[:1000] if check_resp.text else ""
        if "操作过于频繁" in snippet or "您的操作过于频繁" in snippet or "CODE: 301" in snippet or "Unstable Connection" in snippet:
            # do not retry aggressively
            return None

        if is_logged_in(check_resp.text):
            return session

        # not logged in — try again if retries remain
        time.sleep(1)

    return None