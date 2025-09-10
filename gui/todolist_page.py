import ttkbootstrap as tb
from ttkbootstrap.constants import *
from tkinter import ttk
import tkinter as tk
from tkinter import messagebox
import json
import os

TODO_FILE = "gui/data/todo.json"

def load_todos():
    if not os.path.exists(TODO_FILE):
        return []
    with open(TODO_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_todos(todos):
    with open(TODO_FILE, "w", encoding="utf-8") as f:
        json.dump(todos, f, ensure_ascii=False, indent=2)

class TodolistPage(tb.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.todos = []
        self.selected_iid = None
        self.build_ui()
        self.refresh()

    def build_ui(self):
        columns = ("content", "priority", "category", "tags", "major", "created_date")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=18)
        self.tree.heading("content", text="内容")
        self.tree.heading("priority", text="优先级")
        self.tree.heading("category", text="分类")
        self.tree.heading("tags", text="标签")
        self.tree.heading("major", text="重大")
        self.tree.heading("created_date", text="创建日期")
        self.tree.column("content", width=240)
        self.tree.column("priority", width=60, anchor="center")
        self.tree.column("category", width=60, anchor="center")
        self.tree.column("tags", width=80, anchor="center")
        self.tree.column("major", width=50, anchor="center")
        self.tree.column("created_date", width=100, anchor="center")
        self.tree.pack(fill=BOTH, expand=True, padx=8, pady=4)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Double-1>", self.on_double_click)

        entry_frame = tb.Frame(self)
        entry_frame.pack(fill=X, padx=8, pady=2)

        self.entry = tb.Entry(entry_frame, font=("Consolas", 11))
        self.entry.pack(side=LEFT, fill=X, expand=True, padx=2)

        self.priority_entry = tb.Entry(entry_frame, width=4)
        self.priority_entry.pack(side=LEFT, padx=3)
        self.priority_entry.insert(0, "3")

        self.category_entry = tb.Entry(entry_frame, width=8)
        self.category_entry.pack(side=LEFT, padx=3)
        self.category_entry.insert(0, "交易")

        self.major_var = tk.BooleanVar()
        tb.Checkbutton(entry_frame, text="重大", variable=self.major_var).pack(side=LEFT, padx=3)

        self.tags_entry = tb.Entry(entry_frame, width=12)
        self.tags_entry.pack(side=LEFT, padx=3)
        self.tags_entry.insert(0, "")

        tb.Label(entry_frame, text="优先级").pack(side=LEFT, padx=2)
        tb.Label(entry_frame, text="类别").pack(side=LEFT, padx=2)
        tb.Label(entry_frame, text="标签").pack(side=LEFT, padx=2)

        tb.Button(entry_frame, text="添加", width=8, bootstyle="success", command=self.add_item).pack(side=LEFT, padx=3)
        tb.Button(entry_frame, text="修改", width=8, bootstyle="info", command=self.edit_item).pack(side=LEFT, padx=3)
        tb.Button(entry_frame, text="删除", width=8, bootstyle="danger", command=self.delete_item).pack(side=LEFT, padx=3)

    def refresh(self):
        self.todos = load_todos()
        # 统计每个分类的数量
        from collections import Counter
        cat_counts = Counter(todo.get("category", "其他") for todo in self.todos)

        # 构造排序key
        def sort_key(todo):
            cat = todo.get("category", "其他")
            # 分类数降序，分类名升序，优先级降序
            return (-cat_counts[cat], cat, -int(todo.get("priority", 99)))

        self.todos.sort(key=sort_key)
        # 清空Treeview
        for item in self.tree.get_children():
            self.tree.delete(item)
        for idx, todo in enumerate(self.todos):
            self.tree.insert("", "end", iid=str(idx), values=(
                todo.get('content', ''),
                todo.get('priority', ''),
                todo.get('category', ''),
                todo.get('tags', ''),
                "是" if todo.get('major') else "",
                todo.get('created_date', '')
            ))
        if self.selected_iid is not None and self.selected_iid in self.tree.get_children():
            self.tree.selection_set(self.selected_iid)
            self.tree.focus(self.selected_iid)
        self.entry.delete(0, tk.END)
        self.priority_entry.delete(0, tk.END)
        self.priority_entry.insert(0, "3")
        self.category_entry.delete(0, tk.END)
        self.category_entry.insert(0, "交易")
        self.major_var.set(False)
        self.tags_entry.delete(0, tk.END)

    def add_item(self):
        text = self.entry.get().strip()
        try:
            priority = int(self.priority_entry.get().strip())
        except Exception:
            priority = 99
        category = self.category_entry.get().strip() or "其他"
        major = self.major_var.get()
        tags = self.tags_entry.get().strip()
        from datetime import datetime
        created_date = datetime.now().strftime("%Y-%m-%d")
        if text:
            new_todo = {
                "content": text,
                "priority": priority,
                "start_date": "",
                "start_time": "",
                "created_date": created_date,
                "category": category,
                "project": "",
                "tags": tags,
                "major": major
            }
            self.todos.append(new_todo)
            save_todos(self.todos)
            self.selected_iid = str(len(self.todos) - 1)
            self.refresh()

    def delete_item(self):
        iid = self.selected_iid
        if iid is not None and iid.isdigit() and int(iid) < len(self.todos):
            self.todos.pop(int(iid))
            save_todos(self.todos)
            self.selected_iid = None
            self.refresh()
        else:
            messagebox.showinfo("提示", "请先选中需要删除的事项")

    def edit_item(self):
        iid = self.selected_iid
        if iid is None or not iid.isdigit() or int(iid) >= len(self.todos):
            messagebox.showinfo("提示", "请先选中需要修改的事项")
            return
        idx = int(iid)
        text = self.entry.get().strip()
        try:
            priority = int(self.priority_entry.get().strip())
        except Exception:
            priority = 99
        category = self.category_entry.get().strip() or "其他"
        major = self.major_var.get()
        tags = self.tags_entry.get().strip()
        if text:
            self.todos[idx]["content"] = text
            self.todos[idx]["priority"] = priority
            self.todos[idx]["category"] = category
            self.todos[idx]["major"] = major
            self.todos[idx]["tags"] = tags
            save_todos(self.todos)
            self.selected_iid = iid
            self.refresh()

    def on_select(self, event):
        sel = self.tree.selection()
        if sel:
            iid = sel[0]
            self.selected_iid = iid
            idx = int(iid)
            todo = self.todos[idx]
            self.entry.delete(0, tk.END)
            self.entry.insert(0, todo.get("content", ""))
            self.priority_entry.delete(0, tk.END)
            self.priority_entry.insert(0, str(todo.get("priority", "")))
            self.category_entry.delete(0, tk.END)
            self.category_entry.insert(0, todo.get("category", ""))
            self.major_var.set(bool(todo.get("major", False)))
            self.tags_entry.delete(0, tk.END)
            self.tags_entry.insert(0, todo.get("tags", ""))

    def on_double_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region == "cell" or region == "tree":
            rowid = self.tree.identify_row(event.y)
            if rowid:
                self.tree.selection_set(rowid)
                self.tree.focus(rowid)
                self.selected_iid = rowid
                self.on_select(None)