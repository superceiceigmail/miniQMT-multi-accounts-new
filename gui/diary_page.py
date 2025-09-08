import os
import json
import re
from datetime import date, datetime, timedelta
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText
from tkinter import messagebox

# Tooltip实现（支持多行）
class ToolTip:
    def __init__(self, widget, text_func):
        self.widget = widget
        self.text_func = text_func
        self.tipwindow = None
        self.id = None
        self.widget.bind("<Motion>", self.on_motion)
        self.widget.bind("<Leave>", self.hidetip)
        self.last_rowcol = (None, None)
    def showtip(self, text, x, y):
        if self.tipwindow or not text:
            return
        self.tipwindow = tw = tb.Toplevel(self.widget)
        tw.wm_overrideredirect(1)
        tw.wm_geometry("+%d+%d" % (x + 20, y + 20))
        label = tb.Label(tw, text=text, justify=LEFT,
                         background="#ffffe0", relief="solid", borderwidth=1,
                         font=("微软雅黑", 10), anchor="w")
        label.pack(ipadx=1)
    def hidetip(self, event=None):
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None
        self.last_rowcol = (None, None)
    def on_motion(self, event):
        region = self.widget.identify("region", event.x, event.y)
        if region != "cell":
            self.hidetip()
            return
        rowid = self.widget.identify_row(event.y)
        colid = self.widget.identify_column(event.x)
        if self.last_rowcol == (rowid, colid):
            return
        self.last_rowcol = (rowid, colid)
        if rowid and colid:
            colnum = int(colid.replace("#", "")) - 1
            columns = self.widget["columns"]
            colname = columns[colnum]
            if colname not in ("content",):
                self.hidetip()
                return
            item = self.widget.item(rowid)
            values = item.get("values", [])
            if not values or colnum >= len(values):
                self.hidetip()
                return
            fulltext = self.text_func(rowid, colnum)
            if not fulltext:
                self.hidetip()
                return
            x = self.widget.winfo_pointerx()
            y = self.widget.winfo_pointery()
            self.hidetip()
            self.showtip(fulltext, x, y)
        else:
            self.hidetip()

# 统一数据文件目录
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)
DIARY_FILE = os.path.join(DATA_DIR, "diary.json")
REMIND_FILE = os.path.join(DATA_DIR, "remind.json")
TODO_FILE = os.path.join(DATA_DIR, "todo.json")

HONOR_CATEGORIES = ["交易","量化", "生活", "娱乐", "写歌", "锻炼"]
DIARY_PAGE_SIZE = 10

def get_plan_date_choices():
    today = date.today()
    week_days = ['一', '二', '三', '四', '五', '六', '日']
    choices = ["待定"]
    for i in range(0, 10):
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

def load_json_file(filename):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_json_file(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def make_summary(text, length=30):
    text = text.strip().replace('\r\n', '\n').replace('\r', '\n')
    first_line = text.split('\n', 1)[0]
    if len(first_line) > length:
        return first_line[:length] + "..."
    if len(text) > len(first_line):
        return first_line + "..."
    return first_line

class DiaryPage(tb.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.page = 1
        self.create_widgets()
        self.load_today_content()
        self.load_diary_page()
        self.update_today_remind()

    def create_widgets(self):
        main_frame = tb.Frame(self)
        main_frame.pack(fill=BOTH, expand=True, padx=10, pady=8)
        main_frame.pack_propagate(0)

        diary_entry_frame = tb.LabelFrame(main_frame, text="今日交易日记（结构化）", padding=(10, 8))
        diary_entry_frame.pack(side=LEFT, fill=Y, expand=False, padx=(0, 8))

        tb.Label(diary_entry_frame, text="功勋内容：").pack(anchor="w", pady=(2, 0))
        self.honor_content_text = ScrolledText(diary_entry_frame, height=3, width=40, font=("微软雅黑", 10))
        self.honor_content_text.pack(fill=X, padx=0, pady=(0,2))

        honor_attr_frame = tb.Frame(diary_entry_frame)
        honor_attr_frame.pack(fill=X, pady=2)
        self.honor_cat_var = tb.StringVar(value=HONOR_CATEGORIES[0])
        tb.Combobox(honor_attr_frame, textvariable=self.honor_cat_var, values=HONOR_CATEGORIES, width=8, state="readonly").pack(side=LEFT)
        self.honor_major_var = tb.BooleanVar()
        tb.Checkbutton(honor_attr_frame, text="重大", variable=self.honor_major_var).pack(side=LEFT, padx=2)
        self.honor_score_var = tb.StringVar()
        tb.Entry(honor_attr_frame, textvariable=self.honor_score_var, width=6).pack(side=LEFT, padx=2)
        self.honor_unit_var = tb.StringVar(value="小时")
        tb.Combobox(honor_attr_frame, textvariable=self.honor_unit_var, values=["小时", "天"], width=6, state="readonly").pack(side=LEFT, padx=2)
        tb.Label(honor_attr_frame, text="项目:").pack(side=LEFT, padx=(6, 0))
        self.honor_project_var = tb.StringVar()
        tb.Entry(honor_attr_frame, textvariable=self.honor_project_var, width=10).pack(side=LEFT, padx=2)
        tb.Label(honor_attr_frame, text="标签:").pack(side=LEFT, padx=(6, 0))
        self.honor_tags_var = tb.StringVar()
        tb.Entry(honor_attr_frame, textvariable=self.honor_tags_var, width=12).pack(side=LEFT, padx=2)
        tb.Button(honor_attr_frame, text="添加功勋", command=self.add_honor_row, bootstyle="success-outline").pack(side=LEFT, padx=4)
        tb.Button(honor_attr_frame, text="删除选中", command=self.del_selected_honor, bootstyle="danger-outline").pack(side=LEFT)

        honor_frame = tb.Frame(diary_entry_frame)
        honor_frame.pack(fill=X, pady=(2, 0))

        self.honor_tree = tb.Treeview(
            honor_frame,
            columns=("category", "content", "major", "score", "unit", "project", "tags"),
            show="headings",
            height=12
        )
        self.honor_tree.heading("category", text="分类")
        self.honor_tree.heading("content", text="功勋内容")
        self.honor_tree.heading("major", text="重大")
        self.honor_tree.heading("score", text="积分")
        self.honor_tree.heading("unit", text="单位")
        self.honor_tree.heading("project", text="项目")
        self.honor_tree.heading("tags", text="标签")
        self.honor_tree.column("category", width=60, anchor="center")
        self.honor_tree.column("content", width=185, anchor="w")
        self.honor_tree.column("major", width=44, anchor="center")
        self.honor_tree.column("score", width=56, anchor="center")
        self.honor_tree.column("unit", width=44, anchor="center")
        self.honor_tree.column("project", width=70, anchor="w")
        self.honor_tree.column("tags", width=80, anchor="w")
        self.honor_tree.pack(side=LEFT, fill=X, expand=True)

        tree_scroll = tb.Scrollbar(honor_frame, orient="vertical", command=self.honor_tree.yview)
        tree_scroll.pack(side=RIGHT, fill=Y)
        self.honor_tree.configure(yscrollcommand=tree_scroll.set)

        self.honor_tree.bind("<Double-1>", self.on_honor_tree_row_edit)

        def get_honor_fulltext(rowid, colnum):
            item = self.honor_tree.item(rowid)
            vals = item.get("values", [])
            if not vals: return ""
            if hasattr(self, "_honor_fulltext_map"):
                return self._honor_fulltext_map.get(rowid, "")
            return vals[1]
        ToolTip(self.honor_tree, get_honor_fulltext)

        plan_labelframe = tb.LabelFrame(diary_entry_frame, text="后续计划（可多条）", padding=(4, 4))
        plan_labelframe.pack(fill=X, pady=(10, 0))

        tb.Label(plan_labelframe, text="计划内容：").pack(anchor="w", pady=(2, 0))
        self.plan_content_text = ScrolledText(plan_labelframe, height=3, width=35, font=("微软雅黑", 10))
        self.plan_content_text.pack(fill=X, padx=0, pady=(0,2))
        plan_attr_frame = tb.Frame(plan_labelframe)
        plan_attr_frame.pack(fill=X, pady=2)
        self.plan_priority_var = tb.StringVar(value="3")
        tb.Combobox(plan_attr_frame, textvariable=self.plan_priority_var, values=["1", "2", "3", "4", "5"], width=4, state="readonly").pack(side=LEFT, padx=2)
        self.plan_date_choices = get_plan_date_choices()
        self.plan_date_var = tb.StringVar(value=self.plan_date_choices[0])
        self.plan_date_combo = tb.Combobox(plan_attr_frame, textvariable=self.plan_date_var, values=self.plan_date_choices, width=16, state="readonly")
        self.plan_date_combo.pack(side=LEFT, padx=2)
        self.plan_date_combo.bind("<<ComboboxSelected>>", self.on_plan_date_change)
        self.plan_time_choices = [""] + [f"{h:02d}:{m:02d}" for h in range(0, 24) for m in (0, 30)]
        self.plan_time_var = tb.StringVar(value="")
        self.plan_time_combo = tb.Combobox(plan_attr_frame, textvariable=self.plan_time_var, values=self.plan_time_choices, width=8, state="readonly")
        self.plan_time_combo.pack(side=LEFT, padx=2)
        tb.Button(plan_attr_frame, text="添加计划", command=self.add_plan_row, bootstyle="success-outline").pack(side=LEFT, padx=4)
        tb.Button(plan_attr_frame, text="删除选中", command=self.del_selected_plan, bootstyle="danger-outline").pack(side=LEFT)

        plan_frame = tb.Frame(plan_labelframe)
        plan_frame.pack(fill=X, pady=1)

        self.plan_tree = tb.Treeview(
            plan_frame,
            columns=("content", "priority", "date", "time"),
            show="headings",
            height=12
        )
        self.plan_tree.heading("content", text="计划内容")
        self.plan_tree.heading("priority", text="优先级")
        self.plan_tree.heading("date", text="开始日期")
        self.plan_tree.heading("time", text="开始时间")
        self.plan_tree.column("content", width=200, anchor="w")
        self.plan_tree.column("priority", width=54, anchor="center")
        self.plan_tree.column("date", width=120, anchor="center")
        self.plan_tree.column("time", width=70, anchor="center")
        self.plan_tree.pack(side=LEFT, fill=X, expand=True)

        plan_tree_scroll = tb.Scrollbar(plan_frame, orient="vertical", command=self.plan_tree.yview)
        plan_tree_scroll.pack(side=RIGHT, fill=Y)
        self.plan_tree.configure(yscrollcommand=plan_tree_scroll.set)

        self.plan_tree.bind("<Double-1>", self.on_plan_tree_row_edit)

        def get_plan_fulltext(rowid, colnum):
            item = self.plan_tree.item(rowid)
            vals = item.get("values", [])
            if not vals: return ""
            if hasattr(self, "_plan_fulltext_map"):
                return self._plan_fulltext_map.get(rowid, "")
            return vals[0]
        ToolTip(self.plan_tree, get_plan_fulltext)

        label3 = tb.Label(diary_entry_frame, text="要点和心得：")
        label3.pack(anchor="w", pady=(8, 0))
        self.rules_text = ScrolledText(diary_entry_frame, height=2, width=40, font=("Consolas", 10))
        self.rules_text.pack(fill=X, pady=2)

        self.today_remind_frame = tb.Frame(diary_entry_frame)
        self.today_remind_frame.pack(fill=X, pady=(4, 0))
        self.today_remind_label = tb.Label(self.today_remind_frame, font=("微软雅黑", 11, "bold"), foreground="#b22222")
        self.today_remind_label.pack(anchor="w", padx=0, pady=0)
        self.today_remind_items_frame = tb.Frame(self.today_remind_frame)
        self.today_remind_items_frame.pack(fill=X, padx=0, pady=0)

        self.followed_var = tb.BooleanVar(value=True)
        diary_check = tb.Checkbutton(diary_entry_frame, text="是否按照策略规划配置和执行", variable=self.followed_var)
        diary_check.pack(anchor="w", pady=2)
        diary_save_btn = tb.Button(diary_entry_frame, text="保存今日日记", command=self.save_today, bootstyle="primary-outline")
        diary_save_btn.pack(anchor="e", pady=4)

        self.encourage_label = tb.Label(diary_entry_frame, font=("微软雅黑", 11, "bold"), foreground="#1b9d55")
        self.encourage_label.pack(pady=4)

        diary_list_frame = tb.LabelFrame(main_frame, text="历史交易日记", padding=(10, 8))
        diary_list_frame.pack(side=RIGHT, fill=BOTH, expand=True)
        self.diary_list = ScrolledText(diary_list_frame, height=15, width=60, font=("Consolas", 10), state="disabled")
        self.diary_list.pack(fill=BOTH, expand=True, pady=2)
        nav_frame = tb.Frame(diary_list_frame)
        nav_frame.pack(fill=X)
        self.prev_btn = tb.Button(nav_frame, text="上一页", width=12, command=self.prev_page, bootstyle="info-outline")
        self.next_btn = tb.Button(nav_frame, text="下一页", width=12, command=self.next_page, bootstyle="info-outline")
        self.page_label = tb.Label(nav_frame)
        self.prev_btn.pack(side=LEFT, padx=2, pady=3)
        self.next_btn.pack(side=LEFT, padx=2, pady=3)
        self.page_label.pack(side=LEFT, padx=10)

        self.on_plan_date_change()

    def on_honor_tree_row_edit(self, event):
        item_id = self.honor_tree.identify_row(event.y)
        if not item_id:
            return
        vals = self.honor_tree.item(item_id, "values")
        if not vals:
            return
        self.honor_cat_var.set(vals[0])
        fulltext = self._honor_fulltext_map.get(item_id, vals[1])
        self.honor_content_text.delete("1.0", "end")
        self.honor_content_text.insert("1.0", fulltext)
        self.honor_major_var.set(vals[2] == "是")
        self.honor_score_var.set(vals[3])
        self.honor_unit_var.set(vals[4])
        self.honor_project_var.set(vals[5])
        self.honor_tags_var.set(vals[6])
        self.honor_tree.delete(item_id)
        self._honor_fulltext_map.pop(item_id, None)

    def on_plan_tree_row_edit(self, event):
        item_id = self.plan_tree.identify_row(event.y)
        if not item_id:
            return
        vals = self.plan_tree.item(item_id, "values")
        if not vals:
            return
        fulltext = self._plan_fulltext_map.get(item_id, vals[0])
        self.plan_content_text.delete("1.0", "end")
        self.plan_content_text.insert("1.0", fulltext)
        self.plan_priority_var.set(vals[1])
        self.plan_date_var.set(vals[2])
        self.plan_time_var.set(vals[3])
        self.on_plan_date_change()
        self.plan_tree.delete(item_id)
        self._plan_fulltext_map.pop(item_id, None)

    def on_plan_date_change(self, event=None):
        date_label = self.plan_date_var.get()
        if date_label == "待定":
            self.plan_time_var.set("")
            self.plan_time_combo.config(state="disabled")
        else:
            self.plan_time_combo.config(state="readonly")

    def add_honor_row(self):
        cat = self.honor_cat_var.get()
        content = self.honor_content_text.get("1.0", "end").strip()
        major = "是" if self.honor_major_var.get() else ""
        score = self.honor_score_var.get().strip()
        unit = self.honor_unit_var.get()
        project = self.honor_project_var.get().strip()
        tags = self.honor_tags_var.get().strip()
        if not content:
            messagebox.showwarning("提示", "请填写功勋内容")
            return
        try:
            float(score) if score else 0
        except ValueError:
            messagebox.showwarning("提示", "积分请输入数字")
            return
        summary = make_summary(content)
        iid = self.honor_tree.insert("", "end", values=(cat, summary, major, score, unit, project, tags))
        if not hasattr(self, "_honor_fulltext_map"):
            self._honor_fulltext_map = {}
        self._honor_fulltext_map[iid] = content
        self.honor_content_text.delete("1.0", "end")
        self.honor_major_var.set(False)
        self.honor_score_var.set("")
        self.honor_unit_var.set("小时")
        self.honor_project_var.set("")
        self.honor_tags_var.set("")

    def del_selected_honor(self):
        for item in self.honor_tree.selection():
            self.honor_tree.delete(item)
            if hasattr(self, "_honor_fulltext_map"):
                self._honor_fulltext_map.pop(item, None)

    def add_plan_row(self):
        content = self.plan_content_text.get("1.0", "end").strip()
        priority = self.plan_priority_var.get()
        date_label = self.plan_date_var.get()
        time_str = self.plan_time_var.get().strip()
        if not content:
            messagebox.showwarning("提示", "请填写计划内容")
            return
        if date_label == "待定" and time_str:
            messagebox.showwarning("提示", "开始日期为待定时，不能填写开始时间")
            return
        summary = make_summary(content)
        iid = self.plan_tree.insert("", "end", values=(summary, priority, date_label, time_str))
        if not hasattr(self, "_plan_fulltext_map"):
            self._plan_fulltext_map = {}
        self._plan_fulltext_map[iid] = content
        self.plan_content_text.delete("1.0", "end")
        self.plan_priority_var.set("3")
        self.plan_date_var.set(self.plan_date_choices[0])
        self.plan_time_var.set("")
        self.on_plan_date_change()

    def del_selected_plan(self):
        for item in self.plan_tree.selection():
            self.plan_tree.delete(item)
            if hasattr(self, "_plan_fulltext_map"):
                self._plan_fulltext_map.pop(item, None)

    def load_today_content(self):
        today_str = date.today().isoformat()
        diary_data = load_diary()
        rec = next((r for r in diary_data["records"] if r["date"] == today_str), None)
        self.honor_tree.delete(*self.honor_tree.get_children())
        self.plan_tree.delete(*self.plan_tree.get_children())
        self._honor_fulltext_map = {}
        self._plan_fulltext_map = {}
        if rec:
            honors = rec.get("honor", [])
            if isinstance(honors, str):
                honors = [{
                    "category": HONOR_CATEGORIES[0],
                    "content": honors,
                    "major": False,
                    "score": 0,
                    "unit": "小时",
                    "project": "",
                    "tags": ""
                }]
            for honor in honors:
                summary = make_summary(honor.get("content", ""))
                iid = self.honor_tree.insert("", "end", values=(
                    honor.get("category", HONOR_CATEGORIES[0]),
                    summary,
                    "是" if honor.get("major") else "",
                    honor.get("score", ""),
                    honor.get("unit", "小时"),
                    honor.get("project", ""),
                    honor.get("tags", "")
                ))
                self._honor_fulltext_map[iid] = honor.get("content", "")
            plans = rec.get("plan", [])
            if isinstance(plans, str):
                if plans:
                    summary = make_summary(plans)
                    iid = self.plan_tree.insert("", "end", values=(summary, "3", "待定", ""))
                    self._plan_fulltext_map[iid] = plans
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
                    summary = make_summary(plan.get("content", ""))
                    iid = self.plan_tree.insert("", "end", values=(
                        summary,
                        str(plan.get("priority", 3)),
                        date_label,
                        time_value
                    ))
                    self._plan_fulltext_map[iid] = plan.get("content", "")
            self.rules_text.delete("1.0", "end")
            self.rules_text.insert("end", rec.get("rules", ""))
            self.followed_var.set(rec.get("followed_plan", True))
        else:
            self.rules_text.delete("1.0", "end")
            self.followed_var.set(True)
        self.on_plan_date_change()

    def save_today(self):
        honors = []
        for row in self.honor_tree.get_children():
            cat, summary, major, score, unit, project, tags = self.honor_tree.item(row, "values")
            content = self._honor_fulltext_map.get(row, summary)
            honors.append({
                "category": cat,
                "content": content,
                "major": (major == "是"),
                "score": float(score) if score else 0,
                "unit": unit,
                "project": project,
                "tags": tags
            })
        plans = []
        for row in self.plan_tree.get_children():
            summary, priority, date_label, time_value = self.plan_tree.item(row, "values")
            content = self._plan_fulltext_map.get(row, summary)
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
        rules = self.rules_text.get("1.0", "end").strip()
        followed = self.followed_var.get()
        if not honors and not plans and not rules:
            messagebox.showwarning("提示", "请填写至少一项内容！")
            return
        self.save_plan_to_remind_and_todo(plans)
        add_diary_record(honors, plans, rules, followed)
        self.update_encourage()
        self.load_diary_page()
        self.update_today_remind()
        messagebox.showinfo("保存成功", "今日交易日记已保存！")

    def save_plan_to_remind_and_todo(self, plans):
        today = date.today().isoformat()
        old_remind = load_json_file(REMIND_FILE)
        old_todo = load_json_file(TODO_FILE)
        remind = [item for item in old_remind if item.get("created_date") != today]
        todo = [item for item in old_todo if item.get("created_date") != today]
        for plan in plans:
            plan_copy = plan.copy()
            plan_copy["created_date"] = today
            if plan.get("start_date"):
                plan_copy["status"] = plan_copy.get("status", "")
                remind.append(plan_copy)
            else:
                todo.append(plan_copy)
        save_json_file(REMIND_FILE, remind)
        save_json_file(TODO_FILE, todo)

    def update_encourage(self):
        days = get_continuous_days()
        if days > 0:
            msg = f"你已经按照策略规划连续配置和执行了 {days} 天，继续保持！"
        else:
            msg = "加油！从今天开始，养成良好的交易习惯！"
        self.encourage_label.config(text=msg)

    def update_today_remind(self):
        today = date.today().isoformat()
        for widget in self.today_remind_items_frame.winfo_children():
            widget.destroy()
        remind_list = []
        remind_data = []
        if os.path.exists(REMIND_FILE):
            with open(REMIND_FILE, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    remind_data = data
                    for idx, plan in enumerate(data):
                        if plan.get("created_date") == today and plan.get("start_date") == today and plan.get("status", "") != "已知悉":
                            time_str = plan.get("start_time", "")
                            content = plan.get("content", "")
                            item = {
                                "index": idx,
                                "text": f"{time_str + ' - ' if time_str else ''}{content}",
                            }
                            remind_list.append(item)
                except Exception:
                    pass
        if remind_list:
            self.today_remind_label.config(text="今日提醒：")
            for item in remind_list:
                row_frame = tb.Frame(self.today_remind_items_frame)
                row_frame.pack(fill=X, pady=1, anchor="w")
                label = tb.Label(row_frame, text=item["text"], font=("微软雅黑", 10), foreground="#b22222")
                label.pack(side=LEFT, padx=(0,8))
                btn = tb.Button(row_frame, text="知道了", width=7,
                                 command=lambda idx=item["index"]: self.acknowledge_remind(idx), bootstyle="success-outline")
                btn.pack(side=LEFT)
        else:
            self.today_remind_label.config(text="")

    def acknowledge_remind(self, idx):
        if os.path.exists(REMIND_FILE):
            with open(REMIND_FILE, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    if 0 <= idx < len(data):
                        data[idx]["status"] = "已知悉"
                        with open(REMIND_FILE, "w", encoding="utf-8") as wf:
                            json.dump(data, wf, ensure_ascii=False, indent=2)
                except Exception:
                    pass
        self.update_today_remind()

    def load_diary_page(self):
        records, total_pages = get_diary_page(self.page)
        self.diary_list.text.config(state="normal")
        self.diary_list.text.delete("1.0", "end")
        if not records:
            self.diary_list.text.insert("end", "暂无历史日记记录。\n")
        else:
            for rec in records:
                self.diary_list.text.insert("end", f'日期: {rec["date"]}\n')
                self.diary_list.text.insert("end", f'是否按策略执行: {"是" if rec.get("followed_plan", False) else "否"}\n')
                self.diary_list.text.insert("end", f'今日功勋:\n')
                honors = rec.get("honor", [])
                if isinstance(honors, str):
                    honors = [{
                        "category": HONOR_CATEGORIES[0],
                        "content": honors,
                        "major": False,
                        "score": 0,
                        "unit": "小时",
                        "project": "",
                        "tags": ""
                    }]
                if honors:
                    for idx, honor in enumerate(honors, 1):
                        content = honor.get("content", "")
                        self.diary_list.text.insert(
                            "end",
                            f'  {idx}. {content}\n'
                            f'      [{honor.get("category", "")}]'
                            f'{"[重大]" if honor.get("major") else ""} '
                            f'({honor.get("score", 0)}{honor.get("unit", "")})'
                            + (f' 项目:{honor.get("project","")}' if honor.get("project","") else "")
                            + (f' 标签:{honor.get("tags","")}' if honor.get("tags","") else "")
                            + "\n"
                        )
                else:
                    self.diary_list.text.insert("end", "  无\n")
                self.diary_list.text.insert("end", f'后续计划:\n')
                plans = rec.get("plan", [])
                if isinstance(plans, str):
                    if plans:
                        self.diary_list.text.insert("end", f'  1. {plans}\n')
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
                        content = plan.get("content", "")
                        if not plan.get("start_date"):
                            showtime = "待定"
                        elif not time_value:
                            showtime = date_label
                        else:
                            showtime = f"{date_label} {time_value}"
                        self.diary_list.text.insert(
                            "end",
                            f'  {idx}. {content}\n'
                            f'      优先级:{plan.get("priority", 3)}  开始:{showtime}\n'
                        )
                else:
                    self.diary_list.text.insert("end", "  无\n")
                self.diary_list.text.insert("end", f'要点和规则:\n{rec.get("rules", "")}\n')
                self.diary_list.text.insert("end", f'保存时间: {rec.get("timestamp", "")}\n')
                self.diary_list.text.insert("end", "----------------------------------------\n")
        self.diary_list.text.config(state="disabled")
        self.page_label.config(text=f"第 {self.page} / {max(total_pages, 1)} 页")
        self.update_encourage()
        self.prev_btn["state"] = "normal" if self.page > 1 else "disabled"
        self.next_btn["state"] = "normal" if self.page < total_pages else "disabled"
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
    root = tb.Window(themename="cosmo")
    root.title("交易日记")
    DiaryPage(root).pack(fill=BOTH, expand=True)
    root.mainloop()