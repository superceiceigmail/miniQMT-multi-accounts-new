import tkinter as tk
from tkinter import ttk
from gui.account_exec import build_account_frame, save_plan, load_plan
from gui.diary_page import DiaryPage

# 配置区
ACCOUNTS = {
    "shu": {"log_file": "logs/shu.log"},
    "1234": {"log_file": "logs/1234.log"}
}
PLAN_FILE = "core_parameters/setting/setting.json"

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
    plan_text.insert(1.0, load_plan(PLAN_FILE))
    btn_save = ttk.Button(plan_frame, text="保存计划", width=12, command=lambda: save_plan(plan_text.get(1.0, tk.END), PLAN_FILE))
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
