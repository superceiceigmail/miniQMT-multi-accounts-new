import os
import json
import re
from datetime import date, datetime, timedelta
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# 统一数据文件目录
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)
DIARY_FILE = os.path.join(DATA_DIR, "diary.json")
REMIND_FILE = os.path.join(DATA_DIR, "remind.json")
TODO_FILE = os.path.join(DATA_DIR, "todo.json")

HONOR_CATEGORIES = ["交易", "生活", "娱乐", "写歌", "锻炼"]
DIARY_PAGE_SIZE = 10

def get_plan_date_choices():
    today = date.today()
    week_days = ['一', '二', '三', '四', '五', '六', '日']
    choices = ["待定"]
    for i in range(0, 10):  # 今天+后9天
        d = today + timedelta(days=i)
        if i == 0:
            label = f"今天({d.month:02d}月{d.day:02d}日)"
        else:
            weekday = d.weekday()
            days_to_sunday = 6 - today.weekday()
            if i <= days_to_sunday:
                label = f"本周{week_days[weekday]}({d.month:02d}月{d.day:02d}日)"
            else:
                label = f"下周{week_days[weekday]}({d.month:02d}月{d.day:02d}日)"
        choices.append(label)
    return choices

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

def add_diary_record(honors, plans, rules, followed_plan):
    today_str = date.today().isoformat()
    diary_data = load_diary()
    records = diary_data["records"]
    already = False
    for rec in records:
        if rec["date"] == today_str:
            rec["honor"] = honors
            rec["plan"] = plans
            rec["rules"] = rules
            rec["followed_plan"] = followed_plan
            rec["timestamp"] = datetime.now().isoformat(timespec="seconds")
            already = True
            break
    if not already:
        records.append({
            "date": today_str,
            "honor": honors,
            "plan": plans,
            "rules": rules,
            "followed_plan": followed_plan,
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
        self.update_today_remind()

    def create_widgets(self):
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)
        main_frame.pack_propagate(0)

        # 左侧输入区
        diary_entry_frame = ttk.LabelFrame(main_frame, text="今日交易日记（结构化）", padding=(10, 8))
        diary_entry_frame.pack(side=tk.LEFT, fill=tk.Y, expand=False, padx=(0, 8))

        # 功勋内容输入框（单独一行）
        ttk.Label(diary_entry_frame, text="功勋内容：").pack(anchor="w", pady=(2, 0))
        self.honor_content_text = scrolledtext.ScrolledText(diary_entry_frame, height=3, width=40, font=("微软雅黑", 10))
        self.honor_content_text.pack(fill=tk.X, padx=0, pady=(0,2))
        # 分类/重大/积分/单位等属性区（单独一行）
        honor_attr_frame = ttk.Frame(diary_entry_frame)
        honor_attr_frame.pack(fill=tk.X, pady=2)
        self.honor_cat_var = tk.StringVar(value=HONOR_CATEGORIES[0])
        ttk.Combobox(honor_attr_frame, textvariable=self.honor_cat_var, values=HONOR_CATEGORIES, width=8, state="readonly").pack(side=tk.LEFT)
        self.honor_major_var = tk.BooleanVar()
        ttk.Checkbutton(honor_attr_frame, text="重大", variable=self.honor_major_var).pack(side=tk.LEFT, padx=2)
        self.honor_score_var = tk.StringVar()
        ttk.Entry(honor_attr_frame, textvariable=self.honor_score_var, width=6).pack(side=tk.LEFT, padx=2)
        self.honor_unit_var = tk.StringVar(value="小时")
        ttk.Combobox(honor_attr_frame, textvariable=self.honor_unit_var, values=["小时", "天"], width=6, state="readonly").pack(side=tk.LEFT, padx=2)
        ttk.Button(honor_attr_frame, text="添加功勋", command=self.add_honor_row).pack(side=tk.LEFT, padx=4)
        ttk.Button(honor_attr_frame, text="删除选中", command=self.del_selected_honor).pack(side=tk.LEFT)

        honor_frame = ttk.Frame(diary_entry_frame)
        honor_frame.pack(fill=tk.X, pady=(2, 0))

        self.honor_tree = ttk.Treeview(
            honor_frame,
            columns=("category", "content", "major", "score", "unit"),
            show="headings",
            height=4
        )
        self.honor_tree.heading("category", text="分类")
        self.honor_tree.heading("content", text="功勋内容")
        self.honor_tree.heading("major", text="重大")
        self.honor_tree.heading("score", text="积分")
        self.honor_tree.heading("unit", text="单位")
        self.honor_tree.column("category", width=60, anchor="center")
        self.honor_tree.column("content", width=280, anchor="w")
        self.honor_tree.column("major", width=44, anchor="center")
        self.honor_tree.column("score", width=56, anchor="center")
        self.honor_tree.column("unit", width=44, anchor="center")
        self.honor_tree.pack(side=tk.LEFT, fill=tk.X, expand=True)

        tree_scroll = ttk.Scrollbar(honor_frame, orient="vertical", command=self.honor_tree.yview)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.honor_tree.configure(yscrollcommand=tree_scroll.set)

        plan_labelframe = ttk.LabelFrame(diary_entry_frame, text="后续计划（可多条）", padding=(4, 4))
        plan_labelframe.pack(fill=tk.X, pady=(10, 0))

        # 计划内容输入框（单独一行）
        ttk.Label(plan_labelframe, text="计划内容：").pack(anchor="w", pady=(2, 0))
        self.plan_content_text = scrolledtext.ScrolledText(plan_labelframe, height=3, width=35, font=("微软雅黑", 10))
        self.plan_content_text.pack(fill=tk.X, padx=0, pady=(0,2))
        # 优先级/日期/时间等属性区（单独一行）
        plan_attr_frame = ttk.Frame(plan_labelframe)
        plan_attr_frame.pack(fill=tk.X, pady=2)
        self.plan_priority_var = tk.StringVar(value="3")
        ttk.Combobox(plan_attr_frame, textvariable=self.plan_priority_var, values=["1", "2", "3", "4", "5"], width=4, state="readonly").pack(side=tk.LEFT, padx=2)
        self.plan_date_choices = get_plan_date_choices()
        self.plan_date_var = tk.StringVar(value=self.plan_date_choices[0])
        self.plan_date_combo = ttk.Combobox(plan_attr_frame, textvariable=self.plan_date_var, values=self.plan_date_choices, width=16, state="readonly")
        self.plan_date_combo.pack(side=tk.LEFT, padx=2)
        self.plan_date_combo.bind("<<ComboboxSelected>>", self.on_plan_date_change)
        self.plan_time_choices = [""] + [f"{h:02d}:{m:02d}" for h in range(0, 24) for m in (0, 30)]
        self.plan_time_var = tk.StringVar(value="")
        self.plan_time_combo = ttk.Combobox(plan_attr_frame, textvariable=self.plan_time_var, values=self.plan_time_choices, width=8, state="readonly")
        self.plan_time_combo.pack(side=tk.LEFT, padx=2)
        ttk.Button(plan_attr_frame, text="添加计划", command=self.add_plan_row).pack(side=tk.LEFT, padx=4)
        ttk.Button(plan_attr_frame, text="删除选中", command=self.del_selected_plan).pack(side=tk.LEFT)

        plan_frame = ttk.Frame(plan_labelframe)
        plan_frame.pack(fill=tk.X, pady=1)

        self.plan_tree = ttk.Treeview(
            plan_frame,
            columns=("content", "priority", "date", "time"),
            show="headings",
            height=4
        )
        self.plan_tree.heading("content", text="计划内容")
        self.plan_tree.heading("priority", text="优先级")
        self.plan_tree.heading("date", text="开始日期")
        self.plan_tree.heading("time", text="开始时间")
        self.plan_tree.column("content", width=200, anchor="w")
        self.plan_tree.column("priority", width=54, anchor="center")
        self.plan_tree.column("date", width=120, anchor="center")
        self.plan_tree.column("time", width=70, anchor="center")
        self.plan_tree.pack(side=tk.LEFT, fill=tk.X, expand=True)

        plan_tree_scroll = ttk.Scrollbar(plan_frame, orient="vertical", command=self.plan_tree.yview)
        plan_tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.plan_tree.configure(yscrollcommand=plan_tree_scroll.set)

        label3 = ttk.Label(diary_entry_frame, text="要点和心得：")
        label3.pack(anchor="w", pady=(8, 0))
        self.rules_text = scrolledtext.ScrolledText(diary_entry_frame, height=2, width=40, font=("Consolas", 10),
                                                    background="#f7f7fa")
        self.rules_text.pack(fill=tk.X, pady=2)

        # 今日提醒（放在要点和心得下面，更显眼）
        self.today_remind_frame = ttk.Frame(diary_entry_frame)
        self.today_remind_frame.pack(fill=tk.X, pady=(4, 0))
        self.today_remind_label = ttk.Label(self.today_remind_frame, font=("微软雅黑", 11, "bold"), foreground="#b22222")
        self.today_remind_label.pack(anchor="w", padx=0, pady=0)
        self.today_remind_listbox = tk.Listbox(self.today_remind_frame, height=3, font=("微软雅黑", 10), fg="#b22222", borderwidth=0, highlightthickness=0)
        self.today_remind_listbox.pack(fill=tk.X, padx=0, pady=0)

        self.followed_var = tk.BooleanVar(value=True)
        diary_check = ttk.Checkbutton(diary_entry_frame, text="是否按照策略规划配置和执行", variable=self.followed_var)
        diary_check.pack(anchor="w", pady=2)
        diary_save_btn = ttk.Button(diary_entry_frame, text="保存今日日记", command=self.save_today)
        diary_save_btn.pack(anchor="e", pady=4)

        self.encourage_label = ttk.Label(diary_entry_frame, font=("微软雅黑", 11, "bold"), foreground="#1b9d55")
        self.encourage_label.pack(pady=4)

        diary_list_frame = ttk.LabelFrame(main_frame, text="历史交易日记", padding=(10, 8))
        diary_list_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        self.diary_list = scrolledtext.ScrolledText(diary_list_frame, height=15, width=60, font=("Consolas", 10),
                                                    background="#f8faff", state="disabled")
        self.diary_list.pack(fill=tk.BOTH, expand=True, pady=2)
        nav_frame = ttk.Frame(diary_list_frame)
        nav_frame.pack(fill=tk.X)
        self.prev_btn = ttk.Button(nav_frame, text="上一页", width=12, command=self.prev_page)
        self.next_btn = ttk.Button(nav_frame, text="下一页", width=12, command=self.next_page)
        self.page_label = ttk.Label(nav_frame)
        self.prev_btn.pack(side=tk.LEFT, padx=2, pady=3)
        self.next_btn.pack(side=tk.LEFT, padx=2, pady=3)
        self.page_label.pack(side=tk.LEFT, padx=10)

        # 初始禁用时间选择框（如果初始为待定）
        self.on_plan_date_change()

    def on_plan_date_change(self, event=None):
        date_label = self.plan_date_var.get()
        if date_label == "待定":
            self.plan_time_var.set("")
            self.plan_time_combo.config(state="disabled")
        else:
            self.plan_time_combo.config(state="readonly")

    def add_honor_row(self):
        cat = self.honor_cat_var.get()
        content = self.honor_content_text.get("1.0", tk.END).strip()
        major = "是" if self.honor_major_var.get() else ""
        score = self.honor_score_var.get().strip()
        unit = self.honor_unit_var.get()
        if not content:
            messagebox.showwarning("提示", "请填写功勋内容")
            return
        try:
            float(score) if score else 0
        except ValueError:
            messagebox.showwarning("提示", "积分请输入数字")
            return
        self.honor_tree.insert("", tk.END, values=(cat, content, major, score, unit))
        self.honor_content_text.delete("1.0", tk.END)
        self.honor_major_var.set(False)
        self.honor_score_var.set("")
        self.honor_unit_var.set("小时")

    def del_selected_honor(self):
        for item in self.honor_tree.selection():
            self.honor_tree.delete(item)

    def add_plan_row(self):
        content = self.plan_content_text.get("1.0", tk.END).strip()
        priority = self.plan_priority_var.get()
        date_label = self.plan_date_var.get()
        time_str = self.plan_time_var.get().strip()
        if not content:
            messagebox.showwarning("提示", "请填写计划内容")
            return
        # 禁止待定日期时填写时间
        if date_label == "待定" and time_str:
            messagebox.showwarning("提示", "开始日期为待定时，不能填写开始时间")
            return
        self.plan_tree.insert("", tk.END, values=(content, priority, date_label, time_str))
        self.plan_content_text.delete("1.0", tk.END)
        self.plan_priority_var.set("3")
        self.plan_date_var.set(self.plan_date_choices[0])
        self.plan_time_var.set("")
        self.on_plan_date_change()  # 保持时间输入框状态同步

    def del_selected_plan(self):
        for item in self.plan_tree.selection():
            self.plan_tree.delete(item)

    def load_today_content(self):
        today_str = date.today().isoformat()
        diary_data = load_diary()
        rec = next((r for r in diary_data["records"] if r["date"] == today_str), None)
        self.honor_tree.delete(*self.honor_tree.get_children())
        self.plan_tree.delete(*self.plan_tree.get_children())
        if rec:
            honors = rec.get("honor", [])
            if isinstance(honors, str):
                honors = [{
                    "category": HONOR_CATEGORIES[0],
                    "content": honors,
                    "major": False,
                    "score": 0,
                    "unit": "小时"
                }]
            for honor in honors:
                self.honor_tree.insert("", tk.END, values=(
                    honor.get("category", HONOR_CATEGORIES[0]),
                    honor.get("content", ""),
                    "是" if honor.get("major") else "",
                    honor.get("score", ""),
                    honor.get("unit", "小时"),
                ))
            plans = rec.get("plan", [])
            if isinstance(plans, str):
                if plans:
                    self.plan_tree.insert("", tk.END, values=(plans, "3", "待定", ""))
            elif isinstance(plans, list):
                for plan in plans:
                    date_label = "待定"
                    if plan.get("start_date"):
                        try:
                            d = datetime.strptime(plan.get("start_date"), "%Y-%m-%d").date()
                            today = date.today()
                            delta = (d - today).days
                            week_days = ['一', '二', '三', '四', '五', '六', '日']
                            weekday = d.weekday()
                            days_to_sunday = 6 - today.weekday()
                            if delta == 0:
                                date_label = f"今天({d.month:02d}月{d.day:02d}日)"
                            elif delta > 0 and delta <= days_to_sunday:
                                date_label = f"本周{week_days[weekday]}({d.month:02d}月{d.day:02d}日)"
                            else:
                                date_label = f"下周{week_days[weekday]}({d.month:02d}月{d.day:02d}日)"
                        except:
                            date_label = plan.get("start_date", "待定")
                    time_value = plan.get("start_time", "")
                    self.plan_tree.insert("", tk.END, values=(
                        plan.get("content", ""),
                        str(plan.get("priority", 3)),
                        date_label,
                        time_value
                    ))
            self.rules_text.delete(1.0, tk.END)
            self.rules_text.insert(tk.END, rec.get("rules", ""))
            self.followed_var.set(rec.get("followed_plan", True))
        else:
            self.rules_text.delete(1.0, tk.END)
            self.followed_var.set(True)
        self.on_plan_date_change()

    def save_today(self):
        honors = []
        for row in self.honor_tree.get_children():
            cat, content, major, score, unit = self.honor_tree.item(row, "values")
            honors.append({
                "category": cat,
                "content": content,
                "major": (major == "是"),
                "score": float(score) if score else 0,
                "unit": unit
            })
        plans = []
        for row in self.plan_tree.get_children():
            content, priority, date_label, time_value = self.plan_tree.item(row, "values")
            if date_label == "待定":
                date_value = ""
            else:
                m = re.search(r"\((\d+)月(\d+)日\)", date_label)
                if m:
                    month = int(m.group(1))
                    day = int(m.group(2))
                    year = date.today().year
                    date_value = f"{year}-{month:02d}-{day:02d}"
                else:
                    date_value = ""
            plans.append({
                "content": content,
                "priority": int(priority),
                "start_date": date_value,
                "start_time": time_value
            })
        rules = self.rules_text.get(1.0, tk.END).strip()
        followed = self.followed_var.get()
        if not honors and not plans and not rules:
            messagebox.showwarning("提示", "请填写至少一项内容！")
            return
        add_diary_record(honors, plans, rules, followed)
        self.save_plan_to_remind_and_todo(plans)
        self.update_encourage()
        self.load_diary_page()
        self.update_today_remind()
        messagebox.showinfo("保存成功", "今日交易日记已保存！")

    def save_plan_to_remind_and_todo(self, plans):
        remind = []
        todo = []
        for plan in plans:
            if plan.get("start_date"):
                remind.append(plan)
            else:
                todo.append(plan)
        def save_json(filename, data):
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        save_json(REMIND_FILE, remind)
        save_json(TODO_FILE, todo)

    def update_encourage(self):
        days = get_continuous_days()
        if days > 0:
            msg = f"你已经按照策略规划连续配置和执行了 {days} 天，继续保持！"
        else:
            msg = "加油！从今天开始，养成良好的交易习惯！"
        self.encourage_label.config(text=msg)

    def update_today_remind(self):
        today = date.today().isoformat()
        remind_list = []
        if os.path.exists(REMIND_FILE):
            with open(REMIND_FILE, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    for plan in data:
                        if plan.get("start_date") == today:
                            time_str = plan.get("start_time", "")
                            content = plan.get("content", "")
                            if time_str:
                                remind_list.append(f"{time_str} - {content}")
                            else:
                                remind_list.append(f"{content}")
                except Exception:
                    pass
        self.today_remind_listbox.delete(0, tk.END)
        if remind_list:
            self.today_remind_label.config(text="今日提醒：")
            for item in remind_list:
                self.today_remind_listbox.insert(tk.END, item)
        else:
            self.today_remind_label.config(text="")
            self.today_remind_listbox.delete(0, tk.END)

    def load_diary_page(self):
        records, total_pages = get_diary_page(self.page)
        self.diary_list.config(state="normal")
        self.diary_list.delete(1.0, tk.END)
        if not records:
            self.diary_list.insert(tk.END, "暂无历史日记记录。\n")
        else:
            for rec in records:
                self.diary_list.insert(tk.END, f'日期: {rec["date"]}\n')
                self.diary_list.insert(tk.END, f'是否按策略执行: {"是" if rec.get("followed_plan", False) else "否"}\n')
                self.diary_list.insert(tk.END, f'今日功勋:\n')
                honors = rec.get("honor", [])
                if isinstance(honors, str):
                    honors = [{
                        "category": HONOR_CATEGORIES[0],
                        "content": honors,
                        "major": False,
                        "score": 0,
                        "unit": "小时"
                    }]
                if honors:
                    for idx, honor in enumerate(honors, 1):
                        self.diary_list.insert(
                            tk.END,
                            f'  {idx}. {honor.get("content", "")}\n'
                            f'      [{honor.get("category", "")}]'
                            f'{"[重大]" if honor.get("major") else ""} '
                            f'({honor.get("score", 0)}{honor.get("unit", "")})\n'
                        )
                else:
                    self.diary_list.insert(tk.END, "  无\n")
                self.diary_list.insert(tk.END, f'后续计划:\n')
                plans = rec.get("plan", [])
                if isinstance(plans, str):
                    if plans:
                        self.diary_list.insert(tk.END, f'  1. {plans}\n')
                elif isinstance(plans, list):
                    for idx, plan in enumerate(plans, 1):
                        if not plan.get("start_date"):
                            date_label = "待定"
                        else:
                            try:
                                d = datetime.strptime(plan.get("start_date"), "%Y-%m-%d").date()
                                today = date.today()
                                delta = (d - today).days
                                week_days = ['一', '二', '三', '四', '五', '六', '日']
                                weekday = d.weekday()
                                days_to_sunday = 6 - today.weekday()
                                if delta == 0:
                                    date_label = f"今天({d.month:02d}月{d.day:02d}日)"
                                elif delta > 0 and delta <= days_to_sunday:
                                    date_label = f"本周{week_days[weekday]}({d.month:02d}月{d.day:02d}日)"
                                else:
                                    date_label = f"下周{week_days[weekday]}({d.month:02d}月{d.day:02d}日)"
                            except:
                                date_label = plan.get("start_date", "待定")
                        time_value = plan.get("start_time", "")
                        if not plan.get("start_date"):
                            showtime = "待定"
                        elif not time_value:
                            showtime = date_label
                        else:
                            showtime = f"{date_label} {time_value}"
                        self.diary_list.insert(
                            tk.END,
                            f'  {idx}. {plan.get("content", "")}\n'
                            f'      优先级:{plan.get("priority", 3)}  开始:{showtime}\n'
                        )
                else:
                    self.diary_list.insert(tk.END, "  无\n")
                self.diary_list.insert(tk.END, f'要点和规则:\n{rec.get("rules", "")}\n')
                self.diary_list.insert(tk.END, f'保存时间: {rec.get("timestamp", "")}\n')
                self.diary_list.insert(tk.END, "----------------------------------------\n")
        self.diary_list.config(state="disabled")
        self.page_label.config(text=f"第 {self.page} / {max(total_pages, 1)} 页")
        self.update_encourage()
        self.prev_btn["state"] = tk.NORMAL if self.page > 1 else tk.DISABLED
        self.next_btn["state"] = tk.NORMAL if self.page < total_pages else tk.DISABLED
        self.update_today_remind()

    def prev_page(self):
        if self.page > 1:
            self.page -= 1
            self.load_diary_page()

    def next_page(self):
        _, total_pages = get_diary_page(self.page)
        if self.page < total_pages:
            self.page += 1
            self.load_diary_page()

if __name__ == "__main__":
    root = tk.Tk()
    root.title("交易日记")
    DiaryPage(root).pack(fill=tk.BOTH, expand=True)
    root.mainloop()