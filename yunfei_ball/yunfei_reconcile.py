# yunfei_ball/yunfei_reconcile.py
# 提供 reconcile_account 接口：为 GUI 对账使用，调用 fetcher 获取策略页（缓存可选），并对比账户持仓。
# 返回结构化报告，便于 GUI 展示。

import os
import json
from typing import Optional, Dict, Any
from .yunfei_fetcher import fetch_b_follow, parse_b_follow_page
from .yunfei_login import login, is_logged_in, BASE_URL
from collections import defaultdict
from datetime import datetime

# 重用原来的 name->code 映射加载逻辑（从 code_index.json）
CODE_INDEX_PATH = os.path.join(os.path.dirname(__file__), "code_index.json")

# 从 utils 导入持仓/账户转换函数（与原文件兼容）
try:
    from utils.asset_helpers import positions_to_dict, account_asset_to_tuple
except Exception:
    # 若不存在则用简单占位实现（以保证 module import 不会失败）
    def positions_to_dict(x):
        return x
    def account_asset_to_tuple(x):
        return x

def load_name_to_code_map(json_path=CODE_INDEX_PATH):
    if not os.path.exists(json_path):
        return {}
    with open(json_path, 'r', encoding='utf-8') as f:
        code_map = json.load(f)
    name_to_code = {}
    for code, namelist in code_map.items():
        if len(code) == 6:
            code_with_sh = code + ".SH"
        else:
            code_with_sh = code
        for name in namelist:
            if name not in name_to_code:
                name_to_code[name] = code_with_sh
    return name_to_code

def _parse_holding_line(line: str):
    """
    解析形如 "股票名：20%" 或 "空仓" 等
    返回 (name, percent_or_None)
    """
    if not line:
        return None, None
    if '空仓' in line:
        return '空仓', None
    m = None
    m = __import__('re').match(r'([^\s：:]+)[：:]\s*([\d\.]+)%', line)
    if m:
        return m.group(1), float(m.group(2))
    return line.strip(), None

def _aggregate_by_batch(strategies_list):
    """
    将 fetcher 返回的 strategies 列表按配置的交易批次聚合。
    原始 fetcher/parse 并不返回交易批次号，这里仅按策略名称/时间分组并返回列表。
    """
    batches = defaultdict(list)
    batches[1] = strategies_list
    return batches

def reconcile_account(account: Any,
                      account_snapshot: Optional[Any] = None,
                      xt_trader: Optional[Any] = None,
                      username: Optional[str] = None,
                      force_fetch: bool = False,
                      cache_ttl: int = 600) -> Dict[str, Any]:
    """
    对账主入口（供 GUI 调用）
    返回：
    {
      "fetched_at": ...,
      "batches": { batch_no: [ ... ] },
      "account_holdings": {...},
      "warnings": [...]
    }
    """
    warnings = []

    # 先确认登录状态（轻量校验），如果未登录则直接返回明确提示
    session = None
    try:
        session = login(username=username)
    except Exception:
        session = None
    if not session:
        return {
            'fetched_at': None,
            'batches': {},
            'account_holdings': {},
            'warnings': ['not_logged_in']
        }
    try:
        resp = session.get(BASE_URL + '/F2/b_follow.aspx', timeout=10, proxies={})
        resp.encoding = resp.apparent_encoding
        if not is_logged_in(resp.text):
            return {
                'fetched_at': None,
                'batches': {},
                'account_holdings': {},
                'warnings': ['not_logged_in']
            }
    except Exception:
        return {
            'fetched_at': None,
            'batches': {},
            'account_holdings': {},
            'warnings': ['not_logged_in']
        }

    # 1) 获取策略页面（使用 session 以便复用登录）
    try:
        fetch_result = fetch_b_follow(session=session, username=username, force=force_fetch, ttl=cache_ttl)
    except Exception as e:
        return {
            'fetched_at': None,
            'batches': {},
            'account_holdings': {},
            'warnings': [f'fetch_error:{e}']
        }

    # 若 fetcher 返回 warning（例如 抓到登录页并使用陈旧缓存 或 rate_limited），将 warning 直接返回
    if fetch_result.get('warning'):
        return {
            'fetched_at': fetch_result.get('fetched_at_iso'),
            'batches': {},
            'account_holdings': {},
            'warnings': [fetch_result.get('warning')]
        }

    strategies = fetch_result.get('strategies', [])
    fetched_at = fetch_result.get('fetched_at_iso', None)

    # 2) 构造 name->code 映射
    name_to_code = load_name_to_code_map()

    # 3) 获取账户持仓快照（尽量标准化成 code -> { qty, mkt_value, percent } 形式）
    account_holdings = {}
    total_asset = None
    if account_snapshot:
        try:
            account_tuple = account_asset_to_tuple(account_snapshot)
            total_asset = getattr(account_tuple, 'm_dTotal', None) or getattr(account_tuple, 'm_dAssets', None)
        except Exception:
            account_tuple = account_snapshot
    else:
        if xt_trader and account:
            try:
                account_info = xt_trader.query_stock_asset(account)
                positions = xt_trader.query_stock_positions(account)
                total_asset = getattr(account_info, 'm_dTotal', None) or getattr(account_info, 'm_dAssets', None)
                account_holdings = positions_to_dict(positions)
            except Exception as e:
                warnings.append(f"query_account_failed:{e}")
                account_holdings = {}
        else:
            account_holdings = {}

    if not account_holdings and account_snapshot:
        try:
            account_holdings = positions_to_dict(account_snapshot)
        except Exception:
            account_holdings = {}

    normalized_holdings = {}
    if isinstance(account_holdings, dict):
        for code, info in account_holdings.items():
            if isinstance(info, dict):
                qty = info.get('qty') or info.get('m_iHoldQty') or info.get('m_dQty')
                mkt = info.get('m_dFVal') or info.get('m_dMarketValue') or info.get('m_fVal') or info.get('m_dVal') or info.get('mkt_value')
                normalized_holdings[code] = {
                    'qty': qty,
                    'mkt_value': mkt
                }
    if total_asset:
        for c in normalized_holdings:
            m = normalized_holdings[c].get('mkt_value')
            if m:
                try:
                    normalized_holdings[c]['percent'] = float(m) * 100.0 / float(total_asset)
                except Exception:
                    pass

    # 4) 解析策略持仓并与账户对比
    batches = _aggregate_by_batch(strategies)
    report_batches = {}

    for batch_no, strat_list in batches.items():
        report_list = []
        for s in strat_list:
            holding_parsed = []
            for line in s.get('holding_block', []):
                name, pct = _parse_holding_line(line)
                code = None
                if name and name != '空仓':
                    code = name_to_code.get(name)
                holding_parsed.append({
                    'raw': line,
                    'name': name,
                    'code': code,
                    'percent_expect': pct
                })

            comparisons = []
            for h in holding_parsed:
                expected_pct = h.get('percent_expect')
                code = h.get('code')
                acct_info = None
                acct_pct = None
                acct_qty = None
                acct_mkt = None
                if code:
                    acct_info = normalized_holdings.get(code) or {}
                    acct_qty = acct_info.get('qty')
                    acct_mkt = acct_info.get('mkt_value')
                    acct_pct = acct_info.get('percent')
                comparisons.append({
                    'name': h.get('name'),
                    'code': code,
                    'expected_percent': expected_pct,
                    'account_percent': acct_pct,
                    'account_qty': acct_qty,
                    'account_mkt_value': acct_mkt
                })

            report_list.append({
                'strategy_name': s.get('name'),
                'strategy_date': s.get('date'),
                'strategy_time': s.get('time'),
                'operation_block': s.get('operation_block'),
                'holding_parsed': holding_parsed,
                'comparisons': comparisons
            })
        report_batches[batch_no] = report_list

    result = {
        'fetched_at': fetched_at,
        'batches': report_batches,
        'account_holdings': normalized_holdings,
        'warnings': warnings
    }
    return result