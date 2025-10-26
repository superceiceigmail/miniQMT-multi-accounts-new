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

def qmt_restart_program(program_name, program_path, account_password: str = None):
    """
    只关闭指定路径和名称的QMT进程，并重启该程序。
    多账户场景下只影响当前账户，不影响其他账户。

    account_password: 可选，若提供则传给 preprocessing.qmt_auto_login.run_auto_fill_and_login
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
        logging.info(f"请输入账号信息，13秒后将继续连接。")
        time.sleep(13)

        # === 自动登录尝试（安全、可回退） ===
        # 在程序启动并等待一定时间后，尝试调用 preprocessing.qmt_auto_login.run_auto_fill_and_login(silent=True, password=...)
        # 如果 qmt_auto_login 不可用或抛异常，则记录日志并继续，不会中断主流程。
        try:
            # lazy import to avoid heavy imports if not available
            from preprocessing.qmt_auto_login import run_auto_fill_and_login
            logging.info("尝试使用 preprocessing.qmt_auto_login 执行自动登录...")
            auto_success = False
            max_attempts = 4
            for attempt in range(1, max_attempts + 1):
                try:
                    logging.info(f"自动登录尝试 {attempt}/{max_attempts} ...")
                    # silent=True -> no UI prompts; returns True on success
                    ok = run_auto_fill_and_login(silent=True, password=account_password)
                    if ok:
                        logging.info("自动登录成功。")
                        auto_success = True
                        break
                    else:
                        logging.warning("自动登录尝试失败（返回 False）。")
                except Exception:
                    logging.exception("自动登录尝试发生异常")
                # 等待再试（让 QMT 稳定或等 OCR 响应准备好）
                time.sleep(1.5)
            if not auto_success:
                logging.error("多次尝试后自动登录失败，请检查 Desktop/qmt_ocr_debug 下的截图与 resp_*.json 以排查问题。")
        except Exception:
            logging.exception("无法导入或调用 preprocessing.qmt_auto_login，跳过自动登录尝试。")
        # === 自动登录尝试结束 ===

    else:
        logging.warning(f"路径 {program_path} 不存在，无法启动程序！")


if __name__ == "__main__":
    # 方便手动测试（示例）
    # 请确保在测试时提供正确的 program_name/program_path 或在 main 调用时使用 check_and_restart
    # 例如： python self_restart_tool.py  用于手动调用 qmt_restart_program 可在上层脚本中集成
    pass