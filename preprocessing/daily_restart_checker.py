import os
import subprocess
import psutil
import time
import json
from datetime import datetime
from preprocessing.restart_tool import restart_self

def restart_program(program_name, program_path):
    """
    关闭指定任务并打开指定程序。
    """
    # 1. 关闭任务
    for process in psutil.process_iter(['pid', 'name']):
        if process.info['name'] == program_name:
            print(f"正在关闭任务: {program_name} (PID: {process.info['pid']})")
            process.terminate()
            process.wait()
            print(f"任务 {program_name} 已关闭。")
    # 2. 等待一段时间确保任务完全关闭
    time.sleep(2)
    # 3. 打开程序
    if os.path.exists(program_path):
        print(f"正在打开程序: {program_path}")
        subprocess.Popen(program_path, shell=True)
        print(f"程序 {program_name} 已成功启动。")
        print(f"请输入账号信息，20秒后将继续连接。")
        time.sleep(20)
        restart_self()  # 彻底重启main.py进程
    else:
        print(f"路径 {program_path} 不存在，无法启动程序！")


def check_and_restart(config_path):
    """
    检查账户配置文件中的 last_run_date 是否为当天，如果不是则执行 restart_program 并更新 last_run_date 字段。
    """
    today_date = datetime.now().strftime('%Y%m%d')
    # 加载账户配置
    if not os.path.exists(config_path):
        print(f"账户配置文件 {config_path} 不存在，无法检查和重启！")
        return
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    # 检查必须字段
    for key in ("program_name", "program_path"):
        if key not in config:
            print(f"账户配置文件 {config_path} 缺少字段 {key}，请补全！")
            return
    file_date = config.get("last_run_date", "")
    if file_date != today_date:
        print(f"执行重启操作:最后启动日为 {file_date}，非当天日期 {today_date}，")
        # 更新json中的last_run_date
        config["last_run_date"] = today_date
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)  # type: ignore
        restart_program(config["program_name"], config["program_path"])
    else:
        print(f"跳过重启操作：最后启动日为 {file_date}，与当天日期 {today_date} 相同。")


# 主程序入口（测试用）
if __name__ == "__main__":
    # 测试路径
    check_and_restart("../core_parameters/account/8886006288.json")