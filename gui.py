import threading
import time
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
    "mama": {"log_file": "logs/mama.log"}
}
PLAN_FILE = "tradeplan/trade_plan_draft.json"

# 全局进程列表（每个元素为 AccountProcess）
procs = []
# 顺序启动线程与控制事件
_seq_start_thread = None
_seq_start_stop_event = threading.Event()
# 每个账号之间的间隔秒数（全部启动时）
SEQ_START_INTERVAL_SECONDS = 30


def _sequential_start_worker(interval_seconds: int):
    """
    在单独线程中按顺序启动 procs：
    - 每次启动一个账号后等待 interval_seconds（中途若收到停止事件则退出）。
    - 如果某个进程已经在运行，则跳过并继续下一项。
    """
    global _seq_start_thread, _seq_start_stop_event
    try:
        for p in procs:
            if _seq_start_stop_event.is_set():
                break
            try:
                # 如果已经在运行，略过
                if p.proc and p.proc.poll() is None:
                    p.update_status()
                    continue
                p.start()
                p.update_status()
            except Exception as e:
                print(f"[sequential_start] 启动账号出错: {e}")
            # 等待 interval，但响应停止事件（每秒检查）
            waited = 0
            while waited < interval_seconds:
                if _seq_start_stop_event.is_set():
                    break
                time.sleep(1)
                waited += 1
    finally:
        # 线程完成或被中断时清理标记
        _seq_start_thread = None
        _seq_start_stop_event.clear()


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
    global procs, _seq_start_thread, _seq_start_stop_event

    # 顺序启动：在后台线程每隔 SEQ_START_INTERVAL_SECONDS 启动下一个账号
    def all_start():
        global _seq_start_thread, _seq_start_stop_event
        # 如果已有顺序启动线程在运行，不重复启动
        if _seq_start_thread and _seq_start_thread.is_alive():
            messagebox.showinfo("提示", "正在顺序启动账户，请稍候或先点击全部停止以终止本次顺序启动。")
            return
        # 清理任何旧的停止事件，启动新线程
        _seq_start_stop_event.clear()
        _seq_start_thread = threading.Thread(target=_sequential_start_worker, args=(SEQ_START_INTERVAL_SECONDS,), daemon=True)
        _seq_start_thread.start()

    # 全部停止：需要同时中断顺序启动线程（如果有），并调用每个进程的 stop（逻辑与单独 stop 一致）
    def all_stop():
        global _seq_start_thread, _seq_start_stop_event
        # 先设置停止事件以中断顺序启动（若在进行）
        _seq_start_stop_event.set()
        # 等待顺序启动线程短暂结束（非阻塞主线程太久）
        if _seq_start_thread and _seq_start_thread.is_alive():
            # 不长时间阻塞 GUI，做短等待
            _seq_start_thread.join(timeout=1.0)
        # 对所有进程执行 stop（与单个 stop 相同的接口）
        for p in procs:
            try:
                p.stop()
                p.update_status()
            except Exception as e:
                print(f"[all_stop] 停止账户出错: {e}")

    def all_refresh():
        [p.update_log() for p in procs]

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