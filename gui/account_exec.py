# 改进后的 gui/account_exec.py
import os
import subprocess
import threading
import time
import signal
import platform
import re
import uuid
import psutil
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText
from tkinter import messagebox

MAIN_SCRIPT = "main.py"  # 注意：可根据实际后端文件调整路径
ENV_TAG_KEY = "MINIQMT_MANAGED_ACCOUNT"  # 旧的环境标记（account）
ENV_UI_ID = "MINIQMT_UI_ID"  # 新增：GUI 给子进程的唯一 id

class AccountProcess:
    """
    启动时附带唯一 ui_id（同时作为命令行参数和环境变量），便于精确终止。
    stop 使用多阶段策略，优先匹配 ui_id（通过 cmdline 或 environ）来定位并杀死进程。
    """
    def __init__(self, account, config, widgets):
        self.account = account
        self.config = config
        self.proc = None
        self._started_with_group = False
        self.log_buffer = []
        self.log_thread = None
        self.running = False
        self.widgets = widgets  # dict: {status, log_text}
        self._stop_lock = threading.Lock()
        self.ui_id = None  # 每次 start() 时生成并传递

    def start(self):
        print(f"[AccountProcess] 启动账户参数: {self.account}")
        if self.proc and self.proc.poll() is None:
            print("[AccountProcess] 进程已在运行，忽略 start")
            return
        log_path = self.config["log_file"]
        log_dir = os.path.dirname(log_path)
        os.makedirs(log_dir, exist_ok=True)
        open(log_path, "w").close()

        # 生成唯一 ui_id（account + 时间 + uuid）
        uid = uuid.uuid4().hex[:8]
        ts = int(time.time())
        self.ui_id = f"{self.account}-{ts}-{uid}"

        # 传入环境变量标记，便于后代识别
        env = os.environ.copy()
        env[ENV_TAG_KEY] = str(self.account)
        env[ENV_UI_ID] = self.ui_id

        creationflags = 0
        start_new_session = False
        if platform.system() == "Windows":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            self._started_with_group = True
        else:
            start_new_session = True
            self._started_with_group = True

        # 把 ui_id 也放到命令行参数，main.py / helpers.parse_args 已支持 --ui-id
        cmd = ["python", MAIN_SCRIPT, "-a", self.account, "--ui-id", self.ui_id]

        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                encoding="utf-8",
                creationflags=creationflags,
                start_new_session=start_new_session,
                env=env
            )
        except TypeError:
            # 兼容某些环境（若传入参数导致 TypeError），回退到简单启动（仍传 env）
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                encoding="utf-8",
                env=env
            )
            self._started_with_group = False

        self.running = True
        self.log_thread = threading.Thread(target=self._read_log, daemon=True)
        self.log_thread.start()
        self.update_status()
        print(f"[AccountProcess] 已启动 pid={self.proc.pid}, ui_id={self.ui_id}")

    def stop(self):
        """
        非阻塞 stop：立即返回并在后台完成真正的杀进程工作。
        通过 ui_id 优先定位进程，作为精确匹配手段。
        """
        print(f"[AccountProcess] 请求停止账户: {self.account}, ui_id={self.ui_id}")
        if not self.proc and not self.ui_id:
            print("[AccountProcess] 无进程/ID，直接更新状态")
            self.running = False
            self.update_status()
            return

        if not self._stop_lock.acquire(blocking=False):
            print("[AccountProcess] stop 已在进行中，忽略重复调用")
            return

        # 立即让 UI 显示停止中
        self.running = False
        self.update_status()
        t = threading.Thread(target=self._do_stop, daemon=True)
        t.start()

    def _do_stop(self):
        """
        多阶段终止尝试，优先使用 ui_id（通过 cmdline 或 environ）来定位进程，然后递归终止。
        """
        try:
            target_ui = self.ui_id
            # 先收集 candidate pids 当作精确匹配目标
            candidates = set()

            # 如果 self.proc 存在并仍在运行，先把它加入候选
            if self.proc and self.proc.poll() is None:
                candidates.add(self.proc.pid)

            # 1) 尝试按 ui_id 在系统进程中匹配（cmdline 或环境变量）
            if target_ui:
                for p in psutil.process_iter(['pid', 'cmdline', 'name']):
                    try:
                        info = p.info
                        pid = info.get('pid')
                        cmdline = info.get('cmdline') or []
                        cmd_str = " ".join(cmdline)
                        if target_ui in cmd_str:
                            candidates.add(pid)
                            print(f"[AccountProcess._do_stop] cmdline 匹配 ui_id -> pid={pid}")
                            continue
                        # 尝试读 environ（不一定有权限）
                        try:
                            penv = p.environ()
                            if penv.get(ENV_UI_ID) == target_ui:
                                candidates.add(pid)
                                print(f"[AccountProcess._do_stop] environ 匹配 ui_id -> pid={pid}")
                                continue
                        except Exception:
                            pass
                    except Exception:
                        continue

            # 2) 如果没有匹配到任何候选，但存在 self.proc，则回退使用原有策略（按进程树/组）
            if not candidates and self.proc:
                candidates.add(self.proc.pid)

            # 3) 对 candidates 做逐个递归清理（先按组/会话，再按 psutil children）
            for pid in list(candidates):
                try:
                    print(f"[AccountProcess._do_stop] 清理候选 pid={pid}")
                    # 尝试组级终止（如果我们是用 start_new_session/CREATE_NEW_PROCESS_GROUP 启动）
                    try:
                        if self._started_with_group:
                            if platform.system() == "Windows":
                                try:
                                    # Windows: 发送 CTRL_BREAK_EVENT 给组（如果 supported）
                                    p = psutil.Process(pid)
                                    proc_obj = p
                                    # we cannot call proc_obj.send_signal directly if we didn't start it; fallback to terminate
                                    try:
                                        proc_obj.send_signal(signal.CTRL_BREAK_EVENT)
                                        print(f"[AccountProcess._do_stop] 发送 CTRL_BREAK_EVENT 给 pid={pid}")
                                    except Exception:
                                        pass
                                except Exception:
                                    pass
                            else:
                                try:
                                    pgid = os.getpgid(pid)
                                    os.killpg(pgid, signal.SIGTERM)
                                    print(f"[AccountProcess._do_stop] killpg SIGTERM pgid={pgid}")
                                except Exception:
                                    pass
                            # 给时间退出
                            try:
                                psutil.Process(pid).wait(timeout=4)
                                print(f"[AccountProcess._do_stop] pid={pid} 已退出 (组信号)")
                                continue
                            except Exception:
                                pass
                    except Exception:
                        pass

                    # 递归 children
                    try:
                        parent = psutil.Process(pid)
                        children = parent.children(recursive=True)
                        for c in children:
                            try:
                                c.terminate()
                            except Exception:
                                pass
                        gone, alive = psutil.wait_procs(children, timeout=4)
                        for a in alive:
                            try:
                                a.kill()
                            except Exception:
                                pass
                        # 终止 parent
                        try:
                            parent.terminate()
                            try:
                                parent.wait(timeout=4)
                            except Exception:
                                parent.kill()
                        except Exception:
                            pass
                    except psutil.NoSuchProcess:
                        pass
                    except Exception as e:
                        print(f"[AccountProcess._do_stop] 递归终止失败 pid={pid}: {e}")
                        pass

                except Exception as e:
                    print(f"[AccountProcess._do_stop] 清理候选 pid 异常: {e}")

            # 4) 全局兜底：再做一次基于 ui_id 的全系统扫描并强杀（防止 reparent）
            if target_ui:
                to_kill = []
                for p in psutil.process_iter(['pid', 'cmdline']):
                    try:
                        pid = p.info.get('pid')
                        cmdline = p.info.get('cmdline') or []
                        if target_ui in " ".join(cmdline):
                            try:
                                print(f"[AccountProcess._do_stop] 兜底匹配并终止 pid={pid}")
                                p.terminate()
                                to_kill.append(p)
                            except Exception:
                                pass
                    except Exception:
                        continue
                if to_kill:
                    gone, alive = psutil.wait_procs(to_kill, timeout=4)
                    for p in alive:
                        try:
                            p.kill()
                        except Exception:
                            pass

            # 5) 关闭 stdout，清理状态
            try:
                if self.proc and getattr(self.proc, 'stdout', None):
                    try:
                        self.proc.stdout.close()
                    except Exception:
                        pass
            except Exception:
                pass

            self.proc = None
            print(f"[AccountProcess._do_stop] 停止完成 account={self.account}, ui_id={self.ui_id}")

        finally:
            self._stop_lock.release()
            self.running = False
            self.update_status()

    def status(self):
        if not self.proc:
            return "未启动"
        if self.proc.poll() is None:
            return "运行中"
        return f"已退出({self.proc.returncode})"

    def _read_log(self):
        log_path = self.config["log_file"]
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                while True:
                    if not self.proc:
                        break
                    stdout = getattr(self.proc, "stdout", None)
                    if not stdout:
                        break
                    line = stdout.readline()
                    if not line:
                        if self.proc.poll() is not None:
                            break
                        time.sleep(0.1)
                        continue
                    f.write(line)
                    f.flush()
                    self.log_buffer.append(line)
                    if len(self.log_buffer) > 1000:
                        self.log_buffer = self.log_buffer[-1000:]
                    try:
                        self.widgets["log_text"].after(0, self.update_log)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[AccountProcess._read_log] 异常: {e}")
        finally:
            self.update_status()

    def get_log(self, tail=100):
        return "".join(self.log_buffer[-tail:]) if self.log_buffer else self._read_logfile()

    def _read_logfile(self, tail=100):
        path = self.config["log_file"]
        if not os.path.exists(path):
            return ""
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return "".join(lines[-tail:])

    def update_log(self):
        log = self.get_log(500)
        try:
            self.widgets["log_text"].delete(1.0, "end")
            self.widgets["log_text"].insert("end", log)
            self.widgets["log_text"].see("end")
        except Exception:
            pass

    def update_status(self):
        try:
            self.widgets["status"].config(text=self.status())
        except Exception:
            pass

def build_account_frame(root, acc, config):
    frame = tb.LabelFrame(root, text=f"账户：{acc}", padding=(10,8))
    frame.pack(side=LEFT, padx=10, pady=10, fill=BOTH, expand=True)

    status_label = tb.Label(frame, text="未启动", foreground="#2779aa", font=("微软雅黑", 10, "bold"))
    status_label.pack(anchor="w", pady=2)
    btn_frame = tb.Frame(frame)
    btn_frame.pack(fill=X, pady=3)
    btn_start = tb.Button(btn_frame, text="启动", width=10, bootstyle="success-outline")
    btn_stop = tb.Button(btn_frame, text="停止", width=10, bootstyle="danger-outline")
    btn_start.pack(side=LEFT, padx=3)
    btn_stop.pack(side=LEFT, padx=3)

    log_label = tb.Label(frame, text="日志窗口：")
    log_label.pack(anchor="w", pady=(6,0))
    log_text = ScrolledText(frame, height=10, width=50, font=("Consolas", 10), bootstyle="light")
    log_text.pack(fill=BOTH, expand=True, pady=2)
    btn_refresh = tb.Button(frame, text="刷新日志", bootstyle="info-outline")
    btn_refresh.pack(pady=2)

    widgets = {"status": status_label, "log_text": log_text}
    proc = AccountProcess(acc, config, widgets)
    btn_start.config(command=lambda: [proc.start(), proc.update_status()])
    btn_stop.config(command=lambda: [proc.stop(), proc.update_status()])
    btn_refresh.config(command=proc.update_log)
    return proc

def save_plan(plan_text, plan_file):
    os.makedirs(os.path.dirname(plan_file), exist_ok=True)
    with open(plan_file, "w", encoding="utf-8") as f:
        f.write(plan_text)
    messagebox.showinfo("提示", f"计划已保存到 {plan_file}")

def load_plan(plan_file):
    if os.path.exists(plan_file):
        with open(plan_file, "r", encoding="utf-8") as f:
            return f.read()
    return ""