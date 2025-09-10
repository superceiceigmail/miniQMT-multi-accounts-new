import ttkbootstrap as tb
from ttkbootstrap.constants import *
import tkinter as tk
from tkinter import messagebox
import json
import os

REMIND_FILE = "gui/data/remind.json"

def load_reminders():
    if not os.path.exists(REMIND_FILE):
        return []
    with open(REMIND_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_reminders(reminders):
    with open(REMIND_FILE, "w", encoding="utf-8") as f:
        json.dump(reminders, f, ensure_ascii=False, indent=2)

def check_due_reminders(reminders):
    from datetime import datetime, timedelta
    due = []
    now = datetime.now()
    for r in reminders:
        try:
            if r.get("status", "") == "已知悉":
                continue
            date_str = r.get("start_date") or r.get("created_date")
            if not date_str:
                continue
            r_date = datetime.strptime(date_str, "%Y-%m-%d")
            if r.get("start_time"):
                try:
                    h, m = [int(x) for x in r.get("start_time").split(":")[:2]]
                    r_date = r_date.replace(hour=h, minute=m)
                except Exception:
                    pass
            if (r_date.date() <= now.date()) or (now <= r_date <= now + timedelta(days=1)):
                due.append(r)
        except Exception:
            continue
    return due

class RemindPage(tb.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.reminders = []
        self.selected_index = None
        self.build_ui()
        self.refresh()

    def build_ui(self):
        columns = ("content", "priority", "start_date", "start_time", "status", "category", "project", "tags", "created_date")
        self.tree = tb.Treeview(self, columns=columns, show="headings", height=15)
        self.tree.heading("content", text="内容")
        self.tree.heading("priority", text="优先级")
        self.tree.heading("start_date", text="开始日期")
        self.tree.heading("start_time", text="开始时间")
        self.tree.heading("status", text="状态")
        self.tree.heading("category", text="分类")
        self.tree.heading("project", text="项目")
        self.tree.heading("tags", text="标签")
        self.tree.heading("created_date", text="创建日期")
        self.tree.column("content", width=180)
        self.tree.column("priority", width=60, anchor="center")
        self.tree.column("start_date", width=80, anchor="center")
        self.tree.column("start_time", width=70, anchor="center")
        self.tree.column("status", width=70, anchor="center")
        self.tree.column("category", width=60, anchor="center")
        self.tree.column("project", width=80, anchor="center")
        self.tree.column("tags", width=70, anchor="center")
        self.tree.column("created_date", width=80, anchor="center")
        self.tree.pack(fill=BOTH, expand=True, padx=8, pady=4)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Double-1>", self.on_double_click)

        entry_frame = tb.Frame(self)
        entry_frame.pack(fill=X, padx=8, pady=2)

        self.entry = tb.Entry(entry_frame, font=("Consolas", 11), width=16)
        self.entry.pack(side=LEFT, padx=2)

        self.priority_entry = tb.Entry(entry_frame, width=3)
        self.priority_entry.pack(side=LEFT, padx=2)
        self.priority_entry.insert(0, "3")

        self.start_date_entry = tb.Entry(entry_frame, width=8)
        self.start_date_entry.pack(side=LEFT, padx=2)

        self.start_time_entry = tb.Entry(entry_frame, width=6)
        self.start_time_entry.pack(side=LEFT, padx=2)

        self.status_entry = tb.Entry(entry_frame, width=8)
        self.status_entry.pack(side=LEFT, padx=2)

        self.category_entry = tb.Entry(entry_frame, width=8)
        self.category_entry.pack(side=LEFT, padx=2)
        self.category_entry.insert(0, "生活")

        self.project_entry = tb.Entry(entry_frame, width=10)
        self.project_entry.pack(side=LEFT, padx=2)

        self.tags_entry = tb.Entry(entry_frame, width=8)
        self.tags_entry.pack(side=LEFT, padx=2)

        tb.Label(entry_frame, text="内容").pack(side=LEFT, padx=2)
        tb.Label(entry_frame, text="优先级").pack(side=LEFT, padx=2)
        tb.Label(entry_frame, text="开始日").pack(side=LEFT, padx=2)
        tb.Label(entry_frame, text="时间").pack(side=LEFT, padx=2)
        tb.Label(entry_frame, text="状态").pack(side=LEFT, padx=2)
        tb.Label(entry_frame, text="分类").pack(side=LEFT, padx=2)
        tb.Label(entry_frame, text="项目").pack(side=LEFT, padx=2)
        tb.Label(entry_frame, text="标签").pack(side=LEFT, padx=2)

        tb.Button(entry_frame, text="添加", width=7, bootstyle="success", command=self.add_item).pack(side=LEFT, padx=2)
        tb.Button(entry_frame, text="修改", width=7, bootstyle="info", command=self.edit_item).pack(side=LEFT, padx=2)
        tb.Button(entry_frame, text="删除", width=7, bootstyle="danger", command=self.delete_item).pack(side=LEFT, padx=2)

    def refresh(self):
        # 每次操作都重新加载文件内容，防止脏数据覆盖
        self.reminders = load_reminders()
        from collections import Counter
        cat_counts = Counter(remind.get("category", "其他") for remind in self.reminders)
        def sort_key(remind):
            cat = remind.get("category", "其他")
            return (-cat_counts[cat], cat, -int(remind.get("priority", 99)))
        self.reminders.sort(key=sort_key)
        for item in self.tree.get_children():
            self.tree.delete(item)
        for idx, remind in enumerate(self.reminders):
            self.tree.insert("", "end", iid=str(idx), values=(
                remind.get("content", ""),
                remind.get("priority", ""),
                remind.get("start_date", ""),
                remind.get("start_time", ""),
                remind.get("status", ""),
                remind.get("category", ""),
                remind.get("project", ""),
                remind.get("tags", ""),
                remind.get("created_date", "")
            ))
        if self.selected_index is not None and 0 <= self.selected_index < len(self.reminders):
            self.tree.selection_set(str(self.selected_index))
            self.tree.focus(str(self.selected_index))
        self.entry.delete(0, tk.END)
        self.priority_entry.delete(0, tk.END)
        self.priority_entry.insert(0, "3")
        self.start_date_entry.delete(0, tk.END)
        self.start_time_entry.delete(0, tk.END)
        self.status_entry.delete(0, tk.END)
        self.category_entry.delete(0, tk.END)
        self.category_entry.insert(0, "生活")
        self.project_entry.delete(0, tk.END)
        self.tags_entry.delete(0, tk.END)

    def add_item(self):
        # 先reload，防止覆盖外部变更
        self.reminders = load_reminders()
        text = self.entry.get().strip()
        try:
            priority = int(self.priority_entry.get().strip())
        except Exception:
            priority = 99
        start_date = self.start_date_entry.get().strip()
        start_time = self.start_time_entry.get().strip()
        status = self.status_entry.get().strip()
        category = self.category_entry.get().strip() or "其他"
        project = self.project_entry.get().strip()
        tags = self.tags_entry.get().strip()
        from datetime import datetime
        created_date = datetime.now().strftime("%Y-%m-%d")
        if text:
            new_remind = {
                "content": text,
                "priority": priority,
                "start_date": start_date,
                "start_time": start_time,
                "created_date": created_date,
                "status": status,
                "category": category,
                "project": project,
                "tags": tags
            }
            self.reminders.append(new_remind)
            save_reminders(self.reminders)
            self.selected_index = len(self.reminders) - 1
            self.refresh()

    def delete_item(self):
        self.reminders = load_reminders()
        idx = self.selected_index
        if idx is not None and 0 <= idx < len(self.reminders):
            self.reminders.pop(idx)
            save_reminders(self.reminders)
            self.selected_index = None
            self.refresh()
        else:
            messagebox.showinfo("提示", "请先选中需要删除的提醒")

    def edit_item(self):
        self.reminders = load_reminders()
        idx = self.selected_index
        if idx is None or idx < 0 or idx >= len(self.reminders):
            messagebox.showinfo("提示", "请先选中需要修改的提醒")
            return
        text = self.entry.get().strip()
        try:
            priority = int(self.priority_entry.get().strip())
        except Exception:
            priority = 99
        start_date = self.start_date_entry.get().strip()
        start_time = self.start_time_entry.get().strip()
        status = self.status_entry.get().strip()
        category = self.category_entry.get().strip() or "其他"
        project = self.project_entry.get().strip()
        tags = self.tags_entry.get().strip()
        if text:
            self.reminders[idx]["content"] = text
            self.reminders[idx]["priority"] = priority
            self.reminders[idx]["start_date"] = start_date
            self.reminders[idx]["start_time"] = start_time
            self.reminders[idx]["status"] = status
            self.reminders[idx]["category"] = category
            self.reminders[idx]["project"] = project
            self.reminders[idx]["tags"] = tags
            save_reminders(self.reminders)
            self.refresh()
            self.selected_index = idx
            self.tree.selection_set(str(idx))
            self.tree.focus(str(idx))

    def on_select(self, event):
        sel = self.tree.selection()
        if sel:
            iid = sel[0]
            idx = int(iid)
            self.selected_index = idx
            remind = self.reminders[idx]
            self.entry.delete(0, tk.END)
            self.entry.insert(0, remind.get("content", ""))
            self.priority_entry.delete(0, tk.END)
            self.priority_entry.insert(0, str(remind.get("priority", "")))
            self.start_date_entry.delete(0, tk.END)
            self.start_date_entry.insert(0, remind.get("start_date", ""))
            self.start_time_entry.delete(0, tk.END)
            self.start_time_entry.insert(0, remind.get("start_time", ""))
            self.status_entry.delete(0, tk.END)
            self.status_entry.insert(0, remind.get("status", ""))
            self.category_entry.delete(0, tk.END)
            self.category_entry.insert(0, remind.get("category", ""))
            self.project_entry.delete(0, tk.END)
            self.project_entry.insert(0, remind.get("project", ""))
            self.tags_entry.delete(0, tk.END)
            self.tags_entry.insert(0, remind.get("tags", ""))

    def on_double_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region == "cell" or region == "tree":
            rowid = self.tree.identify_row(event.y)
            if rowid:
                self.tree.selection_set(rowid)
                self.tree.focus(rowid)
                self.selected_index = int(rowid)
                self.on_select(None)