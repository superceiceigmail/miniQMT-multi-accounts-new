# utils/config_loader.py 文件内容

import os
import json
import logging

def load_json_file(path):
    """从指定路径加载并解析 JSON 文件"""
    abs_path = os.path.abspath(path)
    logging.debug(f"准备打开文件: {abs_path}")
    try:
        with open(abs_path, 'r', encoding='utf-8') as f:
            logging.debug("文件已打开，准备解析 JSON")
            data = json.load(f)
            logging.debug("JSON 解析完成")
            return data
    except Exception as e:
        # 这里使用 warning 或 error 级别，以便被主程序的日志捕获
        logging.error(f"读取JSON文件失败: {abs_path}, 错误: {e}")
        raise