#!/usr/bin/env python3
# yunfei_ball/yunfei_fetcher.py
# Fetcher that reuses session from yunfei_login.login()
# - accepts optional backward-compatible parameters ttl/cache_ttl and extra kwargs (ignored)
# - performs GET to /F2/b_follow.aspx with Referer
# - detects login/anti-bot page and returns clear warnings
# - optional parse (default True) to return structured items via parse_b_follow_page

import time
import json
import os
from datetime import datetime, timezone
from typing import Optional
import requests

from .yunfei_login import login, BASE_URL, HEADERS, FOLLOW_URL, LOGIN_URL, is_logged_in
from .parse_b_follow_page import parse_b_follow_page

# New: helper for saving fetch artifacts
def _ensure_cache_dir():
    base = os.path.join(os.path.dirname(__file__), "fetch_cache")
    os.makedirs(base, exist_ok=True)
    return base

def _save_fetch_artifacts(html: str, items: Optional[list], ts_iso: str):
    """
    Save raw html and parsed items to yunfei_ball/fetch_cache/
    filenames:
      - html_{ts}.html
      - items_{ts}.json   (if items provided)
      - latest_html.html
      - latest_items.json
    """
    base = _ensure_cache_dir()
    # sanitize ts for filename (use ISO compact)
    tsfn = ts_iso.replace(":", "").replace("-", "").replace("T", "_")
    html_path = os.path.join(base, f"html_{tsfn}.html")
    try:
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write(html)
    except Exception:
        pass
    # write latest_html as convenience (overwrite)
    try:
        with open(os.path.join(base, "latest_html.html"), "w", encoding="utf-8") as fh:
            fh.write(html)
    except Exception:
        pass
    if items is not None:
        items_path = os.path.join(base, f"items_{tsfn}.json")
        try:
            with open(items_path, "w", encoding="utf-8") as fi:
                json.dump(items, fi, ensure_ascii=False, indent=2)
        except Exception:
            pass
        try:
            with open(os.path.join(base, "latest_items.json"), "w", encoding="utf-8") as fi:
                json.dump(items, fi, ensure_ascii=False, indent=2)
        except Exception:
            pass

def fetch_b_follow(session: Optional[requests.Session] = None,
                   username: Optional[str] = None,
                   force: bool = False,
                   parse: bool = True,
                   cache_ttl: Optional[int] = None,
                   ttl: Optional[int] = None,
                   save_to_disk: Optional[bool] = None,
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

    New: save_to_disk (bool|None) controls whether to persist html/items to disk.
      If save_to_disk is None, use env var YUNFEI_SAVE_FETCH (treat "1","true" as True).
    """
    now_ts = int(time.time())
    now_iso = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    # determine save behavior
    if save_to_disk is None:
        envv = os.getenv("YUNFEI_SAVE_FETCH", "")
        save_to_disk = str(envv).lower() in ("1", "true", "yes", "y")

    # backward-compatibility: if ttl provided but cache_ttl is None, map it
    if cache_ttl is None and ttl is not None:
        cache_ttl = ttl

    # If session not provided, create temp session via login()
    local_session = False
    if session is None:
        try:
            session = login(username=username)
            local_session = True
        except Exception:
            session = None

    if session is None:
        return {
            'fetched_at': now_ts,
            'fetched_at_iso': now_iso,
            'html': '',
            'warning': 'login_failed',
            'items': []
        }

    try:
        resp = session.get(FOLLOW_URL, headers=HEADERS, timeout=10, proxies={})
        resp.encoding = resp.apparent_encoding
        html = resp.text
    except Exception as e:
        return {
            'fetched_at': now_ts,
            'fetched_at_iso': now_iso,
            'html': '',
            'warning': f'fetch_error:{e}',
            'items': []
        }

    # check if the page is still login page or not logged in
    if not is_logged_in(html):
        # optionally save html for debugging
        if save_to_disk:
            try:
                _save_fetch_artifacts(html, None, now_iso)
            except Exception:
                pass
        return {
            'fetched_at': now_ts,
            'fetched_at_iso': now_iso,
            'html': html,
            'warning': 'not_logged_in',
            'items': []
        }

    result = {
        'fetched_at': now_ts,
        'fetched_at_iso': now_iso,
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
            # save html even if parse failed
            if save_to_disk:
                try:
                    _save_fetch_artifacts(html, None, now_iso)
                except Exception:
                    pass
            return result
        result['items'] = items
    else:
        result['items'] = []

    # finally, optionally save artifacts
    if save_to_disk:
        try:
            _save_fetch_artifacts(html, result.get('items'), now_iso)
        except Exception:
            pass

    return result