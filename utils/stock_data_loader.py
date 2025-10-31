# utils/stock_data_loader.py
"""
加载股票代码与名称映射、并生成反向映射(reverse mapping)的工具。
统一调用 utils.code_normalizer.normalize_code 来保证 code 带后缀（或按规则推断后缀）。
返回值和原接口兼容： (stock_code_dict, get_stock_code_func, reverse_mapping)
"""
import os
from typing import Tuple, Dict, Callable, Optional
from utils.config_loader import load_json_file
from utils.stock_code_mapper import generate_reverse_mapping, load_stock_codes
from utils.code_normalizer import normalize_code

# 定义文件路径常量（与仓库约定）
STOCK_CODE_FILE_PATH = r"core_parameters/stocks/core_stock_code.json"  # may be name->code or code->name
FULL_CODE_FILE_PATH = r"utils/stocks_code_search_tool/stocks_data/name_vs_code.json"

def _normalize_dict_codes(d: Dict[str, str]) -> Dict[str, str]:
    """
    Normalize mapping values to normalized code strings (带后缀)， keep keys as names.
    """
    out = {}
    for k, v in (d or {}).items():
        if not v:
            continue
        try:
            nc = normalize_code(str(v).strip())
            out[str(k).strip()] = nc
        except Exception:
            out[str(k).strip()] = str(v).strip()
    return out

def load_stock_code_maps() -> Tuple[Dict[str, str], Callable[[str], Optional[str]], Dict[str, str]]:
    """
    Return:
      - stock_code_dict: mapping name -> code (normalized)
      - get_stock_code(name): function to lookup code by name
      - reverse_mapping: mapping base_code (no suffix) -> name (for quick lookup)
    """
    # 1) load core stock code file
    try:
        stock_code_data = load_json_file(STOCK_CODE_FILE_PATH) or {}
    except Exception:
        stock_code_data = {}

    # normalize shape: if file maps code->name, invert to name->code
    stock_code_dict = {}
    sample_key = next(iter(stock_code_data.keys()), None) if isinstance(stock_code_data, dict) else None
    try:
        if sample_key and isinstance(sample_key, str) and sample_key.strip().isdigit() and len(sample_key.strip()) == 6:
            # assume code->name mapping: invert
            for code, name in stock_code_data.items():
                if not name:
                    continue
                stock_code_dict[str(name).strip()] = normalize_code(str(code).strip())
        else:
            # assume name->code mapping already
            for name, code in stock_code_data.items():
                if not name or code is None:
                    continue
                stock_code_dict[str(name).strip()] = normalize_code(str(code).strip())
    except Exception:
        # fallback: try load via stock_code_mapper (file-based)
        try:
            stock_code_dict = load_stock_codes(STOCK_CODE_FILE_PATH)
        except Exception:
            stock_code_dict = {}

    # 2) load full_name->code mapping if present (name_vs_code)
    try:
        full_map = load_json_file(FULL_CODE_FILE_PATH) or {}
        # normalize values
        for k, v in full_map.items():
            if not v:
                continue
            # if v is code string, normalize and set if name not in core
            if isinstance(v, str):
                nm = str(k).strip()
                if nm not in stock_code_dict:
                    stock_code_dict[nm] = normalize_code(str(v).strip())
    except Exception:
        pass

    # reverse mapping: basecode -> name (prefer core mapping)
    reverse_mapping = generate_reverse_mapping(stock_code_dict)
    # ensure reverse mapping keys are base (no suffix)
    reverse_mapping_norm = {}
    for base, name in reverse_mapping.items():
        try:
            base_str = str(base).split('.')[0]
            reverse_mapping_norm[base_str] = name
        except Exception:
            reverse_mapping_norm[str(base)] = name

    # get_stock_code function
    def get_stock_code(name: str) -> Optional[str]:
        if not name:
            return None
        name = str(name).strip()
        if name in stock_code_dict:
            return stock_code_dict[name]
        # try reverse lookup by name normalization (some files store code as key)
        # fallback: try direct numeric name treated as code
        if name.isdigit() and len(name) == 6:
            return normalize_code(name)
        return None

    return stock_code_dict, get_stock_code, reverse_mapping_norm