import tkinter as tk
from tkinter import scrolledtext, messagebox
from tkinter import ttk
import subprocess
import threading
import os

# 配置区
ACCOUNTS = {
    "shu": {"log_file": "logs/shu.log"},
    "1234": {"log_file": "logs/1234.log"}
}
MAIN_SCRIPT = "main.py"
PLAN_FILE = "core_parameters/setting/setting.json"

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
        # 清空旧日志
        open(log_path, "w").close()
        self.proc = subprocess.Popen(
            ["python", MAIN_SCRIPT, "-a", self.account],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
            encoding="utf-8"   # 若遇乱码可尝试 "gbk"
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
                # 实时更新日志
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
        self.widgets["log_text"].delete(1.0, tk.END)
        self.widgets["log_text"].insert(tk.END, log)
        self.widgets["log_text"].see(tk.END)

    def update_status(self):
        self.widgets["status"].config(text=self.status())

def save_plan(plan_text):
    os.makedirs(os.path.dirname(PLAN_FILE), exist_ok=True)
    with open(PLAN_FILE, "w", encoding="utf-8") as f:
        f.write(plan_text)
    messagebox.showinfo("提示", f"计划已保存到 {PLAN_FILE}")

def load_plan():
    if os.path.exists(PLAN_FILE):
        with open(PLAN_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def build_account_frame(root, acc, config):
    frame = ttk.LabelFrame(root, text=f"账户：{acc}", padding=(10,8))
    frame.pack(side=tk.LEFT, padx=10, pady=10, fill=tk.BOTH, expand=True)

    status_label = ttk.Label(frame, text="未启动", foreground="#2779aa", font=("微软雅黑", 10, "bold"))
    status_label.pack(anchor="w", pady=2)
    btn_frame = ttk.Frame(frame)
    btn_frame.pack(fill=tk.X, pady=3)
    btn_start = ttk.Button(btn_frame, text="启动", width=10)
    btn_stop = ttk.Button(btn_frame, text="停止", width=10)
    btn_start.pack(side=tk.LEFT, padx=3)
    btn_stop.pack(side=tk.LEFT, padx=3)

    log_label = ttk.Label(frame, text="日志窗口：")
    log_label.pack(anchor="w", pady=(6,0))
    log_text = scrolledtext.ScrolledText(frame, height=10, width=50, font=("Consolas", 10), background="#f7f7fa")
    log_text.pack(fill=tk.BOTH, expand=True, pady=2)
    btn_refresh = ttk.Button(frame, text="刷新日志")
    btn_refresh.pack(pady=2)

    widgets = {"status": status_label, "log_text": log_text}
    proc = AccountProcess(acc, config, widgets)
    btn_start.config(command=lambda: [proc.start(), proc.update_status()])
    btn_stop.config(command=lambda: [proc.stop(), proc.update_status()])
    btn_refresh.config(command=proc.update_log)
    return proc

def main():
    root = tk.Tk()
    root.title("miniQMT 多账户本地管理")
    root.geometry("1200x800")
    try:
        root.state("zoomed")
    except Exception:
        pass

    style = ttk.Style(root)
    # 使用clam主题比默认更现代，可以试试其它如 "alt", "arc"（需ttkthemes）等
    style.theme_use('clam')
    style.configure("TLabelframe", background="#eaf2fb", font=("微软雅黑", 11, "bold"))
    style.configure("TButton", font=("微软雅黑", 10))
    style.configure("TLabel", background="#eaf2fb")
    style.configure("TFrame", background="#eaf2fb")

    # 计划区
    plan_frame = ttk.LabelFrame(root, text="交易计划粘贴区", padding=(10,8))
    plan_frame.pack(fill=tk.X, padx=12, pady=8)
    plan_text = tk.Text(plan_frame, height=6, width=100, font=("Consolas", 11), background="#f8faff")
    plan_text.pack(fill=tk.X)
    plan_text.insert(1.0, load_plan())
    btn_save = ttk.Button(plan_frame, text="保存计划", width=12, command=lambda: save_plan(plan_text.get(1.0, tk.END)))
    btn_save.pack(pady=4, anchor="e")

    # 功能按钮区
    top_frame = ttk.Frame(root)
    top_frame.pack(side=tk.TOP, fill=tk.X, pady=2)
    global procs
    procs = []
    def all_start():  [p.start() or p.update_status() for p in procs]
    def all_stop():   [p.stop() or p.update_status() for p in procs]
    def all_refresh(): [p.update_log() for p in procs]

    ttk.Button(top_frame, text="全部启动", width=13, command=all_start).pack(side=tk.LEFT, padx=6, pady=6)
    ttk.Button(top_frame, text="全部停止", width=13, command=all_stop).pack(side=tk.LEFT, padx=6, pady=6)
    ttk.Button(top_frame, text="全部刷新日志", width=15, command=all_refresh).pack(side=tk.LEFT, padx=6, pady=6)
    ttk.Button(top_frame, text="退出", width=10, command=lambda: [all_stop(), root.destroy()]).pack(side=tk.RIGHT, padx=6, pady=6)

    # 账户管理区
    accounts_frame = ttk.Frame(root)
    accounts_frame.pack(fill=tk.BOTH, expand=True)
    for acc, cfg in ACCOUNTS.items():
        proc = build_account_frame(accounts_frame, acc, cfg)
        procs.append(proc)

    root.mainloop()

if __name__ == "__main__":
    main()