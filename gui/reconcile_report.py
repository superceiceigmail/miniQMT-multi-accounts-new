"""
Generate a reconciliation report that splits results into three groups:
 - both: items present in both expected (yunfei + draft) and current positions
 - yunfei_only: items only in expected (current market value treated as 0)
 - positions_only: items only in positions (expected treated as 0)

This version merges tradeplan/trade_plan_draft.json suggested holdings into expected amounts,
normalizes codes (remove .SH/.SZ) before summing, then compares against current positions.

It also supports suggested_pct entries from draft: suggested_amount = suggested_pct/100 * total_asset * proportion
where proportion is read from core_parameters/account/mama.json ("proportion" key). Fallbacks used when missing.
"""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import os
import json
import re
import collections

# NOTE: lazy import of reconcile_ui helpers within function to avoid circular import
from yunfei_ball.yunfei_connect_follow import find_strategy_by_id_and_bracket

# paths
TRADE_PLAN_DRAFT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tradeplan", "trade_plan_draft.json"))
CORE_STOCK_CODE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core_parameters", "stocks", "core_stock_code.json"))
MAMA_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core_parameters", "account", "mama.json"))


# ---------- code normalization helpers ----------
def _code_base(code: str) -> str:
    if not code:
        return ''
    s = str(code).strip()
    m = re.match(r'(\d{6})', s)
    return m.group(1) if m else s


def _canonical_variants(code: str):
    if not code:
        return []
    base = _code_base(code)
    s = str(code).strip()
    if '.' in s:
        parts = s.split('.', 1)
        suf = parts[1].upper() if len(parts) > 1 else ''
        return [f"{base}.{suf}", f"{base}.SH", f"{base}.SZ", base]
    if base and base[0] in ("5", "6", "9"):
        return [f"{base}.SH", f"{base}.SZ", base]
    else:
        return [f"{base}.SZ", f"{base}.SH", base]


def _find_current_mv_for_code(code_key: str, current_by_code: dict):
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
# -------------------------------------------------


def _load_code_index():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    p = os.path.join(repo_root, "yunfei_ball", "code_index.json")
    try:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}


def _resolve_code_to_name(code):
    if not code:
        return None
    base = str(code).split('.')[0]
    idx = _load_code_index()
    if base in idx and isinstance(idx[base], list) and idx[base]:
        return idx[base][0]
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    name_vs_code_path = os.path.join(repo_root, "utils", "stocks_code_search_tool", "stocks_data", "name_vs_code.json")
    try:
        if os.path.exists(name_vs_code_path):
            nm = json.load(open(name_vs_code_path, 'r', encoding='utf-8'))
            if code in nm:
                return nm.get(code)
            for s in (".SH", ".SZ"):
                k = base + s
                if k in nm:
                    return nm.get(k)
    except Exception:
        pass
    return None


# load core parameters map
_CORE_STOCK_CODE_CACHE = None


def _load_core_stock_code_map():
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
            sample_key = next(iter(data.keys()), None)
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
    except Exception:
        _CORE_STOCK_CODE_CACHE = {}
    return _CORE_STOCK_CODE_CACHE


# load mama proportion
_MAMA_CACHE = None


def _load_mama_proportion():
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


def _load_trade_plan_draft():
    try:
        if os.path.exists(TRADE_PLAN_DRAFT_PATH):
            d = json.load(open(TRADE_PLAN_DRAFT_PATH, 'r', encoding='utf-8'))
            return d or {}
    except Exception:
        pass
    return {}


def _extract_entries_from_draft(draft):
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


def _merge_rows_by_base(rows):
    grouped = collections.OrderedDict()
    for r in rows:
        code = r.get('stock_code')
        if not code:
            key = f"name::{r.get('stock_name') or ''}"
        else:
            base = re.match(r'(\d{6})', str(code).strip())
            key = base.group(1) if base else str(code).strip()
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


def generate_reconcile_report(account_id: str, require_today: bool = False):
    from gui import reconcile_ui as ru

    allocation_list = ru.load_allocation_list()
    strategies = ru.load_parsed_strategies()
    asset = ru.load_account_asset_latest(account_id)
    if not asset:
        raise RuntimeError(f"找不到账户資產文件 for {account_id}")
    total_asset = Decimal(str(asset.get("total_asset") or asset.get("m_dAsset") or 0))

    positions = ru.load_account_positions_latest(account_id)
    current_by_code = {}
    current_by_name = {}
    for p in (positions or []):
        raw_code = (p.get("stock_code") or p.get("code") or "").strip()
        name = p.get("stock_name") or p.get("stock") or ''
        try:
            mv = Decimal(str(p.get("market_value") or 0))
        except Exception:
            mv = Decimal("0")
        if raw_code:
            current_by_code[raw_code] = {"name": name, "market_value": mv, "raw": p}
            base = _code_base(raw_code)
            if base not in current_by_code:
                current_by_code[base] = {"name": name, "market_value": mv, "raw": p}
        if name:
            current_by_name[name] = current_by_name.get(name, Decimal("0")) + mv

    expected_by_code = {}
    expected_by_name = {}
    if require_today:
        today_str = datetime.now().strftime('%Y-%m-%d')
        today_date = datetime.strptime(today_str, '%Y-%m-%d').date()
    else:
        today_date = None

    for cfg in allocation_list:
        try:
            config_pct = float(cfg.get("配置仓位", 0)) / 100.0
        except Exception:
            config_pct = 0.0

        matched = None
        try:
            matched = find_strategy_by_id_and_bracket(cfg, strategies)
        except Exception:
            matched = None
        if not matched:
            json_name = (cfg.get("策略名称") or "").strip()
            for s in strategies:
                web_full_name = (s.get("name") or s.get("title") or "").strip()
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

        holdings = ru._extract_holdings_from_strategy_item(matched)
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

    # merge draft amounts (support suggested_pct -> compute with total_asset * proportion)
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
                mapped_code = ru.resolve_name_to_code(name_key)
            if mapped_code:
                base = _code_base(mapped_code)
                prev = expected_by_code.get(base, Decimal('0'))
                expected_by_code[base] = (prev + amt_decimal).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            else:
                prev = expected_by_name.get(name_key, Decimal('0'))
                expected_by_name[name_key] = (prev + amt_decimal).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

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

    both = _merge_rows_by_base(both)
    yunfei_only = _merge_rows_by_base(yunfei_only)
    positions_only = _merge_rows_by_base(positions_only)

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