import time
import json
import logging
from preprocessing.self_restart_tool import qmt_restart_program, restart_self

def ensure_qmt_and_connect(config_path, xt_trader, logger=None, connect_max_retry=3, wait_after_qmt=5):
    """
    自动连接QMT，连接失败3次后，重启QMT等待30秒再试3次，再失败则重启QMT并重启本main.py进程。
    此处会把 account JSON 中的 "password" 传给 qmt_restart_program，确保自动登录使用对应账户密码。
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
                time.sleep(3)
        return False

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # 第一次尝试连接
    if try_connect(connect_max_retry):
        return True

    # 失败重启QMT
    log("连接失败3次，重启miniQMT...")

    # 读取 password 并以掩码形式记录（不在日志中打印明文）
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

    account_password = config.get("password")
    masked = _mask(account_password)
    if account_password:
        log(f"从 account 配置中读取到 password（掩码）: {masked}，将传给 qmt_restart_program 用于自动登录。")
    else:
        log(f"account 配置中未设置 password（掩码={masked}），qmt_restart_program 将使用回退逻辑。")

    # 传入 account_password 参数
    qmt_restart_program(config["program_name"], config["program_path"], account_password=account_password)

    log(f"miniQMT已重启，等待{wait_after_qmt}秒后再尝试连接，请在窗口手动登录...")
    time.sleep(wait_after_qmt)
    restart_self()
    # 再次尝试连接
    if try_connect(connect_max_retry):
        return True
    """
    # 仍然失败，重启main.py
    log("连接失败3次，自动重启本main账户进程...")
    restart_self()
    """