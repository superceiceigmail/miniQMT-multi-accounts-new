import os
import subprocess
import threading
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText
from tkinter import messagebox

MAIN_SCRIPT = "main.py"  # 注意：可根据实际后端文件调整路径

class AccountProcess:
    def __init__(self, account, config, widgets):
        self.account = account
        self.config = config
        self.proc = None
        self.log_buffer = []
        self.log_thread = None
        self.running = False
        self.widgets = widgets  # dict: {status, log_text}

    def start(self):
        if self.proc and self.proc.poll() is None:
            return
        log_path = self.config["log_file"]
        log_dir = os.path.dirname(log_path)
        os.makedirs(log_dir, exist_ok=True)
        open(log_path, "w").close()
        self.proc = subprocess.Popen(
            ["python", MAIN_SCRIPT, "-a", self.account],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
            encoding="utf-8"
        )
        self.running = True
        self.log_thread = threading.Thread(target=self._read_log, daemon=True)
        self.log_thread.start()
        self.update_status()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
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
        with open(log_path, "a", encoding="utf-8") as f:
            for line in self.proc.stdout:
                f.write(line)
                f.flush()
                self.log_buffer.append(line)
                if len(self.log_buffer) > 1000:
                    self.log_buffer = self.log_buffer[-1000:]
                self.widgets["log_text"].after(0, self.update_log)
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
        log = self.get_log(100)
        self.widgets["log_text"].delete(1.0, "end")
        self.widgets["log_text"].insert("end", log)
        self.widgets["log_text"].see("end")

    def update_status(self):
        self.widgets["status"].config(text=self.status())

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