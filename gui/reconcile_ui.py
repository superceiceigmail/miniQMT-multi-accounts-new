# GUI helper: reconcile yunfei allocation vs account positions
import os
import json
import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from tkinter import Toplevel, BOTH, X
from ttkbootstrap.scrolled import ScrolledText
import ttkbootstrap as tb

# Reuse existing matching and mapping logic from yunfei module if available
try:
    from yunfei_ball.yunfei_connect_follow import find_strategy_by_id_and_bracket, load_name_to_code_map, CODE_INDEX_PATH
    # prefer name_to_code if module exposed it
    try:
        from yunfei_ball.yunfei_connect_follow import name_to_code as NAME_TO_CODE_GLOBAL
    except Exception:
        NAME_TO_CODE_GLOBAL = None
except Exception:
    find_strategy_by_id_and_bracket = None
    load_name_to_code_map = None
    CODE_INDEX_PATH = None
    NAME_TO_CODE_GLOBAL = None

# Paths
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ALLOCATION_PATH = os.path.join(os.path.dirname(__file__), "..", "yunfei_ball", "allocation.json")
FETCH_CACHE_LATEST = os.path.join(os.path.dirname(__file__), "..", "yunfei_ball", "fetch_cache", "latest_strategies_normalized.json")
DEBUG_OUT_ITEMS = os.path.join(os.path.dirname(__file__), "..", "debug_out_items.json")
ASSET_DIR = os.path.join(os.path.dirname(__file__), "..", "account_data", "assets")
POSITIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "account_data", "positions")

def _load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def _safe_decimal(v):
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal('0')

def _parse_holding_block_entry(s: str):
    """
    parse "名称：xx%" 或 "名称:xx%" 或 "名称 xx%" -> return (name, pct_float)
    """
    if not s:
        return None, None
    # remove surrounding whitespace
    s = s.strip()
    # try extract pct via regex
    m = re.search(r'([\d\.]+)\s*%', s)
    pct = None
    if m:
        try:
            pct = float(m.group(1))
        except Exception:
            pct = None
        # name is part before bracket or separator
        name = re.sub(r'\[.*?\]', '', s)  # strip bracketed tokens
        name = re.split(r'[:：]', name)[0].strip()
        # if name still contains pct fragment at end, strip it
        name = re.sub(r'[\d\.%\s]+$', '', name).strip()
        return name, pct
    # fallback: split by whitespace, last token maybe pct
    parts = s.split()
    if len(parts) >= 2 and parts[-1].endswith('%'):
        try:
            pct = float(parts[-1].rstrip('%'))
            name = ' '.join(parts[:-1])
            return name.strip(), pct
        except Exception:
            pass
    return s, None

def _extract_holdings_from_strategy_item(it):
    """
    Accepts either:
      - parse_b_follow_page style item with 'holdings' list of dicts (with 'name' and 'pct')
      - normalized item with 'holding_block' list of strings like '名称：xx%'
      - legacy _raw etc.
    Returns list of (name, pct_float) entries. If pct is missing use None.
    """
    res = []
    if not it:
        return res
    # prefer raw holdings if present
    raw_holdings = it.get('holdings') or it.get('holding') or it.get('holdings_raw') or None
    if isinstance(raw_holdings, list):
        for h in raw_holdings:
            if isinstance(h, dict):
                name = h.get('name') or h.get('stock_name') or ''
                pct = h.get('pct')
                if pct is None:
                    # try percentage keyed as string
                    try:
                        pct = float(h.get('percentage'))
                    except Exception:
                        pct = None
                res.append((name, pct))
            else:
                # fallback if element is string
                nm, pc = _parse_holding_block_entry(str(h))
                res.append((nm, pc))
        return res

    holding_block = it.get('holding_block') or it.get('holding_block_raw') or None
    if isinstance(holding_block, list):
        for part in holding_block:
            nm, pc = _parse_holding_block_entry(str(part))
            res.append((nm, pc))
        return res

    # fallback: check _raw holdings
    if it.get('_raw') and isinstance(it['_raw'], dict):
        raw = it['_raw']
        if isinstance(raw.get('holdings'), list):
            for h in raw.get('holdings'):
                if isinstance(h, dict):
                    res.append((h.get('name'), h.get('pct')))
    return res

def load_allocation_list():
    data = _load_json(ALLOCATION_PATH)
    if not data:
        return []
    return data

def load_parsed_strategies():
    # priority: latest_strategies_normalized.json -> debug_out_items.json -> yunfei_ball/debug_parsed_strategies.json
    candidates = [FETCH_CACHE_LATEST, DEBUG_OUT_ITEMS,
                  os.path.join(os.path.dirname(__file__), "..", "yunfei_ball", "debug_parsed_strategies.json")]
    for p in candidates:
        p = os.path.abspath(p)
        if os.path.exists(p):
            d = _load_json(p)
            if not d:
                continue
            # if file is reconcile result (has 'batches' etc), try to extract items
            if isinstance(d, dict) and d.get('items'):
                return d.get('items')
            # if it's an array of items
            if isinstance(d, list):
                return d
            # if it's normalized wrapper with 'strategies' key
            if isinstance(d, dict) and d.get('strategies') :
                return d.get('strategies')
            # when debug_parsed_strategies.json contains 'strategies_normalized_sample'
            if isinstance(d, dict) and d.get('strategies_normalized_sample'):
                return d.get('strategies_normalized_sample')
    return []

def load_account_asset_latest(account_id):
    p = os.path.join(ASSET_DIR, f"asset_{account_id}.json")
    data = _load_json(p)
    if not data:
        return None
    # data format: {"last_update": "...", "asset": {...}}
    return data.get('asset') or data

def load_account_positions_latest(account_id):
    p = os.path.join(POSITIONS_DIR, f"position_{account_id}.json")
    data = _load_json(p)
    if not data:
        return []
    return data.get('positions') or data

def resolve_name_to_code(name):
    # try global map if loaded
    if NAME_TO_CODE_GLOBAL:
        return NAME_TO_CODE_GLOBAL.get(name)
    if load_name_to_code_map and CODE_INDEX_PATH:
        try:
            mapping = load_name_to_code_map(CODE_INDEX_PATH)
            return mapping.get(name)
        except Exception:
            return None
    return None
# (Replace the existing reconcile_for_account function in gui/reconcile_ui.py with the following)

def reconcile_for_account(account_id, require_today: bool = False):
    """
    Returns a dict with reconciliation rows for given account_id.
    If require_today is True, only strategies with strategy_date >= today are considered (original behavior).
    If require_today is False (default), include matched strategies regardless of parsed strategy date,
    which is useful for reconciliation/debugging when parsed items are from previous day(s).
    """
    allocation_list = load_allocation_list()
    strategies = load_parsed_strategies()
    asset = load_account_asset_latest(account_id)
    if not asset:
        raise RuntimeError(f"找不到账户资产文件 for {account_id}")
    total_asset = Decimal(str(asset.get('total_asset') or asset.get('m_dAsset') or 0))
    positions = load_account_positions_latest(account_id)

    # Build current positions map by code and fallback by name
    current_by_code = {}
    current_by_name = {}
    for p in (positions or []):
        code = (p.get('stock_code') or p.get('code') or '').strip()
        name = p.get('stock_name') or p.get('stock_name') or p.get('stock', '') or ''
        try:
            mv = Decimal(str(p.get('market_value') or 0))
        except Exception:
            mv = Decimal('0')
        if code:
            current_by_code[code] = {'name': name, 'market_value': mv, 'raw': p}
        if name:
            cur = current_by_name.get(name, Decimal('0'))
            current_by_name[name] = cur + mv

    expected_by_code = {}
    expected_by_name = {}

    # If caller wants to restrict to today's or future strategies, compute today_date
    if require_today:
        today_str = datetime.now().strftime('%Y-%m-%d')
        today_date = datetime.strptime(today_str, '%Y-%m-%d').date()
    else:
        today_date = None

    for cfg in allocation_list:
        try:
            config_pct = float(cfg.get('配置仓位', 0)) / 100.0
        except Exception:
            config_pct = 0.0

        # find matching strategy in parsed strategies
        matched = None
        if find_strategy_by_id_and_bracket:
            try:
                matched = find_strategy_by_id_and_bracket(cfg, strategies)
            except Exception:
                matched = None
        else:
            json_name = (cfg.get('策略名称') or '').strip()
            for s in strategies:
                web_full_name = (s.get('name') or s.get('title') or '').strip()
                if web_full_name.endswith(json_name) and json_name:
                    matched = s
                    break

        if not matched:
            continue

        # If require_today True, enforce date >= today_date
        if today_date:
            strategy_date_str = matched.get('date') or matched.get('time') or ''
            strategy_date = None
            try:
                # try to parse YYYY-MM-DD from 'time' or 'date'
                strategy_date = datetime.strptime(strategy_date_str.split()[0], '%Y-%m-%d').date() if strategy_date_str else None
            except Exception:
                strategy_date = None
            if not strategy_date or strategy_date < today_date:
                # skip this strategy when require_today is True
                continue

        holdings = _extract_holdings_from_strategy_item(matched)
        for name, pct in holdings:
            if not name or pct is None:
                continue
            try:
                frac = float(pct) / 100.0
            except Exception:
                frac = 0.0
            expected_money = (Decimal(str(frac * config_pct)) * total_asset).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            code = resolve_name_to_code(name)
            if code:
                prev = expected_by_code.get(code, Decimal('0'))
                expected_by_code[code] = (prev + expected_money).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            else:
                prev = expected_by_name.get(name, Decimal('0'))
                expected_by_name[name] = (prev + expected_money).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # Build result rows (same as original)
    rows = []
    processed_names = set()

    for code, exp_money in expected_by_code.items():
        name = None
        if code in current_by_code:
            name = current_by_code[code].get('name')
            cur_mv = current_by_code[code].get('market_value') or Decimal('0')
        else:
            name = code
            cur_mv = Decimal('0')
        diff = (exp_money - cur_mv).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        pctdiff = None
        try:
            pctdiff = (diff / exp_money * Decimal('100')).quantize(Decimal('0.1')) if exp_money != 0 else None
        except Exception:
            pctdiff = None
        rows.append({
            'stock_code': code,
            'stock_name': name,
            'expected_money': exp_money,
            'current_market_value': cur_mv,
            'diff_money': diff,
            'percent_diff': pctdiff
        })
        processed_names.add(name)

    for name, exp_money in expected_by_name.items():
        if name in processed_names:
            continue
        cur_mv = Decimal(str(current_by_name.get(name, Decimal('0'))))
        diff = (exp_money - cur_mv).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        pctdiff = None
        try:
            pctdiff = (diff / exp_money * Decimal('100')).quantize(Decimal('0.1')) if exp_money != 0 else None
        except Exception:
            pctdiff = None
        rows.append({
            'stock_code': None,
            'stock_name': name,
            'expected_money': exp_money,
            'current_market_value': cur_mv,
            'diff_money': diff,
            'percent_diff': pctdiff
        })

    rows.sort(key=lambda r: abs(r['diff_money']), reverse=True)
    return {
        'account_id': account_id,
        'total_asset': total_asset,
        'rows': rows,
        'as_of': datetime.utcnow().isoformat()
    }

# GUI: show reconcile dialog (simple)
def show_reconcile_dialog(root_window, account_id):
    """
    root_window: main Tk root or master
    account_id: '8886006288'
    """
    try:
        res = reconcile_for_account(account_id)
    except Exception as e:
        dlg = Toplevel(root_window)
        tb.Label(dlg, text=f"对账失败: {e}").pack(padx=10, pady=10)
        return

    dlg = Toplevel(root_window)
    dlg.title(f"云飞对账 - 账户 {account_id}")
    dlg.geometry("900x600")
    st = ScrolledText(dlg, height=40, width=120, bootstyle="info")
    st.pack(fill=BOTH, expand=True)

    header = f"账户: {account_id}    总资产(快照): {res['total_asset']}\n"
    header += f"对账时间(UTC): {res['as_of']}\n\n"
    st.insert("end", header)

    # table header
    st.insert("end", f"{'代码':12} {'名称':24} {'应配置(元)':>14} {'当前市值(元)':>14} {'差额(元)':>14} {'差额%':>8}\n")
    st.insert("end", "-"*92 + "\n")
    for r in res['rows']:
        code = r['stock_code'] or ''
        name = (r['stock_name'] or '')[:22]
        exp = f"{r['expected_money']:.2f}"
        cur = f"{r['current_market_value']:.2f}"
        diff = f"{r['diff_money']:.2f}"
        pct = f"{r['percent_diff']}%" if r['percent_diff'] is not None else ''
        st.insert("end", f"{code:12} {name:24} {exp:>14} {cur:>14} {diff:>14} {pct:>8}\n")
    st.configure(state='disabled')
    return res