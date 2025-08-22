import sys
import os
import psutil
import time
import subprocess
import logging

def restart_self():
    """
    重启本main.py进程（原地拉起同参数的自己）
    """
    logging.info("正在重启main.py本进程...")
    python = sys.executable
    os.execv(python, [python] + sys.argv)

def qmt_restart_program(program_name, program_path):
    """
    关闭指定任务并打开指定程序。
    """
    # 1. 关闭任务
    for process in psutil.process_iter(['pid', 'name']):
        if process.info['name'] == program_name:
            logging.info(f"正在关闭任务: {program_name} (PID: {process.info['pid']})")
            process.terminate()
            process.wait()
            logging.info(f"任务 {program_name} 已关闭。")
    # 2. 等待一段时间确保任务完全关闭
    time.sleep(2)
    # 3. 打开程序
    if os.path.exists(program_path):
        logging.info(f"正在打开程序: {program_path}")
        subprocess.Popen(program_path, shell=True)
        logging.info(f"程序 {program_name} 已成功启动。")
        logging.info(f"请输入账号信息，30秒后将继续连接。")

    else:
        logging.warning(f"路径 {program_path} 不存在，无法启动程序！")