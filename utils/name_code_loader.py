"""
utils/name_code_loader.py
统一加载 code_index.json 并生成 name->code 映射，使用 utils.code_normalizer.normalize_code 进行后缀推断。
提供缓存、显式后缀优先、以及查询接口。
"""
import os
import json
import re
from typing import Dict, Optional
from functools import lru_cache

from .code_normalizer import normalize_code

@lru_cache(maxsize=1)
def load_code_index(json_path: Optional[str]) -> Dict[str, list]:
    if not json_path:
        return {}
    if not os.path.exists(json_path):
        return {}
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f) or {}
        return data
    except Exception:
        return {}

def build_name_to_code_map(json_path: Optional[str]) -> Dict[str, str]:
    """
    从 code_index.json 构造 name->code 字典。
    规则：
      - 如果 code_key 已包含后缀（xxx.SH/xxx.SZ），保留其规范化形式。
      - 若 code_key 是 6 位纯数字，则调用 normalize_code 推断后缀。
      - name 映射只保留第一次出现（优先级：文件顺序决定）。
    返回 name_to_code：name -> code_with_suffix
    """
    code_map = load_code_index(json_path)
    if not code_map:
        return {}
    name_to_code = {}
    for code_key, namelist in code_map.items():
        key = str(code_key).strip()
        if re.fullmatch(r'\d{6}\.(SH|SZ)', key, re.IGNORECASE):
            code_with_suffix = key.upper()
        elif re.fullmatch(r'\d{6}', key):
            code_with_suffix = normalize_code(key)
        else:
            # 非标准，保留原样（上层可能需要兼容）
            code_with_suffix = key
        for name in (namelist or []):
            if name and name not in name_to_code:
                name_to_code[name] = code_with_suffix
    return name_to_code

def resolve_name_to_code(name: str, json_path: Optional[str]) -> Optional[str]:
    if not name:
        return None
    mapping = build_name_to_code_map(json_path)
    return mapping.get(name)