import os
import json
from datetime import date, datetime, timedelta
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# 分类常量
HONOR_CATEGORIES = ["交易", "量化","生活", "娱乐", "写歌", "锻炼"]
DIARY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "diary.json")
DIARY_PAGE_SIZE = 10


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


def add_diary_record(honors, plan, rules, followed_plan):
    today_str = date.today().isoformat()
    diary_data = load_diary()
    records = diary_data["records"]
    already = False
    for rec in records:
        if rec["date"] == today_str:
            rec["honor"] = honors
            rec["plan"] = plan
            rec["rules"] = rules
            rec["followed_plan"] = followed_plan
            rec["timestamp"] = datetime.now().isoformat(timespec="seconds")
            already = True
            break
    if not already:
        records.append({
            "date": today_str,
            "honor": honors,
            "plan": plan,
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

    def create_widgets(self):
        # 主框架，左右分栏
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)
        main_frame.pack_propagate(0)

        # 左侧输入区
        diary_entry_frame = ttk.LabelFrame(main_frame, text="今日交易日记（结构化）", padding=(10, 8))
        diary_entry_frame.pack(side=tk.LEFT, fill=tk.Y, expand=False, padx=(0, 8))
        # 今日功勋 多条输入
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

        # 新增功勋输入区
        input_frame = ttk.Frame(diary_entry_frame)
        input_frame.pack(fill=tk.X, pady=2)

        self.honor_cat_var = tk.StringVar(value=HONOR_CATEGORIES[0])
        ttk.Combobox(input_frame, textvariable=self.honor_cat_var, values=HONOR_CATEGORIES, width=8,
                     state="readonly").pack(side=tk.LEFT)
        self.honor_content_var = tk.StringVar()
        ttk.Entry(input_frame, textvariable=self.honor_content_var, width=32).pack(side=tk.LEFT, padx=2)
        self.honor_major_var = tk.BooleanVar()
        ttk.Checkbutton(input_frame, text="重大", variable=self.honor_major_var).pack(side=tk.LEFT, padx=2)
        self.honor_score_var = tk.StringVar()
        ttk.Entry(input_frame, textvariable=self.honor_score_var, width=6).pack(side=tk.LEFT, padx=2)
        self.honor_unit_var = tk.StringVar(value="小时")
        ttk.Combobox(input_frame, textvariable=self.honor_unit_var, values=["小时", "天"], width=6,
                     state="readonly").pack(side=tk.LEFT, padx=2)
        ttk.Button(input_frame, text="添加功勋", command=self.add_honor_row).pack(side=tk.LEFT, padx=4)
        ttk.Button(input_frame, text="删除选中", command=self.del_selected_honor).pack(side=tk.LEFT)

        # 计划和规则等
        label2 = ttk.Label(diary_entry_frame, text="后续计划：")
        label2.pack(anchor="w", pady=(8, 0))
        self.plan_text = scrolledtext.ScrolledText(diary_entry_frame, height=3, width=40, font=("Consolas", 10),
                                                   background="#f7f7fa")
        self.plan_text.pack(fill=tk.X, pady=2)

        label3 = ttk.Label(diary_entry_frame, text="要点和规则：")
        label3.pack(anchor="w", pady=(2, 0))
        self.rules_text = scrolledtext.ScrolledText(diary_entry_frame, height=2, width=40, font=("Consolas", 10),
                                                    background="#f7f7fa")
        self.rules_text.pack(fill=tk.X, pady=2)

        self.followed_var = tk.BooleanVar(value=True)
        diary_check = ttk.Checkbutton(diary_entry_frame, text="是否按照策略规划配置和执行", variable=self.followed_var)
        diary_check.pack(anchor="w", pady=2)
        diary_save_btn = ttk.Button(diary_entry_frame, text="保存今日日记", command=self.save_today)
        diary_save_btn.pack(anchor="e", pady=4)

        self.encourage_label = ttk.Label(diary_entry_frame, font=("微软雅黑", 11, "bold"), foreground="#1b9d55")
        self.encourage_label.pack(pady=4)

        # 右侧历史区
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

    def add_honor_row(self):
        cat = self.honor_cat_var.get()
        content = self.honor_content_var.get().strip()
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
        self.honor_content_var.set("")
        self.honor_major_var.set(False)
        self.honor_score_var.set("")
        self.honor_unit_var.set("小时")

    def del_selected_honor(self):
        for item in self.honor_tree.selection():
            self.honor_tree.delete(item)

    def load_today_content(self):
        today_str = date.today().isoformat()
        diary_data = load_diary()
        rec = next((r for r in diary_data["records"] if r["date"] == today_str), None)
        self.honor_tree.delete(*self.honor_tree.get_children())
        if rec:
            honors = rec.get("honor", [])
            # 兼容旧格式
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
            self.plan_text.delete(1.0, tk.END)
            self.plan_text.insert(tk.END, rec.get("plan", ""))
            self.rules_text.delete(1.0, tk.END)
            self.rules_text.insert(tk.END, rec.get("rules", ""))
            self.followed_var.set(rec.get("followed_plan", True))
        else:
            self.plan_text.delete(1.0, tk.END)
            self.rules_text.delete(1.0, tk.END)
            self.followed_var.set(True)

    def save_today(self):
        # 获取所有功勋条目
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
        plan = self.plan_text.get(1.0, tk.END).strip()
        rules = self.rules_text.get(1.0, tk.END).strip()
        followed = self.followed_var.get()
        if not honors and not plan and not rules:
            messagebox.showwarning("提示", "请填写至少一项内容！")
            return
        add_diary_record(honors, plan, rules, followed)
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
                self.diary_list.insert(tk.END, f'日期: {rec["date"]}\n')
                self.diary_list.insert(tk.END, f'是否按策略执行: {"是" if rec.get("followed_plan", False) else "否"}\n')
                self.diary_list.insert(tk.END, f'今日功勋:\n')
                honors = rec.get("honor", [])
                # 兼容旧格式
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
                self.diary_list.insert(tk.END, f'后续计划:\n{rec.get("plan", "")}\n')
                self.diary_list.insert(tk.END, f'要点和规则:\n{rec.get("rules", "")}\n')
                self.diary_list.insert(tk.END, f'保存时间: {rec.get("timestamp", "")}\n')
                self.diary_list.insert(tk.END, "----------------------------------------\n")
        self.diary_list.config(state="disabled")
        self.page_label.config(text=f"第 {self.page} / {max(total_pages, 1)} 页")
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


if __name__ == "__main__":
    root = tk.Tk()
    root.title("交易日记")
    DiaryPage(root).pack(fill=tk.BOTH, expand=True)
    root.mainloop()