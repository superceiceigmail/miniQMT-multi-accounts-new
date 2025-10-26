import os
import subprocess
import psutil
import time
import json
import logging
from datetime import datetime

from preprocessing.self_restart_tool import qmt_restart_program

def check_and_restart(config_path):
    """
    检查账户配置文件中的 last_run_date 是否为当天，如果不是则执行 restart_program 并更新 last_run_date 字段。
    现在会读取 config 中的 "password" 字段（如果存在），并把它传给 qmt_restart_program 以便自动登录使用。
    """
    today_date = datetime.now().strftime('%Y%m%d')
    # 加载账户配置
    if not os.path.exists(config_path):
        logging.warning(f"账户配置文件 {config_path} 不存在，无法检查和重启！")
        return
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    # 检查必须字段
    for key in ("program_name", "program_path"):
        if key not in config:
            logging.warning(f"账户配置文件 {config_path} 缺少字段 {key}，请补全！")
            return
    file_date = config.get("last_run_date", "")
    if file_date != today_date:
        logging.info(f"执行重启操作: 最后启动日为 {file_date}，非当天日期 {today_date}，")

        # 更新json中的last_run_date
        config["last_run_date"] = today_date
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)  # type: ignore

        # 读取密码字段（如果存在）
        account_password = config.get("password")
        # 为了安全，不在日志打印明文密码。下面构造掩码便于你确认是否读取到了密码以及长度信息。
        def _mask(pwd):
            try:
                if pwd is None:
                    return "<none>"
                s = str(pwd)
                if s == "":
                    return "<empty>"
                n = len(s)
                if n <= 2:
                    return "*" * n
                return s[0] + ("*" * (n - 2)) + s[-1]
            except Exception:
                return "<mask_err>"

        masked = _mask(account_password)
        if account_password:
            logging.info(f"从账户配置中读取到 password 字段（掩码）：{masked}，将用于自动登录调用。")
        else:
            logging.info("账户配置中未找到 password 字段（或为空），qmt_auto_login 将使用默认回退密码（若有）。")

        qmt_restart_program(config["program_name"], config["program_path"], account_password=account_password)

    else:
        logging.info(f"跳过重启操作：最后启动日为 {file_date}，与当天日期 {today_date} 完全相同。")


# 主程序入口（测试用）
if __name__ == "__main__":
    # 测试路径
    check_and_restart("../core_parameters/account/8886006288.json")