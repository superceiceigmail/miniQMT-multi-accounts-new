"""
gui/reconcile_ui.py

Compatibility / helper layer used by GUI and scripts to:
 - load allocation and parsed strategies
 - load account asset snapshot and positions
 - provide name->code resolution and core mappings
 - extract holdings from parsed strategy items
 - provide mama/proportion loaders per-account

This file centralizes mapping/normalization by reusing:
 - utils.name_code_loader.build_name_to_code_map / load_code_index / resolve_name_to_code
 - utils.code_normalizer.normalize_code / canonical_variants / match_available_code_in_dict
 - utils.stock_data_loader.load_stock_code_maps

The goal: keep previous external function names/behaviour while removing duplicated
suffix rules and ensuring consistent normalize/matching across the codebase.
"""
from datetime import datetime
from decimal import Decimal
import os
import re
import json
import collections
from typing import Optional, Dict, Any, List, Tuple

# Reuse shared utilities
from utils.name_code_loader import build_name_to_code_map, load_code_index, resolve_name_to_code as _loader_resolve
from utils.code_normalizer import normalize_code, canonical_variants as canonical_variants_from_normalizer, _code_base as _cn_code_base  # noqa: F401
from utils.stock_data_loader import load_stock_code_maps

# Paths (relative to repo root)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_STOCK_CODE_PATH = os.path.join(REPO_ROOT, "core_parameters", "stocks", "core_stock_code.json")
MAMA_PATH = os.path.join(REPO_ROOT, "core_parameters", "account", "mama.json")
ACCOUNT_CONFIG_DIR = os.path.join(REPO_ROOT, "core_parameters", "account")
CODE_INDEX_PATH = os.path.join(REPO_ROOT, "yunfei_ball", "code_index.json")
ALLOCATION_PATH = os.path.join(REPO_ROOT, "yunfei_ball", "allocation.json")

# Global caches
NAME_TO_CODE_GLOBAL: Dict[str, str] = {}
_NAME_TO_CODE_LOADED = False
_CORE_STOCK_CODE_CACHE: Optional[Dict[str, str]] = None
_MAMA_CACHE: Optional[float] = None
_MAMA_PROPORTIONS_CACHE: Dict[str, Tuple[Decimal, Decimal]] = {}

# ----------------- small I/O helpers -----------------
def _load_json(path: str) -> Optional[Any]:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def _safe_decimal(v) -> Decimal:
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal('0')

# ----------------- name/code helpers -----------------
def _code_base(code: str) -> str:
    if not code:
        return ''
    s = str(code).strip()
    m = re.match(r'(\d{6})', s)
    return m.group(1) if m else s

def _canonical_variants(code: str):
    return canonical_variants_from_normalizer(code)

def _ensure_name_to_code_loaded():
    """
    Populate NAME_TO_CODE_GLOBAL from code_index.json via shared loader.
    """
    global NAME_TO_CODE_GLOBAL, _NAME_TO_CODE_LOADED
    if _NAME_TO_CODE_LOADED:
        return
    try:
        mapping = build_name_to_code_map(CODE_INDEX_PATH)
        if mapping:
            NAME_TO_CODE_GLOBAL = mapping
    except Exception:
        NAME_TO_CODE_GLOBAL = {}
    _NAME_TO_CODE_LOADED = True

def resolve_name_to_code(name: str) -> Optional[str]:
    """
    Resolve a human-readable name to a normalized code (with suffix).
    Priority:
      1) yunfei_ball/code_index.json via build_name_to_code_map
      2) core stock code file (core_parameters)
      3) treat 6-digit numeric name as code and normalize with normalize_code
    """
    if not name:
        return None
    _ensure_name_to_code_loaded()
    nm = str(name).strip()
    # direct mapping from code_index
    if NAME_TO_CODE_GLOBAL and nm in NAME_TO_CODE_GLOBAL:
        return NAME_TO_CODE_GLOBAL.get(nm)
    # try core stock code maps
    try:
        core_map, get_stock_code_func, reverse_map = load_stock_code_maps()
        if nm in core_map:
            return core_map.get(nm)
    except Exception:
        pass
    # if numeric 6-digit
    if re.fullmatch(r'\d{6}', nm):
        return normalize_code(nm)
    # fallback: try loader resolve (alias)
    try:
        return _loader_resolve(nm, CODE_INDEX_PATH)
    except Exception:
        return None

# compatibility alias used by some scripts
def load_name_to_code_map(path: Optional[str]):
    return build_name_to_code_map(path)

# ----------------- core stock code map -----------------
def _load_core_stock_code_map() -> Dict[str, str]:
    """
    Load core_parameters/stocks/core_stock_code.json and return name -> code mapping.
    Accepts both shapes:
      - name -> code
      - code -> name  (will invert to name -> code)
    """
    global _CORE_STOCK_CODE_CACHE
    if _CORE_STOCK_CODE_CACHE is not None:
        return _CORE_STOCK_CODE_CACHE
    _CORE_STOCK_CODE_CACHE = {}
    try:
        p = os.path.abspath(CORE_STOCK_CODE_PATH)
        if not os.path.exists(p):
            return _CORE_STOCK_CODE_CACHE
        data = _load_json(p) or {}
        if not isinstance(data, dict):
            return _CORE_STOCK_CODE_CACHE
        sample_key = next(iter(data.keys()), None)
        if sample_key and re.fullmatch(r'\d{6}(\.(SH|SZ))?', str(sample_key).strip(), re.IGNORECASE):
            # file maps code->name; invert to name->code
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
    except Exception:
        _CORE_STOCK_CODE_CACHE = {}
    return _CORE_STOCK_CODE_CACHE

# ----------------- mama proportion loaders -----------------
def _parse_proportion_value(prop) -> Optional[float]:
    """
    Accept number, numeric string, or percent string like '50%'.
    Return float proportion (e.g. 0.5) or None.
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
            return float(s)
    except Exception:
        return None

def _load_mama_proportion() -> float:
    """
    Legacy single 'proportion' loader.
    """
    global _MAMA_CACHE
    if _MAMA_CACHE is not None:
        return _MAMA_CACHE
    _MAMA_CACHE = 1.0
    try:
        if os.path.exists(MAMA_PATH):
            d = _load_json(MAMA_PATH) or {}
            if isinstance(d, dict):
                prop = d.get("proportion")
                parsed = _parse_proportion_value(prop)
                if parsed is not None:
                    _MAMA_CACHE = parsed
    except Exception:
        _MAMA_CACHE = 1.0
    return _MAMA_CACHE

def _load_mama_proportions_for_account(account_id: str) -> Tuple[Decimal, Decimal]:
    """
    Load per-account (proportion_ETF, proportion_YF) with priority:
      1) core_parameters/account/{account_id}.json
      2) core_parameters/account/mama.json per-account entry
      3) top-level in mama.json
      4) default (1.0, 1.0)
    Returns (Decimal(etf), Decimal(yf))
    """
    global _MAMA_PROPORTIONS_CACHE
    if not account_id:
        account_id = str(account_id or "")
    if account_id in _MAMA_PROPORTIONS_CACHE:
        return _MAMA_PROPORTIONS_CACHE[account_id]
    try:
        # 1) per-account file
        acct_file = os.path.join(ACCOUNT_CONFIG_DIR, f"{account_id}.json")
        if os.path.exists(acct_file):
            data = _load_json(acct_file) or {}
            if isinstance(data, dict):
                candidates = [data]
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
        # 2) try mama.json
        mama = _load_json(MAMA_PATH) or {}
        if isinstance(mama, dict):
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
            # 3) top-level keys
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
            # 4) default
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
    result = (Decimal('1.0'), Decimal('1.0'))
    _MAMA_PROPORTIONS_CACHE[account_id] = result
    return result

# ----------------- allocation / parsed strategies / account data -----------------
def load_allocation_list() -> List[dict]:
    d = _load_json(ALLOCATION_PATH)
    return d or []

def load_parsed_strategies() -> List[dict]:
    candidates = [
        os.path.join(REPO_ROOT, "yunfei_ball", "latest_strategies_normalized.json"),
        os.path.join(REPO_ROOT, "debug_out_items.json"),
        os.path.join(REPO_ROOT, "yunfei_ball", "debug_parsed_strategies.json")
    ]
    for p in candidates:
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

def load_account_asset_latest(account_id: str) -> Optional[dict]:
    p = os.path.join(REPO_ROOT, "public", "template_account_info", f"template_account_asset_info.json")
    data = _load_json(p)
    if not data:
        return None
    if isinstance(data, dict) and data.get('asset'):
        return data.get('asset')
    return data

def load_account_positions_latest(account_id: str) -> List[dict]:
    p = os.path.join(REPO_ROOT, "account_data", "positions", f"position_{account_id}.json")
    data = _load_json(p)
    if not data:
        return []
    if isinstance(data, dict) and data.get('positions'):
        return data.get('positions')
    return data if isinstance(data, list) else []

# ----------------- holdings extraction helpers -----------------
def _parse_holding_block_entry(s: str):
    """
    Parse a single holding block entry like "创业板50: 10%" or "StockName 10%".
    Returns (name, pct) where pct may be None.
    """
    if not s:
        return None, None
    s = s.strip()
    # find percentage like 10% or 10.5%
    m = re.search(r'([\d\.]+)\s*%', s)
    pct = None
    if m:
        try:
            pct = float(m.group(1))
        except Exception:
            pct = None
        # remove bracketed text and split by colon
        name = re.sub(r'\[.*?\]', '', s)
        name = re.split(r'[:：]', name)[0].strip()
        return name, pct
    # fallback: last token endswith '%'
    parts = s.split()
    if len(parts) >= 2 and parts[-1].endswith('%'):
        try:
            pct = float(parts[-1].rstrip('%'))
            name = ' '.join(parts[:-1])
            return name.strip(), pct
        except Exception:
            pass
    return s, None

def _extract_holdings_from_strategy_item(it: dict) -> List[Tuple[str, Optional[float]]]:
    """
    Extract holdings list from a parsed strategy item in flexible formats.
    Returns list of tuples (name, pct_or_None).
    """
    res = []
    if not it:
        return res
    raw_holdings = it.get('holdings') or it.get('holding') or it.get('holding_block') or it.get('holding_block_raw') or None
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
    # sometimes holding_block is nested differently
    holding_block = it.get('holding_block') or it.get('holding_block_raw') or None
    if isinstance(holding_block, list):
        for part in holding_block:
            nm, pc = _parse_holding_block_entry(str(part))
            res.append((nm, pc))
        return res
    # try raw parsed payload
    if it.get('_raw') and isinstance(it['_raw'], dict):
        raw = it['_raw']
        if isinstance(raw.get('holdings'), list):
            for h in raw.get('holdings'):
                if isinstance(h, dict):
                    res.append((h.get('name'), h.get('pct')))
    return res

# ----------------- optional helpers used by reconcile scripts -----------------
def _find_current_mv_for_code(code_key: str, current_by_code: dict):
    """
    Try candidate variants and return (market_value Decimal or 0, matched_code_or_None)
    """
    if not code_key:
        return Decimal("0"), None
    variants = _canonical_variants(code_key)
    for v in variants:
        if v in current_by_code:
            mv = current_by_code[v].get("market_value") if isinstance(current_by_code[v], dict) else current_by_code[v]
            try:
                return Decimal(str(mv or 0)), v
            except Exception:
                return Decimal("0"), v
    base = _code_base(code_key)
    if base in current_by_code:
        mv = current_by_code[base].get("market_value") if isinstance(current_by_code[base], dict) else current_by_code[base]
        try:
            return Decimal(str(mv or 0)), base
        except Exception:
            return Decimal("0"), base
    return Decimal("0"), None

# Public alias for other modules (keeps previous name)
def resolve_name_to_code_public(name: str) -> Optional[str]:
    return resolve_name_to_code(name)

# End of file