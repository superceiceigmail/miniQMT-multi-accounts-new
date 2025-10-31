#!/usr/bin/env python3
# Minimal debug script for Yunfei login + fetch "我的策略" (b_follow.aspx)
# Implements the same pattern used in superceiceigmail/yunfeireview:
#  - use one requests.Session
#  - GET login page, preserve hidden fields
#  - POST login, include common headers (Referer/Origin)
#  - wait a short random delay, then GET the protected page and save HTML
#
# Usage: python yunfei_ball/debug_login.py
# Adjust USERNAME / PASSWORD below or set env vars YUNFEI_USERNAME / YUNFEI_PASSWORD

import os
import time
import random
import re
import requests
from bs4 import BeautifulSoup

LOGIN_URL = "https://www.ycyflh.com/F2/login.aspx"
BASE_URL = "https://www.ycyflh.com"
FOLLOW_URL = BASE_URL + "/F2/b_follow.aspx"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

DEFAULT_USERNAME = os.environ.get("YUNFEI_USERNAME", "ceicei")
DEFAULT_PASSWORD = os.environ.get("YUNFEI_PASSWORD", "ceicei628")

def get_value_by_name(soup, name):
    tag = soup.find("input", {"name": name})
    return tag.get("value", "") if tag else ""

def is_logged_in(html_text):
    if not html_text:
        return False
    return ("退出" in html_text or "个人资料" in html_text or "Hi," in html_text)

def try_follow_js_redirect(html, session):
    # Best-effort: follow simple window.location or meta refresh
    try:
        m = re.search(r'window\.location(?:\.href)?\s*=\s*[\'"]([^\'"]+)[\'"]', html)
        if m:
            url = m.group(1)
            if url.startswith("/"):
                url = BASE_URL + url
            return session.get(url, headers=HEADERS, timeout=10)
        m2 = re.search(r'<meta[^>]*http-equiv=["\']refresh["\'][^>]*content=["\']\s*\d+\s*;\s*url=([^"\']+)["\']', html, flags=re.IGNORECASE)
        if m2:
            url = m2.group(1)
            if url.startswith("/"):
                url = BASE_URL + url
            return session.get(url, headers=HEADERS, timeout=10)
    except Exception:
        pass
    return None

def main(username=None, password=None):
    if username is None:
        username = DEFAULT_USERNAME
    if password is None:
        password = DEFAULT_PASSWORD

    session = requests.Session()
    session.trust_env = False
    session.headers.update(HEADERS)

    print("GET login page …")
    resp = session.get(LOGIN_URL, timeout=15)
    print("GET login status:", resp.status_code)
    with open("debug_login_get.html", "w", encoding="utf-8") as f:
        f.write(resp.text)

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

    # Ensure agreement checkbox and submit button fields exist
    if "ckb_UserAgreement" not in data:
        data["ckb_UserAgreement"] = "on"
    # login button name/value seen on site
    data.setdefault("btn_login", "登 录")

    headers_post = dict(session.headers)
    headers_post.update({
        "Referer": LOGIN_URL,
        "Origin": BASE_URL,
        "Content-Type": "application/x-www-form-urlencoded"
    })

    print("POST login …")
    login_resp = session.post(LOGIN_URL, data=data, headers=headers_post, timeout=15, allow_redirects=True)
    print("POST status:", getattr(login_resp, "status_code", "N/A"))
    # save login response head for debugging
    with open("debug_login_post.html", "w", encoding="utf-8") as f:
        f.write(login_resp.text)

    # small random delay to mimic human behavior and let server set cookies
    wait = random.uniform(2.0, 4.5)
    print(f"Waiting {wait:.2f}s after login to allow session stabilization...")
    time.sleep(wait)

    # try to follow possible JS/meta redirect returned by the login response
    follow_resp = try_follow_js_redirect(login_resp.text, session)
    if follow_resp is not None:
        post_login_check = follow_resp
    else:
        post_login_check = session.get(FOLLOW_URL, headers=HEADERS, timeout=15)

    print("GET b_follow status:", getattr(post_login_check, "status_code", "N/A"))
    print("response url:", getattr(post_login_check, "url", "N/A"))
    print("response history:", getattr(post_login_check, "history", []))

    # save protected page head
    with open("debug_b_follow_after_login.html", "w", encoding="utf-8") as f:
        f.write(post_login_check.text or "")

    logged = is_logged_in(post_login_check.text or "")
    print("is_logged_in(b_follow) ->", logged)
    print("session cookies:", session.cookies.get_dict())

    if not logged:
        print("Login not recognized by server. Check debug_* files and try manual login or cookie import.")
    else:
        print("Login successful and verified. Protected page saved to debug_b_follow_after_login.html")

if __name__ == "__main__":
    main()