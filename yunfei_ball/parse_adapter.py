# 兼容适配器：把 parse_b_follow_page 的新结构转换为旧逻辑期望的结构
import re
from typing import List, Dict

def _pct_to_str(pct):
    try:
        if pct is None:
            return None
        return f"{pct}"
    except Exception:
        return None

def normalize_strategies(strategies_raw: List[Dict]) -> List[Dict]:
    """
    Convert parser output into legacy format with keys:
      - name (str)
      - date (YYYY-MM-DD) (str)
      - time (full timestamp str)
      - operation_block (html or text)
      - holding_block (list of 'Name：xx%' or '空仓' strings)
    If an item already looks like legacy format, preserve it.
    """
    out = []
    for it in (strategies_raw or []):
        try:
            if isinstance(it, dict) and ('name' in it and 'date' in it and 'operation_block' in it):
                out.append(it)
                continue

            name = it.get('name') or it.get('title') or it.get('title_text') or it.get('title_str') or ''
            time_str = it.get('time') or it.get('time_str') or it.get('timestamp') or ''
            date = (time_str.split()[0] if time_str else (it.get('date') or ''))
            operation_block = it.get('operation_block') or it.get('op_text') or it.get('operation_html') or it.get('op_html') or ''
            holding_block = []
            raw_holdings = it.get('holding_block') or it.get('holding') or it.get('holdings') or it.get('holding_block_raw') or []

            if isinstance(raw_holdings, str):
                parts = [p.strip() for p in re.split(r'[\n;；,，/]', raw_holdings) if p.strip()]
                holding_block.extend(parts)
            elif isinstance(raw_holdings, list):
                for h in raw_holdings:
                    if isinstance(h, dict):
                        hname = h.get('name') or ''
                        pct = h.get('pct') or h.get('percentage')
                        if pct is None:
                            holding_block.append(hname)
                        else:
                            try:
                                holding_block.append(f"{hname}：{_pct_to_str(pct)}%")
                            except Exception:
                                holding_block.append(f"{hname}：{pct}%")
                    else:
                        holding_block.append(str(h))
            else:
                if raw_holdings:
                    holding_block.append(str(raw_holdings))

            out.append({
                'name': name,
                'date': date,
                'time': time_str,
                'operation_block': operation_block,
                'holding_block': holding_block,
                '_raw': it
            })
        except Exception:
            # in case of unexpected item structure, fallback to stringified item
            try:
                out.append({
                    'name': str(it),
                    'date': '',
                    'time': '',
                    'operation_block': '',
                    'holding_block': [],
                    '_raw': it
                })
            except Exception:
                out.append({
                    'name': '',
                    'date': '',
                    'time': '',
                    'operation_block': '',
                    'holding_block': [],
                    '_raw': None
                })
    return out