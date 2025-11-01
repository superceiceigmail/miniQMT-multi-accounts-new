# GUI helper: reconcile yunfei allocation vs account positions
# NOTE: Modified to load per-account proportions when available.
import os
import json
import re
import sys
import subprocess
import webbrowser
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from tkinter import Toplevel, BOTH, X, messagebox
from ttkbootstrap.scrolled import ScrolledText
import ttkbootstrap as tb

# Try to reuse existing yunfei helpers if available
try:
    from yunfei_ball.yunfei_connect_follow import find_strategy_by_id_and_bracket, load_name_to_code_map, CODE_INDEX_PATH
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
TRADE_PLAN_DRAFT_PATH = os.path.join(os.path.dirname(__file__), "..", "tradeplan", "trade_plan_draft.json")
REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
VIZ_SCRIPT = os.path.join(SCRIPTS_DIR, "viz_per_instrument.py")
VIZ_SCRIPT_FALLBACK = os.path.join(BASE_DIR, "viz_blocks.py")
CORE_STOCK_CODE_PATH = os.path.join(os.path.dirname(__file__), "..", "core_parameters", "stocks", "core_stock_code.json")
MAMA_PATH = os.path.join(os.path.dirname(__file__), "..", "core_parameters", "account", "mama.json")
ACCOUNT_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "core_parameters", "account")

# ---------- utility I/O ----------
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


# ---------- core name->code loader ----------
_CORE_STOCK_CODE_CACHE = None


def _load_core_stock_code_map():
    """
    Load core_parameters/stocks/core_stock_code.json and return mapping name -> code.
    Supports both shapes:
      - { "name": "513500", ... }  OR
      - { "513500": "name", ... }  (we invert to name->code)
    Returns {} on error or missing file.
    """
    global _CORE_STOCK_CODE_CACHE
    if _CORE_STOCK_CODE_CACHE is not None:
        return _CORE_STOCK_CODE_CACHE
    _CORE_STOCK_CODE_CACHE = {}
    try:
        p = os.path.abspath(CORE_STOCK_CODE_PATH)
        if not os.path.exists(p):
            return _CORE_STOCK_CODE_CACHE
        data = _load_json(p)
        if not data or not isinstance(data, dict):
            return _CORE_STOCK_CODE_CACHE
        sample_key = next(iter(data.keys()), None)
        # if keys look like codes, invert mapping (code->name -> name->code)
        if sample_key and re.fullmatch(r'\d{6}(\.(SH|SZ))?', str(sample_key).strip()):
            inv = {}
            for k, v in data.items():
                if v:
                    inv[str(v).strip()] = str(k).strip()
            _CORE_STOCK_CODE_CACHE = inv
        else:
            norm = {}
            for k, v in data.items():
                if v:
                    norm[str(k).strip()] = str(v).strip()
            _CORE_STOCK_CODE_CACHE = norm
        return _CORE_STOCK_CODE_CACHE
    except Exception:
        _CORE_STOCK_CODE_CACHE = {}
        return _CORE_STOCK_CODE_CACHE


# ---------- load mama proportions (per-account) ----------
_MAMA_CACHE = None
# cache map: account_id -> (Decimal(etf), Decimal(yf))
_MAMA_PROPORTIONS_CACHE = {}

def _parse_proportion_value(prop):
    """
    Parse various proportion representations:
      - numeric (0.01, 0.5, 1)
      - numeric string ("0.01", "1")
      - percent string ("1%", "50%")
    Returns float value (e.g. 0.01 for 1%) or None on failure.
    """
    try:
        if prop is None:
            return None
        if isinstance(prop, (int, float)):
            return float(prop)
        if isinstance(prop, str):
            s = prop.strip()
            if s.endswith('%'):
                num = float(s.rstrip('%').strip())
                return float(num / 100.0)
            else:
                return float(s)
    except Exception:
        return None


def _load_mama_proportion():
    """
    Backwards-compatible loader for single 'proportion' (legacy).
    This function does NOT try to infer proportion from unrelated numeric fields.
    """
    global _MAMA_CACHE
    if _MAMA_CACHE is not None:
        return _MAMA_CACHE
    try:
        p = os.path.abspath(MAMA_PATH)
        if not os.path.exists(p):
            _MAMA_CACHE = 1.0
            return _MAMA_CACHE
        d = _load_json(p)
        if not d or not isinstance(d, dict):
            _MAMA_CACHE = 1.0
            return _MAMA_CACHE
        prop = d.get("proportion")
        parsed = _parse_proportion_value(prop)
        if parsed is None:
            _MAMA_CACHE = 1.0
        else:
            _MAMA_CACHE = parsed
        return _MAMA_CACHE
    except Exception:
        _MAMA_CACHE = 1.0
        return _MAMA_CACHE


def _load_mama_proportions_for_account(account_id: str):
    """
    Load proportion_ETF and proportion_YF for a specific account_id.

    Lookup priority:
      1) core_parameters/account/{account_id}.json -> keys proportion_ETF / proportion_YF / proportion
      2) core_parameters/account/mama.json per-account map: mama.json may contain top-level keys named by account_id
         e.g. { "8886006288": {"proportion_ETF": "1", "proportion_YF": "1"}, ... }
      3) core_parameters/account/mama.json top-level keys proportion_ETF/proportion_YF/proportion
      4) default -> (1.0, 1.0)

    Important: DO NOT attempt to infer proportion by picking the first numeric value in the file.
    Returns (Decimal(etf), Decimal(yf))
    """
    global _MAMA_PROPORTIONS_CACHE
    if not account_id:
        account_id = str(account_id or "")
    # cached?
    if account_id in _MAMA_PROPORTIONS_CACHE:
        return _MAMA_PROPORTIONS_CACHE[account_id]
    try:
        # 1) try per-account config file core_parameters/account/{account_id}.json
        acct_file = os.path.join(ACCOUNT_CONFIG_DIR, f"{account_id}.json")
        if os.path.exists(acct_file):
            data = _load_json(acct_file) or {}
            if isinstance(data, dict):
                # Keys can be nested; check top-level and under "account"
                candidates = []
                # top-level
                candidates.append(data)
                # nested account
                if data.get("account") and isinstance(data.get("account"), dict):
                    candidates.append(data.get("account"))
                for entry in candidates:
                    etf_v = _parse_proportion_value(entry.get('proportion_ETF') or entry.get('proportion_etf') or entry.get('proportionETF'))
                    yf_v = _parse_proportion_value(entry.get('proportion_YF') or entry.get('proportion_yf') or entry.get('proportionYF'))
                    if (etf_v is None or yf_v is None) and entry.get('proportion') is not None:
                        single = _parse_proportion_value(entry.get('proportion'))
                        if single is not None:
                            if etf_v is None:
                                etf_v = single
                            if yf_v is None:
                                yf_v = single
                    if etf_v is None:
                        etf_v = 1.0
                    if yf_v is None:
                        yf_v = 1.0
                    result = (Decimal(str(etf_v)), Decimal(str(yf_v)))
                    _MAMA_PROPORTIONS_CACHE[account_id] = result
                    return result
        # 2) try mama.json per-account map
        mama = _load_json(MAMA_PATH) or {}
        if isinstance(mama, dict):
            # if there's a section for this account id
            acct_entry = mama.get(str(account_id))
            if isinstance(acct_entry, dict):
                etf_v = _parse_proportion_value(acct_entry.get('proportion_ETF') or acct_entry.get('proportion_etf') or acct_entry.get('proportionETF'))
                yf_v = _parse_proportion_value(acct_entry.get('proportion_YF') or acct_entry.get('proportion_yf') or acct_entry.get('proportionYF'))
                if (etf_v is None or yf_v is None) and acct_entry.get('proportion') is not None:
                    single = _parse_proportion_value(acct_entry.get('proportion'))
                    if single is not None:
                        if etf_v is None:
                            etf_v = single
                        if yf_v is None:
                            yf_v = single
                if etf_v is None:
                    etf_v = 1.0
                if yf_v is None:
                    yf_v = 1.0
                result = (Decimal(str(etf_v)), Decimal(str(yf_v)))
                _MAMA_PROPORTIONS_CACHE[account_id] = result
                return result
            # 3) try top-level keys in mama.json
            etf = mama.get('proportion_ETF') or mama.get('proportion_etf') or mama.get('proportionETF')
            yf = mama.get('proportion_YF') or mama.get('proportion_yf') or mama.get('proportionYF')
            if (etf is not None) or (yf is not None):
                etf_v = _parse_proportion_value(etf) if etf is not None else None
                yf_v = _parse_proportion_value(yf) if yf is not None else None
                if (etf_v is None or yf_v is None) and mama.get('proportion') is not None:
                    single = _parse_proportion_value(mama.get('proportion'))
                    if single is not None:
                        if etf_v is None:
                            etf_v = single
                        if yf_v is None:
                            yf_v = single
                if etf_v is None:
                    etf_v = 1.0
                if yf_v is None:
                    yf_v = 1.0
                result = (Decimal(str(etf_v)), Decimal(str(yf_v)))
                _MAMA_PROPORTIONS_CACHE[account_id] = result
                return result
            # 4) try default subkey
            default_entry = mama.get('default') or mama.get('DEFAULT')
            if isinstance(default_entry, dict):
                etf_v = _parse_proportion_value(default_entry.get('proportion_ETF') or default_entry.get('proportion'))
                yf_v = _parse_proportion_value(default_entry.get('proportion_YF') or default_entry.get('proportion'))
                if etf_v is None:
                    etf_v = 1.0
                if yf_v is None:
                    yf_v = 1.0
                result = (Decimal(str(etf_v)), Decimal(str(yf_v)))
                _MAMA_PROPORTIONS_CACHE[account_id] = result
                return result
    except Exception:
        pass
    # fallback safe default
    result = (Decimal('1.0'), Decimal('1.0'))
    _MAMA_PROPORTIONS_CACHE[account_id] = result
    return result


# --------- code normalization helpers ----------
def _code_base(code: str) -> str:
    """Return base 6-digit code string from variants like '513500.SH' or '513500'."""
    if not code:
        return ''
    s = str(code).strip()
    m = re.match(r'(\d{6})', s)
    return m.group(1) if m else s


def _canonical_variants(code: str):
    """Return candidate variants for a code: prefer explicit then .SH/.SZ then base"""
    if not code:
        return []
    base = _code_base(code)
    s = str(code).strip()
    if '.' in s:
        parts = s.split('.', 1)
        suf = parts[1].upper() if len(parts) > 1 else ''
        return [f"{base}.{suf}", f"{base}.SH", f"{base}.SZ", base]
    if base and base[0] in ("5", "6","8" ,"9"):
        return [f"{base}.SH", f"{base}.SZ", base]
    else:
        return [f"{base}.SZ", f"{base}.SH", base]


def _find_current_mv_for_code(code_key: str, current_by_code: dict):
    """Try variants and return (market_value Decimal, matched_code_or_None)"""
    if not code_key:
        return Decimal("0"), None
    variants = _canonical_variants(code_key)
    for v in variants:
        if v in current_by_code:
            return current_by_code[v]["market_value"], v
    base = _code_base(code_key)
    if base in current_by_code:
        return current_by_code[base]["market_value"], base
    return Decimal("0"), None


# new helper: resolve code -> friendly name (reverse lookup)
def _resolve_code_to_name(code: str):
    """
    Try to resolve a code (e.g. '513100' or '513100.SH') to a human-friendly name.
    Uses core_parameters/stocks/core_stock_code.json (loaded by _load_core_stock_code_map) by inverting the mapping,
    and falls back to NAME_TO_CODE_GLOBAL if available.
    Returns None when unknown.
    """
    if not code:
        return None
    try:
        core_map = _load_core_stock_code_map()  # name -> code
        # invert by checking values
        base = _code_base(code)
        for name, c in core_map.items():
            if c and _code_base(c) == base:
                return name
        if NAME_TO_CODE_GLOBAL:
            for name, c in NAME_TO_CODE_GLOBAL.items():
                if c and _code_base(c) == base:
                    return name
    except Exception:
        pass
    return None


# --------- holdings parsing ----------
def _parse_holding_block_entry(s: str):
    """
    parse "名称：xx%" 或 "名称:xx%" 或 "名称 xx%" -> return (name, pct_float)
    """
    if not s:
        return None, None
    s = s.strip()
    m = re.search(r'([\d\.]+)\s*%', s)
    pct = None
    if m:
        try:
            pct = float(m.group(1))
        except Exception:
            pct = None
        name = re.sub(r'\[.*?\]', '', s)
        name = re.split(r'[:：]', name)[0].strip()
        return name, pct
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
    Extract holdings list (name, pct) from parsed strategy item.
    """
    res = []
    if not it:
        return res
    raw_holdings = it.get('holdings') or it.get('holding') or it.get('holdings_raw') or None
    if isinstance(raw_holdings, list):
        for h in raw_holdings:
            if isinstance(h, dict):
                name = h.get('name') or h.get('stock_name') or ''
                pct = h.get('pct')
                if pct is None:
                    try:
                        pct = float(h.get('percentage'))
                    except Exception:
                        pct = None
                res.append((name, pct))
            else:
                nm, pc = _parse_holding_block_entry(str(h))
                res.append((nm, pc))
        return res
    holding_block = it.get('holding_block') or it.get('holding_block_raw') or None
    if isinstance(holding_block, list):
        for part in holding_block:
            nm, pc = _parse_holding_block_entry(str(part))
            res.append((nm, pc))
        return res
    if it.get('_raw') and isinstance(it['_raw'], dict):
        raw = it['_raw']
        if isinstance(raw.get('holdings'), list):
            for h in raw.get('holdings'):
                if isinstance(h, dict):
                    res.append((h.get('name'), h.get('pct')))
    return res


# --------- loaders ----------
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
            if isinstance(d, dict) and d.get('items'):
                return d.get('items')
            if isinstance(d, list):
                return d
            if isinstance(d, dict) and d.get('strategies'):
                return d.get('strategies')
            if isinstance(d, dict) and d.get('strategies_normalized_sample'):
                return d.get('strategies_normalized_sample')
    return []


def load_account_asset_latest(account_id):
    p = os.path.join(ASSET_DIR, f"asset_{account_id}.json")
    data = _load_json(p)
    if not data:
        return None
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


# --------- trade plan draft parsing ----------
def _load_trade_plan_draft():
    """
    Load tradeplan/trade_plan_draft.json if present and return its parsed object.
    Returns {} when file missing or parse error.
    """
    try:
        p = os.path.abspath(TRADE_PLAN_DRAFT_PATH)
        if not os.path.exists(p):
            return {}
        d = _load_json(p)
        if not d:
            return {}
        return d
    except Exception:
        return {}


def _extract_entries_from_draft(draft):
    """
    Return list of entries from draft:
      each entry is {'name': str, 'pct': float} or {'name': str, 'amount': float}
    Prefer suggested_pct / pct => will be used to compute amount via total_asset * proportion.
    Fallback to suggested_amount / final_market_value / amount.
    Note: this function does NOT read final_holdings.final_pct — reconcile_for_account will prefer final_holdings if present.
    """
    out = []
    try:
        for key in ('final_suggested_holdings', 'final_holdings', 'final_holdings_info', 'final_holdings_suggested'):
            arr = draft.get(key)
            if isinstance(arr, list) and arr:
                for it in arr:
                    if not isinstance(it, dict):
                        continue
                    name = it.get('name') or it.get('stock_name') or it.get('code') or it.get('stock_code')
                    if 'suggested_pct' in it and it.get('suggested_pct') is not None:
                        try:
                            pct = float(it.get('suggested_pct'))
                            out.append({'name': name, 'pct': pct})
                            continue
                        except Exception:
                            pass
                    if 'pct' in it and it.get('pct') is not None:
                        try:
                            pct = float(it.get('pct'))
                            out.append({'name': name, 'pct': pct})
                            continue
                        except Exception:
                            pass
                    amt = None
                    if 'suggested_amount' in it:
                        amt = it.get('suggested_amount')
                    elif 'final_market_value' in it:
                        amt = it.get('final_market_value')
                    elif 'amount' in it:
                        amt = it.get('amount')
                    if name and amt is not None:
                        out.append({'name': name, 'amount': float(amt)})
                if out:
                    return out
        return out
    except Exception:
        return out


# --------- helper: find reference total asset for draft scaling ----------
def _find_reference_total_from_draft_or_assets(draft):
    """
    Determine a reference total asset to interpret draft absolute amounts against.
    Priority:
      1) draft.get('base_total_asset') if provided (explicit)
      2) maximum total_asset among files in account_data/assets/ (assume main account is largest)
      3) None if no valid reference
    """
    try:
        if isinstance(draft, dict):
            base = draft.get('base_total_asset') or draft.get('reference_total_asset')
            if base:
                try:
                    return Decimal(str(base))
                except Exception:
                    pass
            # Also support explicit per-draft flag 'base_is_percent': if draft stores final_pct we will use that path
        # scan asset files to find largest total_asset
        max_total = None
        if os.path.isdir(ASSET_DIR):
            for fname in os.listdir(ASSET_DIR):
                if not fname.startswith("asset_") or not fname.endswith(".json"):
                    continue
                try:
                    data = _load_json(os.path.join(ASSET_DIR, fname)) or {}
                    candidate = data.get('asset') or data
                    if candidate:
                        t = candidate.get('total_asset') or candidate.get('m_dAsset') or candidate.get('m_dAssets')
                        if t is not None:
                            tdec = Decimal(str(t))
                            if max_total is None or tdec > max_total:
                                max_total = tdec
                except Exception:
                    continue
        return max_total
    except Exception:
        return None


# --------- reconciliation core ----------
def reconcile_for_account(account_id, require_today: bool = False):
    """
    Returns reconciliation dict:
      {
        'account_id': account_id,
        'total_asset': Decimal,
        'rows': [ {stock_code, stock_name, expected_money, current_market_value, diff_money, percent_diff}, ... ],
        'as_of': iso str
      }

    Behavior summary:
      - allocation (YF) uses proportion_YF (per-account if present)
      - draft (ETF/tradeplan) uses proportion_ETF (per-account if present)
      - if draft contains final_holdings with final_pct, prefer those percentages (final_pct/100)
      - draft absolute amounts are scaled to the account's total_asset using a draft reference total if available
    """
    allocation_list = load_allocation_list()
    strategies = load_parsed_strategies()
    draft = _load_trade_plan_draft()
    asset = load_account_asset_latest(account_id)
    if not asset:
        raise RuntimeError(f"找不到账户资产文件 for {account_id}")
    total_asset = Decimal(str(asset.get('total_asset') or asset.get('m_dAsset') or 0))
    positions = load_account_positions_latest(account_id)

    # read two proportions (per-account)
    try:
        proportion_ETF, proportion_YF = _load_mama_proportions_for_account(str(account_id))
    except Exception:
        proportion_ETF = Decimal('1.0')
        proportion_YF = Decimal('1.0')

    # Build current positions map by code and fallback by name (store variants + base)
    current_by_code = {}
    current_by_name = {}
    for p in (positions or []):
        raw_code = (p.get('stock_code') or p.get('code') or '').strip()
        name = p.get('stock_name') or p.get('stock') or ''
        try:
            mv = Decimal(str(p.get('market_value') or 0))
        except Exception:
            mv = Decimal('0')
        if raw_code:
            current_by_code[raw_code] = {'name': name, 'market_value': mv, 'raw': p}
            base = _code_base(raw_code)
            if base not in current_by_code:
                current_by_code[base] = {'name': name, 'market_value': mv, 'raw': p}
        if name:
            cur = current_by_name.get(name, Decimal('0'))
            current_by_name[name] = cur + mv

    expected_by_code = {}
    expected_by_name = {}

    if require_today:
        today_str = datetime.now().strftime('%Y-%m-%d')
        today_date = datetime.strptime(today_str, '%Y-%m-%d').date()
    else:
        today_date = None

    # Aggregate expected from allocation list (yunfei) -> use proportion_YF
    for cfg in allocation_list:
        try:
            config_pct = float(cfg.get('配置仓位', 0)) / 100.0
        except Exception:
            config_pct = 0.0

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

        if today_date:
            strategy_date_str = matched.get('date') or matched.get('time') or ''
            strategy_date = None
            try:
                strategy_date = datetime.strptime(strategy_date_str.split()[0], '%Y-%m-%d').date() if strategy_date_str else None
            except Exception:
                strategy_date = None
            if not strategy_date or strategy_date < today_date:
                continue

        holdings = _extract_holdings_from_strategy_item(matched)
        for name, pct in holdings:
            if not name or pct is None:
                continue
            try:
                frac = float(pct) / 100.0
            except Exception:
                frac = 0.0
            # apply proportion_YF for yunfei/allocation parts
            expected_money = (Decimal(str(frac * config_pct)) * total_asset * Decimal(str(proportion_YF))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            code = resolve_name_to_code(name)
            if code:
                base = _code_base(code)
                prev = expected_by_code.get(base, Decimal('0'))
                expected_by_code[base] = (prev + expected_money).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            else:
                prev = expected_by_name.get(name, Decimal('0'))
                expected_by_name[name] = (prev + expected_money).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # Merge GUI draft suggested holdings
    # For draft 'amount' entries, we will attempt to scale them to this account's total_asset
    # using either a draft-provided base_total_asset or the max total_asset across assets dir.
    draft_entries = []
    if draft:
        # If draft contains final_holdings with final_pct, prefer that
        final_holdings = draft.get('final_holdings') or draft.get('final_holdings_info') or draft.get('final_holdings_suggested')
        if isinstance(final_holdings, list) and final_holdings:
            # convert final_holdings entries into entries with 'pct' field (user told us final_pct should be divided by 100)
            for it in final_holdings:
                name = it.get('name') or it.get('stock_name') or ''
                fp = it.get('final_pct') if it.get('final_pct') is not None else it.get('final_pct_suggested') if it.get('final_pct_suggested') is not None else None
                if fp is not None:
                    try:
                        pct_val = float(fp)
                        draft_entries.append({'name': name, 'pct': pct_val})
                    except Exception:
                        pass
        else:
            # fallback: use the generic extractor only if no final_holdings present
            draft_entries = _extract_entries_from_draft(draft)

    # determine reference total for draft absolute amounts
    draft_reference_total = None
    if draft:
        draft_reference_total = _find_reference_total_from_draft_or_assets(draft)

    # compute draft contributions -> use proportion_ETF for draft/tradeplan parts
    core_map = _load_core_stock_code_map()
    for ent in draft_entries:
        name_key = str(ent.get('name') or '').strip()
        if not name_key:
            continue
        amt_decimal = None
        if 'pct' in ent and ent.get('pct') is not None:
            try:
                # treat provided pct as percent (e.g. 2.23 -> 2.23%)
                pct_raw = Decimal(str(ent.get('pct')))
                pct_fraction = pct_raw / Decimal('100')
                amt_decimal = (pct_fraction) * total_asset * Decimal(str(proportion_ETF))
            except Exception:
                amt_decimal = None
        elif 'amount' in ent and ent.get('amount') is not None:
            try:
                raw_amt = Decimal(str(ent.get('amount')))
                # If a reference total exists and differs from current total_asset, scale the draft amount
                if draft_reference_total and draft_reference_total != Decimal('0') and draft_reference_total != total_asset:
                    try:
                        scale = (total_asset / draft_reference_total)
                        amt_decimal = (raw_amt * scale) * Decimal(str(proportion_ETF))
                    except Exception:
                        # fallback: just multiply by proportion_ETF
                        amt_decimal = raw_amt * Decimal(str(proportion_ETF))
                else:
                    # no reference available: treat amount as absolute for this account but still apply proportion_ETF
                    amt_decimal = raw_amt * Decimal(str(proportion_ETF))
            except Exception:
                amt_decimal = None
        if amt_decimal is None:
            continue
        # map name to code
        mapped_code = None
        if core_map and name_key in core_map:
            mapped_code = core_map.get(name_key)
        if not mapped_code and re.fullmatch(r'\d{6}(\.(SH|SZ))?', name_key, re.IGNORECASE):
            mapped_code = name_key
        if not mapped_code:
            try:
                mapped_code = resolve_name_to_code(name_key)
            except Exception:
                mapped_code = None
        # add to expected sums
        if mapped_code:
            base = _code_base(mapped_code)
            prev = expected_by_code.get(base, Decimal('0'))
            expected_by_code[base] = (prev + amt_decimal).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        else:
            prev = expected_by_name.get(name_key, Decimal('0'))
            expected_by_name[name_key] = (prev + amt_decimal).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # -------------------------
    # Best-effort merge: try to map expected_by_name -> expected_by_code when possible
    # This avoids duplicate display when the account position has a code but the expected entry was only by name.
    # Strategies:
    #  - If name can be resolved to a code via resolve_name_to_code/core_map -> merge
    #  - Otherwise, if some current_by_code entry has market_value approximately equal to expected_money (small tolerance),
    #    consider that the same instrument and merge.
    # -------------------------
    try:
        # tolerance: 1.0 currency unit or 0.5% of total_asset, whichever larger
        tol = Decimal('1.0')
        try:
            percent_tol = (total_asset * Decimal('0.005'))  # 0.5% of total asset
            if percent_tol > tol:
                tol = percent_tol
        except Exception:
            pass

        names_to_remove = []
        for name, exp_money in list(expected_by_name.items()):
            # skip empty/placeholder names quickly
            if not name or str(name).strip() in ('', '未知股票', '未知'):
                # try to at least find a best code match by amount if possible
                matched_flag = False
                for code_k, info in current_by_code.items():
                    cur_mv = info.get('market_value') if isinstance(info.get('market_value'), Decimal) else Decimal(str(info.get('market_value') or 0))
                    try:
                        if abs(cur_mv - exp_money) <= tol:
                            base = _code_base(code_k)
                            prev = expected_by_code.get(base, Decimal('0'))
                            expected_by_code[base] = (prev + exp_money).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                            matched_flag = True
                            break
                    except Exception:
                        continue
                if matched_flag:
                    names_to_remove.append(name)
                continue

            resolved = None
            try:
                resolved = resolve_name_to_code(name)
            except Exception:
                resolved = None
            if resolved:
                base = _code_base(resolved)
                prev = expected_by_code.get(base, Decimal('0'))
                expected_by_code[base] = (prev + exp_money).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                names_to_remove.append(name)
                continue

            # fallback: try to find a current_by_code whose market_value is approx equal to exp_money
            matched = False
            for code_k, info in current_by_code.items():
                cur_mv = info.get('market_value') if isinstance(info.get('market_value'), Decimal) else Decimal(str(info.get('market_value') or 0))
                try:
                    if abs(cur_mv - exp_money) <= tol:
                        base = _code_base(code_k)
                        prev = expected_by_code.get(base, Decimal('0'))
                        expected_by_code[base] = (prev + exp_money).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                        matched = True
                        break
                except Exception:
                    continue
            if matched:
                names_to_remove.append(name)

        for nm in names_to_remove:
            try:
                del expected_by_name[nm]
            except Exception:
                pass
    except Exception:
        # best-effort only, ignore on failure
        pass

    # Build rows
    rows = []
    processed_names = set()

    for code_base, exp_money in expected_by_code.items():
        cur_mv, matched_code = _find_current_mv_for_code(code_base, current_by_code)
        if matched_code:
            name = current_by_code[matched_code].get('name')
            cur_mv = cur_mv or Decimal('0')
        else:
            # try resolve code -> friendly name
            name = _resolve_code_to_name(code_base) or code_base
            cur_mv = cur_mv or Decimal('0')

        if (exp_money == Decimal('0') or exp_money == 0) and (cur_mv == Decimal('0') or cur_mv == 0):
            continue

        diff = (exp_money - cur_mv).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        pctdiff = None
        try:
            pctdiff = (diff / exp_money * Decimal('100')).quantize(Decimal('0.1')) if exp_money != 0 else None
        except Exception:
            pctdiff = None

        display_code_base = _code_base(matched_code or code_base)
        rows.append({
            'stock_code': display_code_base,
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
        if (exp_money == Decimal('0') or exp_money == 0) and (cur_mv == Decimal('0') or cur_mv == 0):
            continue
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

    # Merge duplicate base variants
    merged_map = {}
    final_rows = []
    for r in rows:
        code = r.get('stock_code')
        if not code:
            final_rows.append(r)
            continue
        base = _code_base(code)
        if base not in merged_map:
            merged_map[base] = {
                'stock_code_variants': set(),
                'stock_name_candidates': set(),
                'expected_money': Decimal('0'),
                'current_market_value': Decimal('0')
            }
        gm = merged_map[base]
        gm['stock_code_variants'].add(r.get('stock_code'))
        if r.get('stock_name'):
            gm['stock_name_candidates'].add(r.get('stock_name'))
        try:
            gm['expected_money'] += Decimal(str(r.get('expected_money') or 0))
        except Exception:
            pass
        try:
            gm['current_market_value'] += Decimal(str(r.get('current_market_value') or 0))
        except Exception:
            pass

    for base, g in merged_map.items():
        display_code = None
        for c in sorted(g['stock_code_variants']):
            if '.' in c:
                display_code = c
                break
        if not display_code:
            display_code = next(iter(g['stock_code_variants'])) if g['stock_code_variants'] else base

        chosen_name = None
        for nm in g['stock_name_candidates']:
            if nm and not re.fullmatch(r'\d{6}(\.(SH|SZ))?', nm.strip(), re.IGNORECASE) and nm.strip() != '未知股票':
                chosen_name = nm
                break
        if not chosen_name:
            chosen_name = _resolve_code_to_name(display_code) or (next(iter(g['stock_name_candidates'])) if g['stock_name_candidates'] else display_code)

        if (g['expected_money'] == Decimal('0') or g['expected_money'] == 0) and (g['current_market_value'] == Decimal('0') or g['current_market_value'] == 0):
            continue

        final_rows.append({
            'stock_code': base,
            'stock_name': chosen_name,
            'expected_money': g['expected_money'],
            'current_market_value': g['current_market_value'],
            'diff_money': (g['expected_money'] - g['current_market_value']).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
            'percent_diff': None
        })

    # sort by absolute diff
    def _abs_diff_key(r):
        try:
            return abs((r.get('expected_money') or Decimal('0')) - (r.get('current_market_value') or Decimal('0')))
        except Exception:
            return Decimal('0')

    final_rows.sort(key=_abs_diff_key, reverse=True)

    return {
        'account_id': account_id,
        'total_asset': total_asset,
        'rows': final_rows,
        'as_of': datetime.utcnow().isoformat()
    }


# --------- report saving & visualization ----------
def _ensure_reports_dir():
    try:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        return True
    except Exception:
        return False


def save_report_json(report_obj, account_id):
    """
    Save report_obj to reports/reconcile_{account_id}.json
    """
    if not _ensure_reports_dir():
        return None
    fname = f"reconcile_{account_id}.json"
    path = os.path.join(REPORTS_DIR, fname)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report_obj, f, ensure_ascii=False, indent=2, default=str)
        return path
    except Exception:
        return None


def generate_visualization_from_report(json_path, out_html=None, blocks=30, scale="total", top=100):
    """
    Call viz script to generate HTML and open it.
    """
    if not out_html:
        out_html = os.path.splitext(json_path)[0] + "_viz.html"

    script = VIZ_SCRIPT if os.path.exists(VIZ_SCRIPT) else (VIZ_SCRIPT_FALLBACK if os.path.exists(VIZ_SCRIPT_FALLBACK) else None)
    if not script:
        messagebox.showerror("可视化失败", f"找不到可视化脚本，期待路径：\n{VIZ_SCRIPT}\n或\n{VIZ_SCRIPT_FALLBACK}")
        return None

    cmd = [sys.executable, script, "--json", json_path, "--out", out_html, "--blocks", str(blocks), "--scale", scale, "--top", str(top)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            messagebox.showerror("可视化失败",
                                 f"可视化脚本返回错误 (rc={proc.returncode})\n\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}")
            return None
        out_html_abs = os.path.abspath(out_html)
        webbrowser.open("file://" + out_html_abs)
        return out_html_abs
    except Exception as e:
        messagebox.showerror("可视化失败", f"执行可视化脚本出错：{e}")
        return None


# --------- UI: show reconcile dialog (with export & viz buttons) ----------
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
    dlg.geometry("1000x700")

    ctrl_frame = tb.Frame(dlg)
    ctrl_frame.pack(fill=X, padx=8, pady=6)

    def on_export_json():
        path = save_report_json(res, account_id)
        if path:
            messagebox.showinfo("导出成功", f"已导出对账 JSON:\n{path}")
        else:
            messagebox.showerror("导出失败", "导出对账 JSON 失败，请检查权限和目录")

    def on_generate_viz():
        json_path = save_report_json(res, account_id)
        if not json_path:
            messagebox.showerror("可视化失败", "先导出 JSON 失败，无法生成可视化")
            return
        out_html = os.path.join(REPORTS_DIR, f"reconcile_{account_id}_viz.html")
        result = generate_visualization_from_report(json_path, out_html=out_html, blocks=30, scale="total", top=100)
        if result:
            messagebox.showinfo("已生成并打开可视化", f"已生成可视化并在浏览器打开：\n{result}")

    btn_export = tb.Button(ctrl_frame, text="导出 JSON", bootstyle="primary", command=on_export_json)
    btn_export.pack(side="left", padx=(0, 8))

    btn_viz = tb.Button(ctrl_frame, text="生成可视化", bootstyle="info", command=on_generate_viz)
    btn_viz.pack(side="left", padx=(0, 8))

    st = ScrolledText(dlg, height=40, width=120, bootstyle="info")
    st.pack(fill=BOTH, expand=True, padx=8, pady=(0, 8))

    header = f"账户: {account_id}    总资产(快照): {res['total_asset']}\n"
    header += f"对账时间(UTC): {res['as_of']}\n\n"
    st.insert("end", header)

    st.insert("end", f"{'代码':12} {'名称':32} {'应配置(元)':>14} {'当前市值(元)':>14} {'差额(元)':>14} {'差额%':>8}\n")
    st.insert("end", "-" * 112 + "\n")
    for r in res['rows']:
        code = r['stock_code'] or ''
        name = (r['stock_name'] or '')[:30]
        exp = f"{r['expected_money']:.2f}"
        cur = f"{r['current_market_value']:.2f}"
        diff = f"{r.get('diff_money', Decimal('0')):.2f}"
        pct_val = r.get('percent_diff')
        pct = f"{pct_val}%" if pct_val is not None else ''
        st.insert("end", f"{code:12} {name:32} {exp:>14} {cur:>14} {diff:>14} {pct:>8}\n")
    st.configure(state='disabled')
    return res