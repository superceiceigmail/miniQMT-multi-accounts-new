#!/usr/bin/env python3
# parse_b_follow_page.py
# Fixed parser: avoid creating holdings from bracket tokens by splitting holdings
# using HTML-level <br> first, extract per-segment bracketed profit, then parse.

import re
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from urllib.parse import unquote

RE_CDETAIL = re.compile(r'c_detail\.aspx\?id=(\d+)')
RE_FOLLOW = re.compile(r'[?&]id=(\d+)')
RE_TIME = re.compile(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]')
RE_HOLDING_PCT = re.compile(r'([\d\.]+)\s*%')
RE_SHORTID = re.compile(r'^L(\d+):')
NOISE_PATTERNS = [
    re.compile(r'持仓第\d+'),
    re.compile(r'暂不调仓'),
    re.compile(r'持仓第.*日'),
    re.compile(r'暂不调'),
]

def _is_noise_text(s: str) -> bool:
    if not s:
        return False
    for p in NOISE_PATTERNS:
        if p.search(s):
            return True
    return False

def _extract_profit_from_brackets(text: str) -> (Optional[str], Optional[float]):
    if not text:
        return None, None
    for m in re.finditer(r'\[([^\]]+)\]', text):
        inside = m.group(1)
        pm = re.search(r'([+\-]?\d+(?:\.\d+)?)\s*%', inside)
        if pm:
            num = pm.group(1)
            try:
                pct = float(num)
            except Exception:
                pct = None
            if num.startswith('+') or num.startswith('-'):
                profit_str = f"{num}%"
            else:
                profit_str = f"{'+' if pct and pct > 0 else ''}{num}%"
            return profit_str, pct
    return None, None

def _decode_nested_href(href: str) -> str:
    decoded = href or ""
    for _ in range(3):
        nxt = unquote(decoded)
        if nxt == decoded:
            break
        decoded = nxt
    return decoded

def _parse_holdings_from_element(elem) -> List[Dict]:
    """
    elem: BeautifulSoup element that holds the holdings (div or td)
    Strategy:
      - split HTML of elem by <br> boundaries (so each segment usually maps to one holding)
      - for each segment: extract bracket profit (if any), remove brackets, then split by ; or , into subparts
      - parse each subpart for name and pct
    """
    if elem is None:
        return []

    html = str(elem)  # preserve <br> boundaries
    # split by <br> (handle variations <br>, <br/>, <br />)
    segments = re.split(r'(?i)<br\s*/?>', html)
    holdings: List[Dict] = []

    for seg_html in segments:
        # convert segment html to text (keeps bracketed content)
        seg_text = BeautifulSoup(seg_html, "html.parser").get_text(separator=" ", strip=True)
        if not seg_text:
            continue
        # ignore segments that are pure noise or are only bracket fragments
        if _is_noise_text(seg_text):
            continue
        # extract profit for this segment from brackets (if present)
        profit_str, profit_pct = _extract_profit_from_brackets(seg_text)
        # remove bracket contents to avoid them becoming separate parts
        seg_text_no_brackets = re.sub(r'\[[^\]]*\]', '', seg_text).strip()
        if not seg_text_no_brackets:
            continue
        # split further by ; , / and similar within the segment
        parts = re.split(r'[;；,，/]', seg_text_no_brackets)
        for part in parts:
            part = part.strip()
            if not part or _is_noise_text(part):
                continue
            # parse name and pct
            if '：' in part:
                name_part, pct_part = part.split('：', 1)
            elif ':' in part:
                name_part, pct_part = part.split(':', 1)
            else:
                m = RE_HOLDING_PCT.search(part)
                if m:
                    pct_part = m.group(0)
                    name_part = part[:m.start()].strip()
                else:
                    name_part, pct_part = part, ''
            name = name_part.strip() or None
            pct = None
            m_pct = RE_HOLDING_PCT.search(pct_part or '')
            if m_pct:
                try:
                    pct = float(m_pct.group(1))
                except Exception:
                    pct = None
            # final filter: ignore fragments starting with '[' or that look like leftover bracket pieces
            if name and name.startswith('['):
                continue
            holdings.append({
                "name": name,
                "pct": pct,
                "profit_str": profit_str,
                "profit_pct": profit_pct
            })

    # deduplicate preserving order
    seen = set()
    deduped = []
    for h in holdings:
        key = (h.get("name"), h.get("pct"), h.get("profit_str"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(h)
    return deduped

def parse_b_follow_page(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", class_="content") or soup.find("div", id="main") or soup

    results: List[Dict] = []

    for a in content.find_all("a", href=RE_CDETAIL):
        tbl = a.find_parent("table")
        while tbl:
            if tbl.find("td", class_="td_top") or tbl.find(attrs={"im": "1"}) or \
               any((tag for tag in tbl.find_all(True) if tag.attrs.get("im") == 1)):
                break
            parent_tbl = tbl.find_parent("table")
            if not parent_tbl or parent_tbl is tbl:
                break
            tbl = parent_tbl
        if not tbl:
            continue

        href = a.get("href", "")
        detail_m = RE_CDETAIL.search(href)
        detail_id = int(detail_m.group(1)) if detail_m else None
        title = a.get_text(strip=True)

        short_id = None
        s_m = RE_SHORTID.search(title)
        if s_m:
            try:
                short_id = int(s_m.group(1))
            except Exception:
                short_id = None

        tbl_text = tbl.get_text(" ", strip=True)
        time_m = RE_TIME.search(tbl_text)
        time_str = time_m.group(1) if time_m else None

        op_div = tbl.find(attrs={"im": "1"})
        if not op_div:
            for tag in tbl.find_all(True):
                im_val = tag.attrs.get("im")
                if im_val == "1" or im_val == 1:
                    op_div = tag
                    break
        op_text = op_div.get_text(" ", strip=True) if op_div else ""

        # holdings: find the td.td_top and pick the first '目前持仓' block; parse using HTML-aware helper
        holdings: List[Dict] = []
        td = tbl.find("td", class_="td_top")
        if td:
            # try to locate the div after the '目前持仓' label
            divs = [d for d in td.find_all("div", recursive=True)]
            idx = None
            for i, d in enumerate(divs):
                if '目前持仓' in d.get_text():
                    idx = i
                    break
            hold_elem = None
            if idx is not None and idx + 1 < len(divs):
                hold_elem = divs[idx + 1]
            else:
                # fallback: try to find first div that contains '%' or '空仓' or '：'
                for d in divs:
                    txt = d.get_text()
                    if '%' in txt or '空仓' in txt or '：' in txt:
                        hold_elem = d
                        break
                # last resort: use td itself
                if hold_elem is None:
                    hold_elem = td
            holdings = _parse_holdings_from_element(hold_elem)

        follow_id: Optional[int] = None
        follow_a = tbl.find("a", class_="follow")
        if follow_a:
            href2 = follow_a.get("href", "")
            decoded = _decode_nested_href(href2)
            m2 = RE_FOLLOW.search(decoded)
            if m2:
                try:
                    follow_id = int(m2.group(1))
                except Exception:
                    follow_id = None

        results.append({
            "short_id": short_id,
            "title": title,
            "detail_id": detail_id,
            "follow_id": follow_id,
            "time": time_str,
            "op_text": op_text,
            "holdings": holdings
        })

    return results