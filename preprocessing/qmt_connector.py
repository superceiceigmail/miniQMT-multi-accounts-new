import time
import json
import logging
from preprocessing.self_restart_tool import qmt_restart_program, restart_self

def ensure_qmt_and_connect(config_path, xt_trader, logger=None, connect_max_retry=3, wait_after_qmt=30):
    """
    自动连接QMT，连接失败3次后，重启QMT等待30秒再试3次，再失败则重启QMT并重启本main.py进程。
    """
    def log(msg):
        if logger:
            logger.info(msg)
        logging.info(msg)

    def try_connect(max_retry):
        retry = 0
        while retry < max_retry:
            if xt_trader.connect() == 0:
                log("miniQMT连接成功！")
                return True
            else:
                retry += 1
                log(f"连接失败！正在重试...（第{retry}次）")
                time.sleep(5)
        return False

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # 第一次尝试连接
    if try_connect(connect_max_retry):
        return True

    # 失败重启QMT
    log("连接失败3次，重启miniQMT...")
    qmt_restart_program(config["program_name"], config["program_path"])
    log(f"miniQMT已重启，等待{wait_after_qmt}秒后再尝试连接，请在窗口手动登录...")
    time.sleep(wait_after_qmt)

    # 再次尝试连接
    if try_connect(connect_max_retry):
        return True

    # 仍然失败，重启main.py
    log("再次连接失败，自动重启本main账户进程...")
    restart_self()