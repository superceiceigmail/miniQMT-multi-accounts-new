#!/usr/bin/env python3
# main.py — 程序入口（精简版）
import os
import sys
import time
import logging
import traceback
import argparse
import atexit
import re
import ctypes
from datetime import datetime

from utils.log_utils import ensure_utf8_stdio, setup_logging
from utils.config_loader import load_json_file
from utils.stock_data_loader import load_stock_code_maps
from utils.asset_helpers import positions_to_dict
from preprocessing.qmt_connector import ensure_qmt_and_connect
from preprocessing.qmt_daily_restart_checker import check_and_restart
from processor.trade_plan_generation import print_trade_plan as generate_trade_plan_final_func
from utils.git_push_tool import push_project_to_github
from xtquant.xttype import StockAccount
from xtquant import xtdata

# 本地拆分模块
import helpers
import tasks
import psutil

# 常量（保留你的原配置或改为外部配置）
ACCOUNT_CONFIG_MAP = {
    "shu": "core_parameters/account/8886006288.json",
    "mama": "core_parameters/account/mama.json",
}

YUNFEI_SCHEDULE_TIMES = helpers.YUNFEI_SCHEDULE_TIMES
AUTO_BUY_511880_TIME = helpers.AUTO_BUY_511880_TIME
AUTO_SELL_511880_TIME = helpers.AUTO_SELL_511880_TIME

# PID file directory for ui-launched processes
_PID_DIR = os.path.join("runtime", "pids")


def _write_ui_pid_file(ui_id: str):
    """
    Write a small pid file for the given ui_id. Returns path or None.
    """
    try:
        if not ui_id:
            return None
        os.makedirs(_PID_DIR, exist_ok=True)
        fname = os.path.join(_PID_DIR, f"{ui_id}.pid")
        with open(fname, "w", encoding="utf-8") as f:
            f.write(f"pid: {os.getpid()}\n")
            f.write(f"cmd: {' '.join(sys.argv)}\n")
            f.write(f"started_at: {datetime.now().isoformat()}\n")
        return fname
    except Exception:
        return None


def _remove_ui_pid_file(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


# ----------------- Windows 窗口最小化（更稳健实现） -----------------
# 思路：优先按可执行名（进程）查找其顶层窗口并最小化；若找不到，再回退到按窗口标题正则匹配。
# 优点：如果 QMT 以 XtMiniQmt.exe 运行，按进程查找会更可靠；同时增加重试等待时间以处理窗口延迟出现或标题更新。
def _enum_windows(callback):
    """
    Enumerate top-level windows via ctypes, calling callback(hwnd) for each.
    """
    user32 = ctypes.windll.user32
    EnumWindows = user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @EnumWindowsProc
    def _proc(hwnd, lParam):
        callback(hwnd)
        return True

    EnumWindows(_proc, 0)


def _get_window_text(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def _is_window_visible(hwnd):
    return bool(ctypes.windll.user32.IsWindowVisible(hwnd))


def _get_window_pid(hwnd):
    """
    Return process id owning this window, or None on failure.
    """
    try:
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value
    except Exception:
        return None


def _collect_hwnds_for_pid(pid):
    """
    Return a list of top-level hwnds that belong to process pid.
    """
    hwnds = []

    def _check(hwnd):
        try:
            if not _is_window_visible(hwnd):
                return
            owner_pid = _get_window_pid(hwnd)
            if owner_pid == pid:
                # skip windows with empty title
                title = _get_window_text(hwnd)
                if title and len(title.strip()) > 0:
                    hwnds.append((hwnd, title))
        except Exception:
            pass

    try:
        _enum_windows(_check)
    except Exception:
        pass
    return hwnds


def _minimize_hwnd(hwnd):
    try:
        SW_MINIMIZE = 6
        ctypes.windll.user32.ShowWindow(hwnd, SW_MINIMIZE)
        return True
    except Exception:
        return False


def _find_processes_by_exe_names(candidate_names):
    """
    Return list of psutil.Process for processes whose name() matches any in candidate_names (case-insensitive).
    candidate_names: list of strings like ['XtMiniQmt.exe', 'XtMiniQmt']
    """
    procs = []
    lower_names = [n.lower() for n in candidate_names]
    for p in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
        try:
            nm = (p.info.get('name') or "").lower()
            exe = (p.info.get('exe') or "")
            if nm in lower_names:
                procs.append(p)
                continue
            # also check exe basename
            be = os.path.basename(exe).lower() if exe else ""
            if be in lower_names:
                procs.append(p)
                continue
            # sometimes the cmdline contains exe path
            cmd0 = (p.info.get('cmdline') or [])
            if cmd0 and len(cmd0) > 0 and os.path.basename(cmd0[0]).lower() in lower_names:
                procs.append(p)
        except Exception:
            continue
    return procs


def minimize_qmt_window_improved(timeout=10):
    """
    Try multiple strategies to find and minimize QMT window:
    1) Find process by common exe names (XtMiniQmt.exe / XtMiniQmt), enumerate its windows and minimize them.
    2) Fallback: match top-level window titles via regex patterns.
    3) Retry until timeout (seconds).
    Returns True if at least one window was minimized.
    """
    if sys.platform != "win32":
        logging.debug("minimize_qmt_window_improved: not on Windows, skip")
        return False

    end = time.time() + timeout
    exe_candidates = ["XtMiniQmt.exe", "XtMiniQmt", "XtMiniQmt_x64.exe", "XtMiniQmt32.exe"]
    title_patterns = [r"XtMiniQmt", r"miniqmt", r"QtMiniQmt"]

    while time.time() < end:
        # 1) 按进程查找
        procs = _find_processes_by_exe_names(exe_candidates)
        found_any = False
        for p in procs:
            try:
                pid = p.pid
                hwnds = _collect_hwnds_for_pid(pid)
                if hwnds:
                    for hwnd, title in hwnds:
                        try:
                            if _minimize_hwnd(hwnd):
                                logging.info(f"已将进程 pid={pid} 的窗口最小化：hwnd={hwnd}, title={title}")
                                found_any = True
                        except Exception as e:
                            logging.debug(f"最小化 hwnd 异常: {e}")
            except Exception:
                continue
        if found_any:
            return True

        # 2) 回退：按标题正则匹配
        for pat in title_patterns:
            try:
                if minimize_window_by_title_regex(pat, timeout=0.8):
                    logging.info(f"通过标题模式 '{pat}' 最小化了窗口")
                    return True
            except Exception:
                pass

        time.sleep(0.5)

    logging.debug(f"在 {timeout}s 内未能最小化 QMT 窗口")
    return False


# 保留旧的按标题最小化的实现作为回退（简短版）
def minimize_window_by_title_regex(title_regex: str, timeout: float = 1.0) -> bool:
    """
    Try to find a top-level window whose title matches title_regex (re.search).
    If found, call ShowWindow(hwnd, SW_MINIMIZE) and return True.
    Retries until timeout seconds. Returns False if not found or on non-Windows.
    """
    if sys.platform != "win32":
        logging.debug("minimize_window_by_title_regex: not on Windows, skip")
        return False

    pattern = re.compile(title_regex, re.IGNORECASE)
    end = time.time() + timeout
    SW_MINIMIZE = 6
    user32 = ctypes.windll.user32

    while time.time() < end:
        found = False

        def _check(hwnd):
            nonlocal found
            try:
                if not _is_window_visible(hwnd):
                    return
                title = _get_window_text(hwnd)
                if not title:
                    return
                if pattern.search(title):
                    # minimize
                    try:
                        user32.ShowWindow(hwnd, SW_MINIMIZE)
                        logging.info(f"已将窗口最小化（标题匹配）：hwnd={hwnd}, title={title}")
                        found = True
                    except Exception as e:
                        logging.warning(f"最小化窗口失败 hwnd={hwnd}, title={title}, err={e}")
            except Exception:
                pass

        try:
            _enum_windows(_check)
        except Exception:
            logging.debug("窗口枚举失败（可能不是 Windows 环境或权限问题）")
            return False

        if found:
            return True
        time.sleep(0.2)

    logging.debug(f"在 {timeout}s 内未找到匹配窗口: {title_regex}")
    return False
# -----------------------------------------------------------------------------


def main():
    ensure_utf8_stdio()
    helpers.install_console_stream_filters()

    # parse args here (include optional --ui-id for GUI-launched processes)
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--account', required=True, help='账户别名或ID')
    parser.add_argument('--ui-id', required=False, help='来自 GUI 的唯一进程标识（可选）')
    args = None
    try:
        args = parser.parse_args()
        account_name = args.account
        ui_id = getattr(args, "ui_id", None)
    except SystemExit:
        # keep behaviour consistent with previous code: let SystemExit propagate
        raise
    except Exception as e:
        print("解析参数失败:", e)
        raise

    # If GUI passed a ui_id, write a pid file and register cleanup handlers.
    pidfile_path = None
    if ui_id:
        pidfile_path = _write_ui_pid_file(ui_id)
        if pidfile_path:
            # ensure pidfile is removed on normal exit
            atexit.register(lambda: _remove_ui_pid_file(pidfile_path))

            # signal cleanup: try to remove pidfile on abrupt termination as well
            try:
                import signal

                def _safe_exit(signum, frame):
                    _remove_ui_pid_file(pidfile_path)
                    # re-raise default behavior / exit
                    sys.exit(0)

                signal.signal(signal.SIGTERM, _safe_exit)
                signal.signal(signal.SIGINT, _safe_exit)
                try:
                    signal.signal(signal.SIGBREAK, _safe_exit)  # Windows
                except Exception:
                    pass
            except Exception:
                pass

    # Single-instance check (same as before)
    if not helpers.check_duplicate_instance('main.py', account_name):
        print(f"账户[{account_name}]已有实例运行，退出")
        sys.exit(0)

    # Optionally set process title if ui_id is provided and setproctitle is installed
    if ui_id:
        try:
            from setproctitle import setproctitle
            try:
                setproctitle(f"miniQMT:{ui_id}")
            except Exception:
                pass
        except Exception:
            # setproctitle not installed — it's optional
            pass

    setup_logging(console=True, file=True, account_name=account_name)

    logging.info("===============程序开始执行================")
    logging.info(f"sys.argv = {sys.argv}")
    logging.info(f"账户参数解析成功: {account_name}")
    if ui_id:
        logging.info(f"ui_id = {ui_id}, pidfile = {pidfile_path}")

    # --- enhanced config lookup: try map, direct filename, then scan for matching account_id in files ---
    config_path = ACCOUNT_CONFIG_MAP.get(account_name)
    if not config_path:
        # 1) try direct filename under core_parameters/account/{account_name}.json
        direct_candidate = os.path.join("core_parameters", "account", f"{account_name}.json")
        if os.path.exists(direct_candidate):
            config_path = direct_candidate
            logging.info(f"通过文件名直接找到账户配置: {config_path}")
        else:
            # 2) scan directory for json files whose content contains matching account_id
            acc_dir = os.path.join("core_parameters", "account")
            try:
                if os.path.isdir(acc_dir):
                    for fn in os.listdir(acc_dir):
                        if not fn.lower().endswith(".json"):
                            continue
                        fp = os.path.join(acc_dir, fn)
                        try:
                            data = load_json_file(fp)
                        except Exception:
                            data = None
                        if not data:
                            continue
                        # check common field names for account id
                        candidate_ids = []
                        if isinstance(data, dict):
                            # standard field
                            if data.get("account_id") is not None:
                                candidate_ids.append(str(data.get("account_id")))
                            # some configs might nest under "account" or other key
                            if data.get("account") and isinstance(data.get("account"), dict):
                                if data["account"].get("account_id") is not None:
                                    candidate_ids.append(str(data["account"].get("account_id")))
                            # fallback: check any top-level value that equals account_name
                            for v in data.values():
                                try:
                                    if str(v) == str(account_name):
                                        candidate_ids.append(str(account_name))
                                except Exception:
                                    pass
                        if any(str(account_name) == cid for cid in candidate_ids):
                            config_path = fp
                            logging.info(f"通过文件内容匹配到账户配置: {config_path}")
                            break
            except Exception as e:
                logging.debug(f"扫描 account 配置目录失败: {e}")

    if not config_path:
        logging.error("找不到账户配置，退出")
        return

    try:
        config = load_json_file(config_path)
        logging.info(f"账户配置加载成功: {config_path}")
    except Exception as e:
        logging.error(f"加载 config_path 出错：{e}")
        logging.error(traceback.format_exc())
        return

    path_qmt = config['path_qmt']
    session_id = config['session_id']
    account_id = config['account_id']
    sell_time = config['sell_time']
    buy_time = config['buy_time']
    check_time_first = config['check_time_first']
    check_time_second = config['check_time_second']

    # 检查 miniQMT 并保证连接（内部可能会自动重启并登录）
    check_and_restart(config_path)

    # 初始化 xt_trader（回调在 helpers 中定义并注册）
    xt_trader = helpers.init_xt_trader(path_qmt, session_id)

    # 确保 qmt 连接（会使用 xt_trader）
    ensure_qmt_and_connect(config_path, xt_trader, logger=logging)

    # At this point auto-login should have completed (if configured).
    # Attempt to minimize the QMT window (Windows only). This is best-effort.
    try:
        # 增加更长的 timeout 以适应窗口创建/标题更新延迟
        minimized = minimize_qmt_window_improved(timeout=12)
        if minimized:
            logging.info("在自动登录后已最小化 QMT 窗口（尝试成功）。")
        else:
            logging.info("未能找到或最小化 QMT 窗口（可能不是 Windows 或窗口标题/进程名不匹配）。")
    except Exception as e:
        logging.exception(f"尝试最小化 QMT 窗口时发生异常: {e}")

    # 加载股票代码与 reverse mapping
    try:
        _, _, reverse_mapping = load_stock_code_maps()
        logging.info("股票代码加载成功，并生成 reverse_mapping")
    except Exception as e:
        logging.error(f"加载股票代码失败: {e}")
        xt_trader.stop()
        return

    # 初始资产/持仓快照（用于生成交易计划）
    account_asset_info = helpers.print_account_asset(xt_trader, account_id)
    positions = helpers.print_positions(xt_trader, account_id, reverse_mapping, account_asset_info)
    positions_dict = positions_to_dict(positions)

    # 生成最终交易计划（覆盖或创建文件）
    trade_plan_draft_file_path = 'tradeplan/trade_plan_draft.json'
    trade_date = datetime.now().strftime('%Y-%m-%d')
    trade_plan_file = f'./tradeplan/final/trade_plan_final_{account_id}_{trade_date.replace("-", "")}.json'

    generate_trade_plan_final_func(
        config=config,
        account_asset_info=account_asset_info,
        positions=positions_dict,
        trade_date=trade_date,
        setting_file_path=trade_plan_draft_file_path,
        trade_plan_file=trade_plan_file
    )

    time.sleep(1)
    logging.info("布置定时任务")
    scheduler = helpers.create_scheduler()

    # 注册关键任务（使用 tasks 中的工厂）
    sell_task = tasks.sell_execution_task_factory(xt_trader, account_id, trade_plan_file, trade_plan_draft_file_path)
    helpers.add_cron_job(scheduler, sell_task, sell_time, job_id="sell_execution_task")

    buy_task = tasks.buy_execution_task_factory(xt_trader, account_id, trade_plan_file, trade_plan_draft_file_path)
    helpers.add_cron_job(scheduler, buy_task, buy_time, job_id="buy_execution_task")

    cancel_times = [check_time_first, check_time_second, "13:00:03"]
    cancel_jobs = []
    for idx, t in enumerate(cancel_times, 1):
        cancel_jobs.append({
            "func": tasks.cancel_and_reorder_task_factory(xt_trader, account_id, reverse_mapping),
            "time": t,
            "id": f"cancel_and_reorder_task_{idx}"
        })
    helpers.add_multiple_cron_jobs(scheduler, cancel_jobs)

    print_jobs = [
        {"func": tasks.print_positions_task_factory(xt_trader, account_id, reverse_mapping), "time": "09:35:00", "id": "print_positions_task_0935"},
        {"func": tasks.print_positions_task_factory(xt_trader, account_id, reverse_mapping), "time": "14:57:00", "id": "print_positions_task_1457"}
    ]
    helpers.add_multiple_cron_jobs(scheduler, print_jobs)

    # 511880 自动买卖
    buy_h, buy_m, buy_s = AUTO_BUY_511880_TIME
    buy_511880_job = tasks.buy_all_funds_to_511880_factory(xt_trader, account_id)
    helpers.add_cron_job(scheduler, buy_511880_job, f"{buy_h:02d}:{buy_m:02d}:{buy_s:02d}", job_id="auto_buy_511880")
    chk_buy_h, chk_buy_m, chk_buy_s = helpers.add_seconds_to_hms(buy_h, buy_m, buy_s, 20)
    helpers.add_cron_job(scheduler, tasks.cancel_and_reorder_task_factory(xt_trader, account_id, reverse_mapping),
                         f"{chk_buy_h:02d}:{chk_buy_m:02d}:{chk_buy_s:02d}", job_id="check_after_511880_buy")

    sell_h, sell_m, sell_s = AUTO_SELL_511880_TIME
    sell_511880_job = tasks.sell_all_511880_factory(xt_trader, account_id)
    helpers.add_cron_job(scheduler, sell_511880_job, f"{sell_h:02d}:{sell_m:02d}:{sell_s:02d}", job_id="auto_sell_511880")
    chk_sell_h, chk_sell_m, chk_sell_s = helpers.add_seconds_to_hms(sell_h, sell_m, sell_s, 20)
    helpers.add_cron_job(scheduler, tasks.cancel_and_reorder_task_factory(xt_trader, account_id, reverse_mapping),
                         f"{chk_sell_h:02d}:{chk_sell_m:02d}:{chk_sell_s:02d}", job_id="check_after_511880_sell")

    # 自动推送 frontend（保持原有 lambda 调用方式）
    helpers.add_cron_job(
        scheduler,
        lambda path=r"C:\Users\ceicei\PycharmProjects\miniQMT-frontend": push_project_to_github(path),
        "09:36:00",
        job_id="push_miniQMT_frontend_to_github"
    )

    # 云飞跟投任务（使用当前快照）
    # 关键修正：把生成最终交易计划的函数传入 helpers.add_yunfei_jobs
    helpers.add_yunfei_jobs(scheduler, xt_trader, config, account_asset_info, positions_dict, StockAccount(account_id), generate_trade_plan_final_func)

    scheduler.start()

    # 信号注册（会在 handle_exit 中停止 scheduler 和 xt_trader）
    helpers.register_signal_handlers(scheduler, xt_trader)

    try:
        while True:
            time.sleep(5)
    except (KeyboardInterrupt, SystemExit):
        logging.info("程序被手动终止。")
    finally:
        try:
            scheduler.shutdown()
        except Exception:
            pass
        try:
            xt_trader.stop()
        except Exception:
            pass
        # remove pidfile if any (redundant with atexit but helps in case of direct exit paths)
        if ui_id and pidfile_path:
            _remove_ui_pid_file(pidfile_path)
        logging.info("交易线程已停止.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        err_txt = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
        logging.error(err_txt)
        raise