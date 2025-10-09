import ttkbootstrap as tb
from ttkbootstrap.constants import *
from tkinter import ttk
import tkinter as tk
from tkinter import messagebox
import json
import os
from datetime import datetime

# 文件路径定义
# 注意：确保 'gui/data' 目录存在，否则 load/save 函数会报错
TODO_FILE = "gui/data/todo.json"
DIARY_FILE = "gui/data/diary.json"


# --- 数据加载与保存函数（保持不变）---

def load_todos():
    if not os.path.exists(TODO_FILE):
        # 确保目录存在
        os.makedirs(os.path.dirname(TODO_FILE), exist_ok=True)
        return []
    with open(TODO_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_todos(todos):
    os.makedirs(os.path.dirname(TODO_FILE), exist_ok=True)
    with open(TODO_FILE, "w", encoding="utf-8") as f:
        json.dump(todos, f, ensure_ascii=False, indent=2)


def load_diary():
    if not os.path.exists(DIARY_FILE):
        os.makedirs(os.path.dirname(DIARY_FILE), exist_ok=True)
        return {
            "continuous_days": 1,
            "records": [],
            "continuous_days_last_date": ""
        }
    with open(DIARY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_diary(diary):
    os.makedirs(os.path.dirname(DIARY_FILE), exist_ok=True)
    with open(DIARY_FILE, "w", encoding="utf-8") as f:
        json.dump(diary, f, ensure_ascii=False, indent=2)


# --- HonorDialog 类（保持不变）---

class HonorDialog(tb.Toplevel):
    def __init__(self, master, todo):
        super().__init__(master)
        self.result = None
        self.title("完成事项-填写honor信息")
        # 调整窗口大小以适应内容
        self.geometry("450x300")
        self.resizable(False, False)
        self.grab_set()

        # 使用 Frame 包装内容，方便布局
        content_frame = tb.Frame(self, padding=15)
        content_frame.pack(fill=BOTH, expand=True)

        # 内容、分类、标签、重大（只读）
        fields = [
            ("内容:", todo.get("content", ""), 220),
            ("分类:", todo.get("category", ""), None),
            ("标签:", todo.get("tags", ""), None),
            ("重大:", "是" if todo.get("major") else "否", None)
        ]

        for i, (label_text, value, wraplength) in enumerate(fields):
            tb.Label(content_frame, text=label_text, bootstyle="secondary").grid(row=i, column=0, sticky='e', pady=2,
                                                                                 padx=5)

            value_label = tb.Label(content_frame, text=value, anchor='w')
            if wraplength:
                value_label.config(wraplength=wraplength, justify='left')
            value_label.grid(row=i, column=1, sticky='w', pady=2, padx=5)

        # 可编辑字段
        edit_fields_start_row = len(fields)

        tb.Label(content_frame, text="积分:", bootstyle="primary").grid(row=edit_fields_start_row, column=0, sticky='e',
                                                                        pady=5, padx=5)
        self.score_entry = tb.Entry(content_frame, width=15)
        self.score_entry.insert(0, "1.0")
        self.score_entry.grid(row=edit_fields_start_row, column=1, sticky='w', pady=5, padx=5)

        tb.Label(content_frame, text="单位:", bootstyle="primary").grid(row=edit_fields_start_row + 1, column=0,
                                                                        sticky='e', pady=5, padx=5)
        self.unit_var = tk.StringVar(value="次")  # 更换默认单位为“次”更通用
        tb.Combobox(content_frame, textvariable=self.unit_var, values=["次", "天", "小时"], width=10,
                    state="readonly").grid(row=edit_fields_start_row + 1, column=1, sticky='w', pady=5, padx=5)

        tb.Label(content_frame, text="项目:", bootstyle="primary").grid(row=edit_fields_start_row + 2, column=0,
                                                                        sticky='e', pady=5, padx=5)
        self.project_entry = tb.Entry(content_frame, width=30)
        # 尝试使用 todo 的 category 作为默认项目
        self.project_entry.insert(0, todo.get("category", ""))
        self.project_entry.grid(row=edit_fields_start_row + 2, column=1, sticky='w', pady=5, padx=5)

        # 按钮
        button_frame = tb.Frame(self)
        button_frame.pack(pady=10)

        tb.Button(button_frame, text="确定", bootstyle="success", command=self.confirm).pack(side=LEFT, padx=15)
        tb.Button(button_frame, text="取消", bootstyle="secondary", command=self.cancel).pack(side=LEFT, padx=15)

    def confirm(self):
        try:
            score = float(self.score_entry.get() or "1.0")
        except Exception:
            messagebox.showerror("输入错误", "积分必须是数字。")
            return

        self.result = {
            "score": score,
            "unit": self.unit_var.get(),
            "project": self.project_entry.get(),
        }
        self.destroy()

    def cancel(self):
        self.result = None
        self.destroy()


# --- TodolistPage 类（主要修改部分）---

class TodolistPage(tb.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.todos = []
        self.selected_iid = None

        # --- 排序状态变量 ---
        # 默认排序：按优先级（降序，即数字小靠前），不使用原有复杂排序
        self.sort_column = "priority"
        self.sort_reverse = True  # False: 升序 (数字小在前)
        # -------------------

        self.build_ui()
        # 初始刷新，使用默认排序
        self.refresh()

    def build_ui(self):
        columns = ("content", "priority", "category", "tags", "major", "created_date")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=18)

        # 定义列标题和点击排序命令
        self.tree.heading("content", text="内容", command=lambda: self.sort_by_column("content"))
        self.tree.heading("priority", text="优先级", command=lambda: self.sort_by_column("priority"))
        self.tree.heading("category", text="分类", command=lambda: self.sort_by_column("category"))
        self.tree.heading("tags", text="标签", command=lambda: self.sort_by_column("tags"))
        self.tree.heading("major", text="重大", command=lambda: self.sort_by_column("major"))
        self.tree.heading("created_date", text="创建日期", command=lambda: self.sort_by_column("created_date"))

        # 定义列宽度和对齐
        self.tree.column("content", width=240, stretch=tk.YES)
        self.tree.column("priority", width=60, anchor="center")
        self.tree.column("category", width=60, anchor="center")
        self.tree.column("tags", width=80, anchor="center")
        self.tree.column("major", width=50, anchor="center")
        self.tree.column("created_date", width=100, anchor="center")

        self.tree.pack(fill=BOTH, expand=True, padx=8, pady=4)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Double-1>", self.on_double_click)

        # --- 输入和按钮部分 (保持不变) ---
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

        tb.Label(entry_frame, text="P").pack(side=LEFT, padx=2)
        tb.Label(entry_frame, text="C").pack(side=LEFT, padx=2)
        tb.Label(entry_frame, text="T").pack(side=LEFT, padx=2)

        tb.Button(entry_frame, text="添加", width=8, bootstyle="success", command=self.add_item).pack(side=LEFT, padx=3)
        tb.Button(entry_frame, text="修改", width=8, bootstyle="info", command=self.edit_item).pack(side=LEFT, padx=3)
        tb.Button(entry_frame, text="删除", width=8, bootstyle="danger", command=self.delete_item).pack(side=LEFT,
                                                                                                        padx=3)
        tb.Button(entry_frame, text="完成", width=8, bootstyle="primary", command=self.finish_item).pack(side=LEFT,
                                                                                                         padx=3)

    def sort_by_column(self, col):
        """处理表头点击事件，设置排序字段和升降序，并刷新列表。"""

        # 如果点击同一列，则切换升降序
        if self.sort_column == col:
            self.sort_reverse = not self.sort_reverse
        # 如果点击不同列，则切换到新列，并设置默认升降序
        else:
            self.sort_column = col
            # 默认：优先级、创建日期：降序（小的/新的在前）
            if col in ["priority", "created_date"]:
                self.sort_reverse = False  # False表示升序（数字/日期 小的在前）
            elif col == "major":
                self.sort_reverse = True  # True表示降序（True在前）
            else:
                self.sort_reverse = False  # 文本默认升序

        self.refresh()

    def refresh(self):
        self.todos = load_todos()

        # --- 排序逻辑：使用当前的 sort_column 和 sort_reverse ---
        col = self.sort_column
        reverse = self.sort_reverse

        def get_sort_key(todo):
            val = todo.get(col, '')
            if col == 'priority':
                # 尝试转为 int，失败则给一个很大的值（使其排在后面）
                try:
                    return int(val)
                except Exception:
                    return 999
            elif col == 'major':
                # 布尔值排序
                return bool(val)
            elif col == 'created_date':
                # 日期字符串排序
                return val
            elif isinstance(val, str):
                # 文本排序，转小写以进行不区分大小写的排序
                return val.lower()
            else:
                return val

        # 排序
        # 注意：这里的 reverse 逻辑是 Tkinter Treeview 约定俗成的，
        # 通常 `reverse=False` 对应 A-Z, 1-9, 新日期在前（即升序）。
        # 对于优先级，我们希望数字小（高优先级）在前，所以默认 `reverse=False` 是对的。
        self.todos.sort(key=get_sort_key, reverse=reverse)
        # -----------------------------------------------------

        # 清空Treeview
        for item in self.tree.get_children():
            self.tree.delete(item)

        # 优先级色阶配置 (保持不变)
        def get_priority_tag(prio):
            try:
                prio = int(prio)
            except Exception:
                prio = 99
            if prio <= 1:
                return "prio1"
            elif prio == 2:
                return "prio2"
            elif prio == 3:
                return "prio3"
            elif prio == 4:
                return "prio4"
            else:
                return "prio5"

        self.tree.tag_configure("prio1", background="#f5f5f5")  # 灰
        self.tree.tag_configure("prio2", background="#e0f7fa")  # 青
        self.tree.tag_configure("prio3", background="#eaffea")  # 绿
        self.tree.tag_configure("prio4", background="#fffbe6")  # 黄
        self.tree.tag_configure("prio5", background="#ffeaea")  # 红

        for idx, todo in enumerate(self.todos):
            tag = get_priority_tag(todo.get('priority', 99))
            self.tree.insert(
                "", "end", iid=str(idx),
                values=(
                    todo.get('content', ''),
                    todo.get('priority', ''),
                    todo.get('category', ''),
                    todo.get('tags', ''),
                    "是" if todo.get('major') else "",
                    todo.get('created_date', '')
                ),
                tags=(tag,)
            )

        # 重新选中之前的项目（如果它还存在）
        if self.selected_iid is not None and self.selected_iid in self.tree.get_children():
            self.tree.selection_set(self.selected_iid)
            self.tree.focus(self.selected_iid)
            # 如果重新排序导致 iid 变化，则需要重新设置 iid
            self.selected_iid = self.tree.selection()[0]
        else:
            self.selected_iid = None

        # 清空输入框
        self.entry.delete(0, tk.END)
        self.priority_entry.delete(0, tk.END)
        self.priority_entry.insert(0, "3")
        self.category_entry.delete(0, tk.END)
        self.category_entry.insert(0, "交易")
        self.major_var.set(False)
        self.tags_entry.delete(0, tk.END)

    # --- CRUD 方法 (保持不变) ---
    def add_item(self):
        text = self.entry.get().strip()
        try:
            priority = int(self.priority_entry.get().strip())
        except Exception:
            priority = 99
        category = self.category_entry.get().strip() or "其他"
        major = self.major_var.get()
        tags = self.tags_entry.get().strip()
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
            # 添加后重新排序并刷新
            self.refresh()
            # 尝试选中新添加的项目
            # 由于排序，新项目不一定在最后，这里暂时不处理选中状态
            # self.selected_iid = str(len(self.todos) - 1)
        else:
            messagebox.showinfo("提示", "内容不能为空")

    def delete_item(self):
        iid = self.selected_iid
        if iid is not None and iid.isdigit() and int(iid) < len(self.todos):
            # 获取当前选中的待办事项的索引
            current_index = int(iid)

            # 检查索引是否有效（因为 refresh 是基于当前 list 长度设置 iid 的）
            if 0 <= current_index < len(self.todos):
                self.todos.pop(current_index)
                save_todos(self.todos)
                self.selected_iid = None
                self.refresh()
            else:
                messagebox.showinfo("错误", "列表数据与选中项不匹配，请重新选中。")
                self.selected_iid = None
                self.tree.selection_remove(self.tree.selection())

        else:
            messagebox.showinfo("提示", "请先选中需要删除的事项")

    def edit_item(self):
        iid = self.selected_iid
        if iid is None or not iid.isdigit() or int(iid) >= len(self.todos):
            messagebox.showinfo("提示", "请先选中需要修改的事项")
            return
        idx = int(iid)

        # 确保索引在有效范围内
        if not (0 <= idx < len(self.todos)):
            messagebox.showinfo("错误", "列表数据与选中项不匹配，请重新选中。")
            self.selected_iid = None
            self.tree.selection_remove(self.tree.selection())
            return

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

            # 修改后保持选中状态，重新刷新（会根据新的值进行排序）
            self.refresh()
        else:
            messagebox.showinfo("提示", "内容不能为空")

    def finish_item(self):
        iid = self.selected_iid
        if iid is None or not iid.isdigit() or int(iid) >= len(self.todos):
            messagebox.showinfo("提示", "请先选中需要完成的事项")
            return

        idx = int(iid)

        if not (0 <= idx < len(self.todos)):
            messagebox.showinfo("错误", "列表数据与选中项不匹配，请重新选中。")
            self.selected_iid = None
            self.tree.selection_remove(self.tree.selection())
            return

        # 1. 执行一次“修改”逻辑，确保数据是最新的
        text = self.entry.get().strip()
        if not text:
            messagebox.showinfo("提示", "内容不能为空")
            return

        try:
            priority = int(self.priority_entry.get().strip())
        except Exception:
            priority = 99
        category = self.category_entry.get().strip() or "其他"
        major = self.major_var.get()
        tags = self.tags_entry.get().strip()

        self.todos[idx]["content"] = text
        self.todos[idx]["priority"] = priority
        self.todos[idx]["category"] = category
        self.todos[idx]["major"] = major
        self.todos[idx]["tags"] = tags
        save_todos(self.todos)

        # 2. 弹出 honor 填写框
        todo = self.todos[idx]
        dialog = HonorDialog(self, todo)
        self.wait_window(dialog)

        if dialog.result is None:
            return  # 用户取消

        # 3. 记录 honor 并删除待办
        honor = {
            "category": todo.get("category", ""),
            "content": todo.get("content", ""),
            "major": bool(todo.get("major", False)),
            "score": dialog.result.get("score", 1.0),
            "unit": dialog.result.get("unit", "天"),
            "project": dialog.result.get("project", ""),
            "tags": todo.get("tags", "")
        }

        now_date = datetime.now().strftime("%Y-%m-%d")
        diary = load_diary()
        found = False

        # 查找或创建今日记录
        for record in diary.get("records", []):
            if record.get("date") == now_date:
                record.setdefault("honor", []).append(honor)
                found = True
                break
        if not found:
            diary.setdefault("records", []).append({
                "date": now_date,
                "honor": [honor],
                "plan": [],
                "rules": "",
                "followed_plan": False,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            })

        save_diary(diary)

        # 从 todos 中删除该事项
        self.todos.pop(idx)
        save_todos(self.todos)
        self.selected_iid = None
        self.refresh()
        messagebox.showinfo("提示", "已完成并加入honor！")

    def on_select(self, event):
        sel = self.tree.selection()
        if sel:
            iid = sel[0]
            self.selected_iid = iid
            idx = int(iid)

            # 检查索引是否有效
            if 0 <= idx < len(self.todos):
                todo = self.todos[idx]

                # 更新输入框内容
                self.entry.delete(0, tk.END)
                self.entry.insert(0, todo.get("content", ""))
                self.priority_entry.delete(0, tk.END)
                self.priority_entry.insert(0, str(todo.get("priority", "")))
                self.category_entry.delete(0, tk.END)
                self.category_entry.insert(0, todo.get("category", ""))
                self.major_var.set(bool(todo.get("major", False)))
                self.tags_entry.delete(0, tk.END)
                self.tags_entry.insert(0, todo.get("tags", ""))
            else:
                # 选中项无效，重置状态
                self.selected_iid = None
                self.tree.selection_remove(iid)

    def on_double_click(self, event):
        # 双击操作：选定并填充输入框
        region = self.tree.identify("region", event.x, event.y)
        if region == "cell" or region == "tree":
            rowid = self.tree.identify_row(event.y)
            if rowid:
                self.tree.selection_set(rowid)
                self.tree.focus(rowid)
                self.selected_iid = rowid
                self.on_select(None)
                # 也可以直接调用 self.edit_item() 或 self.finish_item()
                # 根据双击的期望行为来定。这里选择只选中并填充。


# --- 主应用框架（新增）---

class TodoApp(tb.Window):
    def __init__(self):
        super().__init__(themename="superhero")  # 使用 ttkbootstrap 主题
        self.title("Todo List & Honor Tracker")
        self.geometry("880x550")
        self.resizable(False, False)

        # 创建并显示待办事项页面
        self.todolist_page = TodolistPage(self)
        self.todolist_page.pack(fill=BOTH, expand=True)


if __name__ == "__main__":
    # 在运行前创建所需目录
    os.makedirs("gui/data", exist_ok=True)

    app = TodoApp()
    app.mainloop()