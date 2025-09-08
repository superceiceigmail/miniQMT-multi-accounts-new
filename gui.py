import tkinter as tk
from tkinter import scrolledtext, messagebox
from tkinter import ttk
import subprocess
import threading
import os
import json
from datetime import date, datetime, timedelta

# 配置区
ACCOUNTS = {
    "shu": {"log_file": "logs/shu.log"},
    "1234": {"log_file": "logs/1234.log"}
}
MAIN_SCRIPT = "main.py"
PLAN_FILE = "core_parameters/setting/setting.json"
DIARY_FILE = "logs/transection_tracking.json"
DIARY_PAGE_SIZE = 10

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

def ensure_diary_file():
    os.makedirs(os.path.dirname(DIARY_FILE), exist_ok=True)
    if not os.path.exists(DIARY_FILE):
        with open(DIARY_FILE, "w", encoding="utf-8") as f:
            json.dump({"continuous_days": 0, "records": []}, f, ensure_ascii=False, indent=2)

def load_diary():
    ensure_diary_file()
    try:
        with open(DIARY_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                raise ValueError("Empty file")
            return json.loads(content)
    except Exception:
        data = {"continuous_days": 0, "records": []}
        with open(DIARY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data

def save_diary(diary_data):
    os.makedirs(os.path.dirname(DIARY_FILE), exist_ok=True)
    with open(DIARY_FILE, "w", encoding="utf-8") as f:
        json.dump(diary_data, f, ensure_ascii=False, indent=2)

def add_diary_record(honor, plan, rules, followed_plan, score, score_unit):
    today_str = date.today().isoformat()
    diary_data = load_diary()
    records = diary_data["records"]
    already = False
    for rec in records:
        if rec["date"] == today_str:
            rec["honor"] = honor
            rec["plan"] = plan
            rec["rules"] = rules
            rec["followed_plan"] = followed_plan
            rec["score"] = score
            rec["score_unit"] = score_unit
            rec["timestamp"] = datetime.now().isoformat(timespec="seconds")
            already = True
            break
    if not already:
        records.append({
            "date": today_str,
            "honor": honor,
            "plan": plan,
            "rules": rules,
            "followed_plan": followed_plan,
            "score": score,
            "score_unit": score_unit,
            "timestamp": datetime.now().isoformat(timespec="seconds")
        })
    if followed_plan:
        prev_day = (date.fromisoformat(today_str) - timedelta(days=1)).isoformat()
        prev = next((r for r in records if r["date"] == prev_day), None)
        if prev and prev["followed_plan"]:
            diary_data["continuous_days"] = diary_data.get("continuous_days", 0) + 1
        else:
            diary_data["continuous_days"] = 1
    else:
        diary_data["continuous_days"] = 0
    diary_data["records"] = records
    save_diary(diary_data)

def get_diary_page(page=1):
    diary_data = load_diary()
    records = diary_data["records"]
    records_sorted = sorted(records, key=lambda r: r["date"], reverse=True)
    total = len(records_sorted)
    total_pages = (total + DIARY_PAGE_SIZE - 1) // DIARY_PAGE_SIZE
    start = (page - 1) * DIARY_PAGE_SIZE
    end = start + DIARY_PAGE_SIZE
    return records_sorted[start:end], total_pages

def get_continuous_days():
    diary_data = load_diary()
    return diary_data.get("continuous_days", 0)

class DiaryPage(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.page = 1
        self.create_widgets()
        self.load_today_content()
        self.load_diary_page()

    def create_widgets(self):
        diary_entry_frame = ttk.LabelFrame(self, text="今日交易日记（结构化）", padding=(10, 8))
        diary_entry_frame.pack(fill=tk.X, padx=10, pady=8)

        label1 = ttk.Label(diary_entry_frame, text="今日功勋：")
        label1.pack(anchor="w", pady=(2,0))
        self.honor_text = scrolledtext.ScrolledText(diary_entry_frame, height=3, width=80, font=("Consolas", 10), background="#f7f7fa")
        self.honor_text.pack(fill=tk.X, pady=2)

        # 积分输入
        label_score = ttk.Label(diary_entry_frame, text="积分：")
        label_score.pack(anchor="w", pady=(2, 0))
        score_frame = ttk.Frame(diary_entry_frame)
        score_frame.pack(fill=tk.X, pady=2)
        self.score_var = tk.StringVar()
        self.score_unit_var = tk.StringVar(value="小时")
        score_entry = ttk.Entry(score_frame, textvariable=self.score_var, width=10)
        score_entry.pack(side=tk.LEFT)
        score_unit = ttk.Combobox(score_frame, textvariable=self.score_unit_var, values=["小时", "天"], width=6, state="readonly")
        score_unit.pack(side=tk.LEFT, padx=4)
        score_unit.current(0)

        label2 = ttk.Label(diary_entry_frame, text="后续计划：")
        label2.pack(anchor="w", pady=(2,0))
        self.plan_text = scrolledtext.ScrolledText(diary_entry_frame, height=3, width=80, font=("Consolas", 10), background="#f7f7fa")
        self.plan_text.pack(fill=tk.X, pady=2)

        label3 = ttk.Label(diary_entry_frame, text="要点和规则：")
        label3.pack(anchor="w", pady=(2,0))
        self.rules_text = scrolledtext.ScrolledText(diary_entry_frame, height=2, width=80, font=("Consolas", 10), background="#f7f7fa")
        self.rules_text.pack(fill=tk.X, pady=2)

        self.followed_var = tk.BooleanVar(value=True)
        diary_check = ttk.Checkbutton(diary_entry_frame, text="是否按照策略规划配置和执行", variable=self.followed_var)
        diary_check.pack(anchor="w", pady=2)
        diary_save_btn = ttk.Button(diary_entry_frame, text="保存今日日记", command=self.save_today)
        diary_save_btn.pack(anchor="e", pady=2)

        self.encourage_label = ttk.Label(self, font=("微软雅黑", 12, "bold"), foreground="#1b9d55")
        self.encourage_label.pack(pady=4)

        diary_list_frame = ttk.LabelFrame(self, text="历史交易日记", padding=(10, 8))
        diary_list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)
        self.diary_list = scrolledtext.ScrolledText(diary_list_frame, height=15, width=100, font=("Consolas", 10), background="#f8faff", state="disabled")
        self.diary_list.pack(fill=tk.BOTH, expand=True, pady=2)
        nav_frame = ttk.Frame(diary_list_frame)
        nav_frame.pack(fill=tk.X)
        self.prev_btn = ttk.Button(nav_frame, text="上一页", width=12, command=self.prev_page)
        self.next_btn = ttk.Button(nav_frame, text="下一页", width=12, command=self.next_page)
        self.page_label = ttk.Label(nav_frame)
        self.prev_btn.pack(side=tk.LEFT, padx=2, pady=3)
        self.next_btn.pack(side=tk.LEFT, padx=2, pady=3)
        self.page_label.pack(side=tk.LEFT, padx=10)

    def load_today_content(self):
        today_str = date.today().isoformat()
        diary_data = load_diary()
        rec = next((r for r in diary_data["records"] if r["date"] == today_str), None)
        if rec:
            self.honor_text.delete(1.0, tk.END)
            self.honor_text.insert(tk.END, rec.get("honor", ""))
            self.plan_text.delete(1.0, tk.END)
            self.plan_text.insert(tk.END, rec.get("plan", ""))
            self.rules_text.delete(1.0, tk.END)
            self.rules_text.insert(tk.END, rec.get("rules", ""))
            self.score_var.set(str(rec.get("score", "")))
            self.score_unit_var.set(rec.get("score_unit", "小时"))
            self.followed_var.set(rec.get("followed_plan", True))
        else:
            self.honor_text.delete(1.0, tk.END)
            self.plan_text.delete(1.0, tk.END)
            self.rules_text.delete(1.0, tk.END)
            self.score_var.set("")
            self.score_unit_var.set("小时")
            self.followed_var.set(True)

    def save_today(self):
        honor = self.honor_text.get(1.0, tk.END).strip()
        plan = self.plan_text.get(1.0, tk.END).strip()
        rules = self.rules_text.get(1.0, tk.END).strip()
        followed = self.followed_var.get()
        score = self.score_var.get().strip()
        score_unit = self.score_unit_var.get()
        if not honor and not plan and not rules:
            messagebox.showwarning("提示", "请填写至少一项内容！")
            return
        try:
            score = float(score) if score else 0
        except ValueError:
            messagebox.showwarning("提示", "积分请输入数字！")
            return
        add_diary_record(honor, plan, rules, followed, score, score_unit)
        # 注意保存后不清空内容，便于补充
        self.update_encourage()
        self.load_diary_page()
        messagebox.showinfo("保存成功", "今日交易日记已保存！")

    def update_encourage(self):
        days = get_continuous_days()
        if days > 0:
            msg = f"你已经按照策略规划连续配置和执行了 {days} 天，继续保持！"
        else:
            msg = "加油！从今天开始，养成良好的交易习惯！"
        self.encourage_label.config(text=msg)

    def load_diary_page(self):
        records, total_pages = get_diary_page(self.page)
        self.diary_list.config(state="normal")
        self.diary_list.delete(1.0, tk.END)
        if not records:
            self.diary_list.insert(tk.END, "暂无历史日记记录。\n")
        else:
            for rec in records:
                self.diary_list.insert(tk.END,
                    f'日期: {rec["date"]}\n'
                    f'是否按策略执行: {"是" if rec.get("followed_plan", False) else "否"}\n'
                    f'今日功勋:\n{rec.get("honor", "")}\n'
                    f'积分: {rec.get("score", "")} {rec.get("score_unit", "")}\n'
                    f'后续计划:\n{rec.get("plan", "")}\n'
                    f'要点和规则:\n{rec.get("rules", "")}\n'
                    f'保存时间: {rec.get("timestamp", "")}\n'
                    "----------------------------------------\n"
                )
        self.diary_list.config(state="disabled")
        self.page_label.config(text=f"第 {self.page} / {max(total_pages,1)} 页")
        self.update_encourage()
        self.prev_btn["state"] = tk.NORMAL if self.page > 1 else tk.DISABLED
        self.next_btn["state"] = tk.NORMAL if self.page < total_pages else tk.DISABLED

    def prev_page(self):
        if self.page > 1:
            self.page -= 1
            self.load_diary_page()

    def next_page(self):
        _, total_pages = get_diary_page(self.page)
        if self.page < total_pages:
            self.page += 1
            self.load_diary_page()

def main():
    root = tk.Tk()
    root.title("miniQMT 多账户本地管理")
    root.geometry("1200x800")
    try:
        root.state("zoomed")
    except Exception:
        pass

    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure("TLabelframe", background="#eaf2fb", font=("微软雅黑", 11, "bold"))
    style.configure("TButton", font=("微软雅黑", 10))
    style.configure("TLabel", background="#eaf2fb")
    style.configure("TFrame", background="#eaf2fb")

    menu_bar = tk.Menu(root)
    root.config(menu=menu_bar)

    main_frame = tk.Frame(root)
    main_frame.pack(fill=tk.BOTH, expand=True)

    exec_frame = tk.Frame(main_frame)
    exec_frame.pack(fill=tk.BOTH, expand=True)

    plan_frame = ttk.LabelFrame(exec_frame, text="交易计划粘贴区", padding=(10,8))
    plan_frame.pack(fill=tk.X, padx=12, pady=8)
    plan_text = tk.Text(plan_frame, height=6, width=100, font=("Consolas", 11), background="#f8faff")
    plan_text.pack(fill=tk.X)
    plan_text.insert(1.0, load_plan())
    btn_save = ttk.Button(plan_frame, text="保存计划", width=12, command=lambda: save_plan(plan_text.get(1.0, tk.END)))
    btn_save.pack(pady=4, anchor="e")

    top_frame = ttk.Frame(exec_frame)
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

    accounts_frame = ttk.Frame(exec_frame)
    accounts_frame.pack(fill=tk.BOTH, expand=True)
    for acc, cfg in ACCOUNTS.items():
        proc = build_account_frame(accounts_frame, acc, cfg)
        procs.append(proc)

    diary_frame = DiaryPage(main_frame)
    diary_frame.pack_forget()  # 默认隐藏

    def show_exec():
        exec_frame.pack(fill=tk.BOTH, expand=True)
        diary_frame.pack_forget()
    def show_diary():
        exec_frame.pack_forget()
        diary_frame.pack(fill=tk.BOTH, expand=True)
        diary_frame.load_today_content()
        diary_frame.load_diary_page()

    menu_bar.add_command(label="交易执行", command=show_exec)
    menu_bar.add_command(label="交易日记", command=show_diary)

    show_exec()
    root.mainloop()

if __name__ == "__main__":
    main()