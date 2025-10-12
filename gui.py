import ttkbootstrap as tb
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText
from gui.account_exec import build_account_frame, save_plan, load_plan
from gui.diary_page import DiaryPage
from gui.todolist_page import TodolistPage
from gui.remind_page import RemindPage, load_reminders, save_reminders, check_due_reminders
from tkinter import messagebox

# 配置区
ACCOUNTS = {
    "shu": {"log_file": "logs/shu.log"},
    "1234": {"log_file": "logs/1234.log"}
}
PLAN_FILE = "tradeplan/trade_plan_draft.json"

def main():
    root = tb.Window(themename="cosmo")
    root.title("miniQMT 多账户本地管理")
    root.geometry("1200x800")
    try:
        root.state("zoomed")
    except Exception:
        pass

    menu_bar = tb.Menu(root)
    root.config(menu=menu_bar)

    main_frame = tb.Frame(root)
    main_frame.pack(fill=BOTH, expand=True)

    exec_frame = tb.Frame(main_frame)
    exec_frame.pack(fill=BOTH, expand=True)

    plan_frame = tb.LabelFrame(exec_frame, text="交易计划粘贴区", padding=(10,8))
    plan_frame.pack(fill=X, padx=12, pady=8)
    plan_text = ScrolledText(plan_frame, height=6, width=100, font=("Consolas", 11))
    plan_text.pack(fill=X)
    plan_text.insert(1.0, load_plan(PLAN_FILE))
    btn_save = tb.Button(
        plan_frame,
        text="保存计划",
        width=12,
        command=lambda: save_plan(plan_text.get(1.0, END), PLAN_FILE),
        bootstyle="primary-outline"
    )
    btn_save.pack(pady=4, anchor="w")

    top_frame = tb.Frame(exec_frame)
    top_frame.pack(side=TOP, fill=X, pady=2)
    global procs
    procs = []
    def all_start():  [p.start() or p.update_status() for p in procs]
    def all_stop():   [p.stop() or p.update_status() for p in procs]
    def all_refresh(): [p.update_log() for p in procs]

    tb.Button(top_frame, text="全部启动", width=13, command=all_start, bootstyle="success-outline").pack(side=LEFT, padx=6, pady=6)
    tb.Button(top_frame, text="全部停止", width=13, command=all_stop, bootstyle="danger-outline").pack(side=LEFT, padx=6, pady=6)
    tb.Button(top_frame, text="全部刷新日志", width=15, command=all_refresh, bootstyle="info-outline").pack(side=LEFT, padx=6, pady=6)
    tb.Button(top_frame, text="退出", width=10, command=lambda: [all_stop(), root.destroy()], bootstyle="secondary-outline").pack(side=RIGHT, padx=6, pady=6)

    accounts_frame = tb.Frame(exec_frame)
    accounts_frame.pack(fill=BOTH, expand=True)
    for acc, cfg in ACCOUNTS.items():
        proc = build_account_frame(accounts_frame, acc, cfg)
        procs.append(proc)

    diary_frame = DiaryPage(main_frame)
    diary_frame.pack_forget()  # 默认隐藏

    todolist_frame = TodolistPage(main_frame)
    todolist_frame.pack_forget()

    remind_frame = RemindPage(main_frame)
    remind_frame.pack_forget()

    # 页面切换
    def show_exec():
        exec_frame.pack(fill=BOTH, expand=True)
        diary_frame.pack_forget()
        todolist_frame.pack_forget()
        remind_frame.pack_forget()
    def show_diary():
        exec_frame.pack_forget()
        diary_frame.pack(fill=BOTH, expand=True)
        diary_frame.load_today_content()
        diary_frame.load_diary_page()
        todolist_frame.pack_forget()
        remind_frame.pack_forget()
    def show_todolist():
        exec_frame.pack_forget()
        diary_frame.pack_forget()
        todolist_frame.pack(fill=BOTH, expand=True)
        remind_frame.pack_forget()
        # 每次切换到todolist页面都刷新
        if hasattr(todolist_frame, "refresh"):
            todolist_frame.refresh()
    def show_remind():
        exec_frame.pack_forget()
        diary_frame.pack_forget()
        todolist_frame.pack_forget()
        remind_frame.pack(fill=BOTH, expand=True)
        # 每次切换到提醒页面都强制刷新
        if hasattr(remind_frame, "refresh"):
            remind_frame.refresh()

    # 菜单顺序调整为：交易执行、交易日记、todolist、提醒、切换主题
    menu_bar.add_command(label="交易执行", command=show_exec)
    menu_bar.add_command(label="交易日记", command=show_diary)
    menu_bar.add_command(label="todolist", command=show_todolist)
    menu_bar.add_command(label="提醒", command=show_remind)

    # ----------- 动态切换主题菜单（放到最后） -----------
    themes = tb.Style().theme_names()
    theme_menu = tb.Menu(menu_bar, tearoff=0)
    def set_theme(theme_name):
        root.style.theme_use(theme_name)
    for t in themes:
        theme_menu.add_command(label=t, command=lambda tn=t: set_theme(tn))
    menu_bar.add_cascade(label="切换主题", menu=theme_menu)
    # ----------- 主题菜单结束 ---------------

    show_exec()

    root.mainloop()

if __name__ == "__main__":
    main()