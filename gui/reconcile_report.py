"""
gui/reconcile_report.py

对账/展示层的工具。提供：
- 解析并加载 allocation / parsed strategies
- 将策略预期持仓（yunfei 页面 + draft）合并到 expected_by_code
- 将账户当前持仓标准化为 current_by_code/current_by_name
- 生成 reconciliation report：both / yunfei_only / positions_only
- 若需要，返回简化的 reconcile_for_account 用于 GUI/脚本快速查看

此文件重用 utils.name_code_loader 与 utils.code_normalizer 以统一 code 后缀处理规则。
保持向后兼容原有接口（脚本、工具可能直接 import 这些函数）。
"""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import os
import json
import re
import collections
from typing import Optional, Dict, Any, List, Tuple

# reuse loader & normalizer
from utils.name_code_loader import load_code_index as load_code_index_from_loader, build_name_to_code_map
from utils.code_normalizer import normalize_code, canonical_variants as canonical_variants_from_normalizer, _code_base as _cn_code_base  # noqa: F401

# Note: _code_base wrapper kept for compatibility below
def _code_base(code: str) -> str:
    if not code:
        return ''
    s = str(code).strip()
    m = re.match(r'(\d{6})', s)
    return m.group(1) if m else s

def _canonical_variants(code: str):
    # wrapper to keep existing call sites working
    return canonical_variants_from_normalizer(code)

def _find_current_mv_for_code(code_key: str, current_by_code: dict) -> Tuple[Decimal, Optional[str]]:
    """
    Try variants and return (market_value Decimal, matched_code_or_None)
    current_by_code: mapping of code-> { name, market_value, raw }
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

# file paths
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TRADE_PLAN_DRAFT_PATH = os.path.join(REPO_ROOT, "tradeplan", "trade_plan_draft.json")
CORE_STOCK_CODE_PATH = os.path.join(REPO_ROOT, "core_parameters", "stocks", "core_stock_code.json")
MAMA_PATH = os.path.join(REPO_ROOT, "core_parameters", "account", "mama.json")
CODE_INDEX_PATH = os.path.join(REPO_ROOT, "yunfei_ball", "code_index.json")
NAME_VS_CODE_PATH = os.path.join(REPO_ROOT, "utils", "stocks_code_search_tool", "stocks_data", "name_vs_code.json")
ALLOCATION_PATH = os.path.join(REPO_ROOT, "yunfei_ball", "allocation.json")

# ---------- code_index loader ----------
def _load_code_index():
    """
    Return the content of yunfei_ball/code_index.json via shared loader (cached).
    """
    try:
        return load_code_index_from_loader(CODE_INDEX_PATH)
    except Exception:
        # fallback: try read file directly
        try:
            if os.path.exists(CODE_INDEX_PATH):
                with open(CODE_INDEX_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f) or {}
        except Exception:
            pass
    return {}

def _resolve_code_to_name(code: str) -> Optional[str]:
    """
    Try to resolve a code (e.g. '513100' or '513100.SH') to a human-friendly name.
    Uses code_index first, then name_vs_code file if present.
    """
    if not code:
        return None
    base = str(code).split('.')[0]
    idx = _load_code_index()
    if base in idx and isinstance(idx[base], list) and idx[base]:
        return idx[base][0]
    try:
        if os.path.exists(NAME_VS_CODE_PATH):
            nm = json.load(open(NAME_VS_CODE_PATH, 'r', encoding='utf-8'))
            if code in nm:
                return nm.get(code)
            for s in (".SH", ".SZ"):
                k = base + s
                if k in nm:
                    return nm.get(k)
    except Exception:
        pass
    return None

# ---------- core stock code map (for scripts that rely on core mapping) ----------
_CORE_STOCK_CODE_CACHE = None
def _load_core_stock_code_map() -> Dict[str, str]:
    global _CORE_STOCK_CODE_CACHE
    if _CORE_STOCK_CODE_CACHE is not None:
        return _CORE_STOCK_CODE_CACHE
    _CORE_STOCK_CODE_CACHE = {}
    try:
        if os.path.exists(CORE_STOCK_CODE_PATH):
            data = json.load(open(CORE_STOCK_CODE_PATH, 'r', encoding='utf-8')) or {}
            if not isinstance(data, dict):
                _CORE_STOCK_CODE_CACHE = {}
                return _CORE_STOCK_CODE_CACHE
            # Detect whether core file is name->code or code->name and normalize to name->code
            sample_key = next(iter(data.keys()), None)
            if sample_key and re.fullmatch(r'\d{6}(\.(SH|SZ))?', str(sample_key).strip()):
                # file maps code->name; invert
                inv = {}
                for k, v in data.items():
                    if v:
                        inv[str(v).strip()] = str(k).strip()
                _CORE_STOCK_CODE_CACHE = inv
            else:
                # file likely name->code
                norm = {}
                for k, v in data.items():
                    if v:
                        norm[str(k).strip()] = str(v).strip()
                _CORE_STOCK_CODE_CACHE = norm
    except Exception:
        _CORE_STOCK_CODE_CACHE = {}
    return _CORE_STOCK_CODE_CACHE

# ---------- mama proportion ----------
_MAMA_CACHE = None
def _load_mama_proportion() -> float:
    global _MAMA_CACHE
    if _MAMA_CACHE is not None:
        return _MAMA_CACHE
    _MAMA_CACHE = 1.0
    try:
        if os.path.exists(MAMA_PATH):
            d = json.load(open(MAMA_PATH, 'r', encoding='utf-8')) or {}
            if isinstance(d, dict):
                prop = d.get("proportion")
                if prop is None:
                    # try find numeric value
                    for v in d.values():
                        if isinstance(v, (int, float)):
                            prop = v
                            break
                if prop is not None:
                    try:
                        _MAMA_CACHE = float(prop)
                    except Exception:
                        _MAMA_CACHE = 1.0
    except Exception:
        _MAMA_CACHE = 1.0
    return _MAMA_CACHE

# ---------- trade plan draft loader & extractor ----------
def _load_trade_plan_draft() -> dict:
    try:
        if os.path.exists(TRADE_PLAN_DRAFT_PATH):
            d = json.load(open(TRADE_PLAN_DRAFT_PATH, 'r', encoding='utf-8'))
            return d or {}
    except Exception:
        pass
    return {}

def _extract_entries_from_draft(draft: dict) -> List[dict]:
    """
    Extract candidate holding entries from draft structure.
    Support fields:
      - final_suggested_holdings / final_holdings / final_holdings_info lists
      - each item may have: name/stock_name/code/stock_code, suggested_pct, pct, suggested_amount, final_market_value, amount
    Return list of dicts: {'name': ..., 'pct': ...} or {'name': ..., 'amount': ...}
    """
    out = []
    if not draft or not isinstance(draft, dict):
        return out
    try:
        for key in ('final_suggested_holdings', 'final_holdings', 'final_holdings_info'):
            arr = draft.get(key)
            if isinstance(arr, list) and arr:
                for it in arr:
                    if not isinstance(it, dict):
                        continue
                    # name or code field
                    name = it.get('name') or it.get('stock_name') or it.get('code') or it.get('stock_code')
                    # pct fields
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
                    # amount-like fields
                    amt = None
                    if 'suggested_amount' in it:
                        amt = it.get('suggested_amount')
                    elif 'final_market_value' in it:
                        amt = it.get('final_market_value')
                    elif 'amount' in it:
                        amt = it.get('amount')
                    if name and amt is not None:
                        try:
                            out.append({'name': name, 'amount': float(amt)})
                        except Exception:
                            continue
                if out:
                    return out
        return out
    except Exception:
        return out

# ---------- helpers to merge/aggregate ----------
def _merge_rows_by_base(rows: List[dict]) -> List[dict]:
    """
    Merge rows grouped by base code (6-digit) or by name:: prefix for name-only entries.
    Each grouped entry accumulates expected_money and current_market_value.
    Returns list of merged dict rows with keys:
      - stock_code (base or None), stock_name, expected_money (Decimal), current_market_value (Decimal)
    """
    grouped = collections.OrderedDict()
    for r in rows:
        code = r.get('stock_code')
        if not code:
            key = f"name::{r.get('stock_name') or ''}"
        else:
            base_m = re.match(r'(\d{6})', str(code).strip())
            key = base_m.group(1) if base_m else str(code).strip()
        if key not in grouped:
            grouped[key] = {
                'codes': set(),
                'names': set(),
                'expected_money': Decimal('0'),
                'current_market_value': Decimal('0')
            }
        g = grouped[key]
        if r.get('stock_code'):
            g['codes'].add(str(r.get('stock_code')).strip())
        if r.get('stock_name'):
            g['names'].add(str(r.get('stock_name')).strip())
        try:
            g['expected_money'] += Decimal(str(r.get('expected_money') or 0))
        except Exception:
            pass
        try:
            g['current_market_value'] += Decimal(str(r.get('current_market_value') or 0))
        except Exception:
            pass

    merged = []
    for key, g in grouped.items():
        if key.startswith("name::"):
            name = next(iter(g['names'])) if g['names'] else None
            if (g['expected_money'] == Decimal('0') or g['expected_money'] == 0) and (g['current_market_value'] == Decimal('0') or g['current_market_value'] == 0):
                continue
            merged.append({
                'stock_code': None,
                'stock_name': name,
                'expected_money': g['expected_money'],
                'current_market_value': g['current_market_value']
            })
            continue

        # choose display_code preference
        display_code = None
        for c in sorted(g['codes']):
            if '.' in c:
                display_code = c
                break
        if not display_code:
            base = key
            sh = f"{base}.SH"
            sz = f"{base}.SZ"
            if sh in g['codes']:
                display_code = sh
            elif sz in g['codes']:
                display_code = sz
            else:
                display_code = next(iter(g['codes'])) if g['codes'] else key

        # choose friendly name
        chosen_name = None
        for nm in g['names']:
            if nm and not re.fullmatch(r'\d{6}(\.(SH|SZ))?', nm.strip(), re.IGNORECASE) and nm.strip() != '未知股票':
                chosen_name = nm
                break
        if not chosen_name:
            chosen_name = _resolve_code_to_name(display_code) or (next(iter(g['names'])) if g['names'] else display_code)

        if (g['expected_money'] == Decimal('0') or g['expected_money'] == 0) and (g['current_market_value'] == Decimal('0') or g['current_market_value'] == 0):
            continue

        merged.append({
            'stock_code': key,
            'stock_name': chosen_name,
            'expected_money': g['expected_money'],
            'current_market_value': g['current_market_value']
        })
    return merged

# ---------- public utilities used by scripts / GUI ----------
def _load_json(p: str) -> Any:
    try:
        return json.load(open(p, 'r', encoding='utf-8')) or {}
    except Exception:
        return {}

def load_allocation_list() -> List[dict]:
    d = _load_json(ALLOCATION_PATH)
    return d or []

def load_parsed_strategies() -> List[dict]:
    # priority: latest_strategies_normalized.json -> debug_out_items.json -> yunfei_ball/debug_parsed_strategies.json
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

def resolve_name_to_code_public(name: str) -> Optional[str]:
    """
    Public helper: resolve a human name to code using code_index via shared loader.
    """
    mapping = build_name_to_code_map(CODE_INDEX_PATH)
    return mapping.get(name)

def load_account_asset_latest(account_id: str) -> Optional[dict]:
    p = os.path.join(REPO_ROOT, "public", "template_account_info", f"template_account_asset_info.json")
    data = _load_json(p)
    if not data:
        return None
    # some saved formats store 'asset' wrapper
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

# helper to extract holdings from strategy item (copied/compatible with reconcile_ui)
def _parse_holding_block_entry(s: str):
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

def _extract_holdings_from_strategy_item(it: dict) -> List[Tuple[str, Optional[float]]]:
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

# ---------- main reconcile driver (used by GUI) ----------
def reconcile_for_account(account_id: str):
    """
    Simplified reconcile driver used by GUI: loads allocation & parsed strategies,
    maps expected holdings to codes and compare against local saved positions.
    Returns a summary structure for quick viewing.
    """
    allocations = load_allocation_list()
    strategies = load_parsed_strategies()

    # load latest account snapshot files (if present)
    asset_path = os.path.join(REPO_ROOT, "public", "template_account_info", f"template_account_asset_info.json")
    pos_path = os.path.join(REPO_ROOT, "account_data", "positions", f"position_{account_id}.json")
    current_positions = {}
    try:
        pos_data = _load_json(pos_path)
        if isinstance(pos_data, dict) and pos_data.get('positions'):
            for p in pos_data.get('positions'):
                code = p.get('stock_code') or p.get('code') or ''
                if not code:
                    continue
                # normalize keys for easier lookup
                norm = normalize_code(code)
                current_positions[norm] = {
                    "name": p.get('stock_name') or p.get('stock') or '',
                    "market_value": p.get('market_value') or p.get('m_dFVal') or 0,
                    "raw": p
                }
    except Exception:
        current_positions = {}

    return {
        "allocations_count": len(allocations),
        "strategies_count": len(strategies),
        "current_positions_sample": {k: v["market_value"] for k, v in list(current_positions.items())[:40]}
    }

# ---------- generate full reconcile report ----------
def generate_reconcile_report(account_id: str, require_today: bool = False) -> Dict[str, Any]:
    """
    Generate detailed reconcile report for account_id.
    Returns dict with keys: account_id, total_asset, as_of, both, yunfei_only, positions_only
    """
    # import reconcile_ui lazily to avoid circular import
    from gui import reconcile_ui as ru
    # load data
    allocation_list = load_allocation_list()
    strategies = load_parsed_strategies()
    asset = load_account_asset_latest(account_id)
    if not asset:
        raise RuntimeError(f"找不到账户資產文件 for {account_id}")
    total_asset = Decimal(str(asset.get("total_asset") or asset.get("m_dAsset") or 0))

    positions = load_account_positions_latest(account_id)
    current_by_code: Dict[str, dict] = {}
    current_by_name: Dict[str, Decimal] = {}
    for p in (positions or []):
        raw_code = (p.get("stock_code") or p.get("code") or "").strip()
        name = p.get("stock_name") or p.get("stock") or ''
        try:
            mv = Decimal(str(p.get("market_value") or 0))
        except Exception:
            mv = Decimal("0")
        if raw_code:
            # store as-is and also base
            current_by_code[raw_code] = {"name": name, "market_value": mv, "raw": p}
            base = _code_base(raw_code)
            if base not in current_by_code:
                current_by_code[base] = {"name": name, "market_value": mv, "raw": p}
        if name:
            current_by_name[name] = current_by_name.get(name, Decimal("0")) + mv

    expected_by_code: Dict[str, Decimal] = {}
    expected_by_name: Dict[str, Decimal] = {}
    if require_today:
        today_str = datetime.now().strftime('%Y-%m-%d')
        today_date = datetime.strptime(today_str, '%Y-%m-%d').date()
    else:
        today_date = None

    # 1) expected from allocation + parsed strategies
    for cfg in allocation_list:
        try:
            config_pct = float(cfg.get("配置仓位", 0)) / 100.0
        except Exception:
            config_pct = 0.0

        matched = None
        try:
            # find_strategy_by_id_and_bracket defined in yunfei module; import lazily
            from yunfei_ball.yunfei_connect_follow import find_strategy_by_id_and_bracket
            matched = find_strategy_by_id_and_bracket(cfg, strategies)
        except Exception:
            matched = None

        if not matched:
            json_name = (cfg.get("策略名称") or "").strip()
            for s in strategies:
                web_full_name = (s.get('name') or s.get('title') or "").strip()
                if web_full_name.endswith(json_name) and json_name:
                    matched = s
                    break
        if not matched:
            continue

        if today_date:
            strategy_date_str = matched.get('date') or matched.get('time') or ''
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
            expected_money = (Decimal(str(frac * config_pct)) * total_asset).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            code = ru.resolve_name_to_code(name)
            if code:
                base = _code_base(code)
                prev = expected_by_code.get(base, Decimal('0'))
                expected_by_code[base] = (prev + expected_money).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            else:
                prev = expected_by_name.get(name, Decimal('0'))
                expected_by_name[name] = (prev + expected_money).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # 2) merge draft amounts (support suggested_pct -> compute with total_asset * proportion)
    draft = _load_trade_plan_draft()
    if draft:
        entries = _extract_entries_from_draft(draft)
        core_map = _load_core_stock_code_map()
        proportion = _load_mama_proportion()
        for ent in entries:
            name_key = str(ent.get('name') or '').strip()
            if not name_key:
                continue
            amt_decimal = None
            if 'pct' in ent and ent.get('pct') is not None:
                try:
                    pct = Decimal(str(ent.get('pct')))
                    amt_decimal = (pct / Decimal('100')) * total_asset * Decimal(str(proportion))
                except Exception:
                    amt_decimal = None
            elif 'amount' in ent and ent.get('amount') is not None:
                try:
                    amt_decimal = Decimal(str(ent.get('amount')))
                except Exception:
                    amt_decimal = None
            if amt_decimal is None:
                continue
            mapped_code = None
            if core_map and name_key in core_map:
                mapped_code = core_map.get(name_key)
            if not mapped_code and re.fullmatch(r'\d{6}(\.(SH|SZ))?', name_key, re.IGNORECASE):
                mapped_code = name_key
            if not mapped_code:
                mapped_code = resolve_name_to_code_public(name_key)
            if mapped_code:
                base = _code_base(mapped_code)
                prev = expected_by_code.get(base, Decimal('0'))
                expected_by_code[base] = (prev + amt_decimal).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            else:
                prev = expected_by_name.get(name_key, Decimal('0'))
                expected_by_name[name_key] = (prev + amt_decimal).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # 3) build result groups
    both = []
    yunfei_only = []
    positions_only = []

    for code, exp_money in expected_by_code.items():
        cur_mv, matched_code = _find_current_mv_for_code(code, current_by_code)
        if matched_code:
            name = current_by_code[matched_code].get('name')
            cur_mv = cur_mv or Decimal('0')
        else:
            name = _resolve_code_to_name(code) or code
            cur_mv = cur_mv or Decimal('0')
        if (exp_money == Decimal('0') or exp_money == 0) and (cur_mv == Decimal('0') or cur_mv == 0):
            continue
        if cur_mv and cur_mv != Decimal("0"):
            both.append({
                "stock_code": code,
                "stock_name": name,
                "expected_money": exp_money,
                "current_market_value": cur_mv
            })
        else:
            yunfei_only.append({
                "stock_code": code,
                "stock_name": name,
                "expected_money": exp_money,
                "current_market_value": Decimal("0")
            })

    # find positions only (exclude those already in expected_by_code via base matching)
    for code, info in current_by_code.items():
        accounted = False
        for candidate in _canonical_variants(code):
            if _code_base(candidate) in expected_by_code:
                accounted = True
                break
        if accounted:
            continue
        name = info.get("name") or _resolve_code_to_name(code) or code
        mv = info.get("market_value") or Decimal("0")
        if mv == Decimal('0') or mv == 0:
            continue
        positions_only.append({
            "stock_code": code,
            "stock_name": name,
            "expected_money": Decimal("0"),
            "current_market_value": mv
        })

    # name-only expected items
    for name, amt in expected_by_name.items():
        display = name
        if re.fullmatch(r'\d{6}(\.(SH|SZ))?', name.strip(), re.IGNORECASE):
            resolved = _resolve_code_to_name(name.strip())
            display = resolved or name
        if (amt == Decimal('0') or amt == 0) and (current_by_name.get(name, Decimal('0')) == Decimal('0') or current_by_name.get(name, Decimal('0')) == 0):
            continue
        yunfei_only.append({
            "stock_code": None,
            "stock_name": display,
            "expected_money": amt,
            "current_market_value": Decimal(str(current_by_name.get(name, Decimal("0"))))
        })

    # merge rows by base for nicer display
    both = _merge_rows_by_base(both)
    yunfei_only = _merge_rows_by_base(yunfei_only)
    positions_only = _merge_rows_by_base(positions_only)

    # sort by absolute diff desc
    def _abs_diff_row(r):
        try:
            return abs((r["expected_money"] - r["current_market_value"]))
        except Exception:
            return Decimal("0")

    both.sort(key=_abs_diff_row, reverse=True)
    yunfei_only.sort(key=_abs_diff_row, reverse=True)
    positions_only.sort(key=_abs_diff_row, reverse=True)

    return {
        "account_id": account_id,
        "total_asset": total_asset,
        "as_of": datetime.utcnow().isoformat(),
        "both": both,
        "yunfei_only": yunfei_only,
        "positions_only": positions_only
    }