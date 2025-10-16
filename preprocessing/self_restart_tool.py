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
    只关闭指定路径和名称的QMT进程，并重启该程序。
    多账户场景下只影响当前账户，不影响其他账户。
    """
    # 1. 关闭该账户相关的QMT进程
    closed = False
    for process in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
        # 检查进程名和exe路径是否都匹配（防止影响其他账户QMT）
        exe_match = process.info.get('exe') and os.path.normcase(process.info['exe']) == os.path.normcase(program_path)
        name_match = process.info.get('name') and process.info['name'].lower() == program_name.lower()
        if exe_match and name_match:
            logging.info(f"正在关闭任务: {program_name} (PID: {process.info['pid']}) 路径: {process.info['exe']}")
            try:
                process.terminate()
                process.wait(timeout=5)
                logging.info(f"任务 {program_name} 已关闭。")
                closed = True
            except Exception as e:
                logging.warning(f"关闭进程 {process.info['pid']} 失败: {e}")
    if not closed:
        logging.info(f"没有找到路径和名称都匹配的QMT进程，无需关闭。")
    # 2. 等待一段时间确保任务完全关闭
    time.sleep(2)
    # 3. 打开程序
    if os.path.exists(program_path):
        logging.info(f"正在打开程序: {program_path}")
        subprocess.Popen(program_path, shell=True)
        logging.info(f"程序 {program_name} 已成功启动。")
        logging.info(f"请输入账号信息，30秒后将继续连接。")
        time.sleep(30)
    else:
        logging.warning(f"路径 {program_path} 不存在，无法启动程序！")