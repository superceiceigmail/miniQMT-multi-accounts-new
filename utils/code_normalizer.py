"""
utils/code_normalizer.py
统一处理股票代码后缀：normalize_code / ensure_suffix / canonical_variants / match helper.
"""
import re
from typing import List, Optional

def normalize_code(code: str) -> str:
    """
    将输入规范化为大写并确保带后缀（若输入是6位数字则按规则补后缀）。
    规则（保持与现有实现兼容）:
      - 以 6/5/8/9 开头 -> .SH
      - 其它以数字开头的六位 -> .SZ
    已带后缀的保持不变（且规范为大写）。
    """
    if not code:
        return ""
    s = str(code).strip().upper()
    # 已带后缀
    m = re.fullmatch(r'(\d{6})\.(SH|SZ)', s, re.IGNORECASE)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    # 6位纯数字
    m2 = re.fullmatch(r'(\d{6})', s)
    if m2:
        base = m2.group(1)
        if base.startswith(('6', '5', '8', '9')):
            return f"{base}.SH"
        else:
            return f"{base}.SZ"
    return s

def ensure_suffix(code: str, prefer: Optional[str] = None) -> str:
    """
    类似 normalize_code；当传入 prefer ('SH' 或 'SZ') 时在无后缀的情形下按偏好补后缀。
    """
    if not code:
        return ""
    s = str(code).strip().upper()
    if '.' in s:
        return s
    base = s.split('.')[0]
    if prefer and prefer.upper() in ('SH', 'SZ') and re.fullmatch(r'\d{6}', base):
        return f"{base}.{prefer.upper()}"
    return normalize_code(base)

def _code_base(code: str) -> str:
    if not code:
        return ""
    m = re.match(r'(\d{6})', str(code).strip())
    return m.group(1) if m else str(code).strip()

def canonical_variants(code: str) -> List[str]:
    """
    返回用于匹配的候选变体列表，优先显式后缀，再常见后缀，再无后缀。
    """
    if not code:
        return []
    s = str(code).strip()
    base = _code_base(s)
    if '.' in s:
        parts = s.split('.', 1)
        suf = parts[1].upper() if len(parts) > 1 else ''
        return [f"{base}.{suf}", f"{base}.SH", f"{base}.SZ", base]
    if base and base[0] in ("5", "6", "8", "9"):
        return [f"{base}.SH", f"{base}.SZ", base]
    else:
        return [f"{base}.SZ", f"{base}.SH", base]

def match_available_code_in_dict(code: str, available_dict: dict) -> Optional[str]:
    """
    在 available_dict 的 keys 中尝试匹配 code 的变体，返回第一个命中的 key（或 None）。
    """
    for v in canonical_variants(code):
        if v in available_dict:
            return v
    return None