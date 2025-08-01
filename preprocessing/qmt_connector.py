import time
import json
<<<<<<< HEAD
from preprocessing.restart_tool import restart_self
=======
import sys
import os

def restart_self():
    """
    重启本main.py进程（原地拉起同参数的自己）
    """
    print("正在重启main.py本进程...")
    python = sys.executable
    os.execl(python, python, *sys.argv)
>>>>>>> 235dce32f998ec64d0f9bb77bbfc4e0bd1799da7

def ensure_qmt_and_connect(config_path, xt_trader, logger=None, connect_max_retry=3, wait_after_qmt=15):
    """
    自动连接QMT，连接失败5次后，自动重启QMT并重启本main.py进程（即本账户进程）。
    """
    def log(msg):
        if logger:
            logger.info(msg)
        print(msg)

    # 延迟import，保证与你的 daily_restart_checker/restart_program 不冲突
    from preprocessing.daily_restart_checker import restart_program

    while True:
        retry = 0
        while retry < connect_max_retry:
            if xt_trader.connect() == 0:
                log("miniQMT连接成功！")
                return True
            else:
                retry += 1
                log(f"连接失败！正在重试...（第{retry}次）")
                time.sleep(5)
        # 五次都失败，重启QMT和自身main.py
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        log("连接失败5次，尝试关闭并重启miniQMT...")
        restart_program(config["program_name"], config["program_path"])
        log(f"已重启miniQMT，请在窗口手动登录，程序将在{wait_after_qmt}秒后自动重启本main账户进程...")
        time.sleep(wait_after_qmt)
        restart_self()  # 彻底重启main.py进程