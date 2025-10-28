#!/usr/bin/env python3
# yunfei_ball/yunfei_fetcher.py
# Fetcher that reuses session from yunfei_login.login()
# - accepts optional backward-compatible parameters ttl/cache_ttl and extra kwargs (ignored)
# - performs GET to /F2/b_follow.aspx with Referer
# - detects login/anti-bot page and returns clear warnings
# - optional parse (default True) to return structured items via parse_b_follow_page

import time
import json
from datetime import datetime, timezone
from typing import Optional
import requests

from .yunfei_login import login, BASE_URL, HEADERS, FOLLOW_URL, LOGIN_URL, is_logged_in
from .parse_b_follow_page import parse_b_follow_page

def fetch_b_follow(session: Optional[requests.Session] = None,
                   username: Optional[str] = None,
                   force: bool = False,
                   parse: bool = True,
                   cache_ttl: Optional[int] = None,
                   ttl: Optional[int] = None,
                   **kwargs) -> dict:
    """
    Fetch /F2/b_follow.aspx and return a dict:
      {
        'fetched_at': ts,
        'fetched_at_iso': iso,
        'html': html_text,
        'warning': '',  # or 'login_failed'/'not_logged_in'/'rate_limited'/'fetch_error:...'
        'items': [...]  # present if parse=True and fetch succeeded
      }
    Backward compatibility:
      - Accepts 'ttl' or 'cache_ttl' kwargs (not used by fetcher itself) so callers that pass ttl won't error.
      - Accepts arbitrary extra kwargs and ignores them.
    """
    now_ts = int(time.time())
    # backward-compatibility: if ttl provided but cache_ttl is None, map it
    if cache_ttl is None and ttl is not None:
        cache_ttl = ttl

    # ensure we have session
    if session is None:
        session = login(username=username)
        if session is None:
            return {
                'fetched_at': None,
                'fetched_at_iso': None,
                'html': '',
                'warning': 'login_failed',
                'items': []
            }

    # perform GET with proper Referer
    headers = dict(session.headers)
    headers.update({
        'Referer': LOGIN_URL
    })

    try:
        resp = session.get(FOLLOW_URL, headers=headers, timeout=15, allow_redirects=True)
        resp.encoding = resp.apparent_encoding
        html = resp.text
    except Exception as e:
        return {
            'fetched_at': now_ts,
            'fetched_at_iso': datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
            'html': '',
            'warning': f'fetch_error:{e}',
            'items': []
        }

    # quick anti-bot/limit detection
    if "操作过于频繁" in html or "您的操作过于频繁" in html or "CODE: 301" in html or "Unstable Connection" in html:
        return {
            'fetched_at': now_ts,
            'fetched_at_iso': datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
            'html': html,
            'warning': 'rate_limited',
            'items': []
        }

    # check if the page is still login page or not logged in
    if not is_logged_in(html):
        return {
            'fetched_at': now_ts,
            'fetched_at_iso': datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
            'html': html,
            'warning': 'not_logged_in',
            'items': []
        }

    result = {
        'fetched_at': now_ts,
        'fetched_at_iso': datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
        'html': html,
        'warning': ''
    }

    # success: optionally parse into structured items
    if parse:
        try:
            items = parse_b_follow_page(html)
        except Exception as e:
            result['warning'] = f'parse_error:{e}'
            result['items'] = []
            return result
        result['items'] = items
    else:
        result['items'] = []

    return result

# helper to save result to runtime cache (optional)
def save_cache_for_user(username: str, payload: dict, runtime_dir: str):
    try:
        import os
        os.makedirs(runtime_dir, exist_ok=True)
        path = os.path.join(runtime_dir, f"cache_b_follow_{username or 'default'}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass