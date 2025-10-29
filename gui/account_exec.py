import os
import subprocess
import threading
import time
import signal
import platform
import re
import uuid
import psutil
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText
from tkinter import messagebox, Toplevel, BOTH, X, LEFT, RIGHT
import webbrowser
import json
from decimal import Decimal

# New: try import reconcile_ui to reuse save/viz helpers
try:
    from gui import reconcile_ui as ru
except Exception:
    ru = None

# 新增：调用 yunfei 的对账接口（网络）和本地对账函数（文件比对）
try:
    from yunfei_ball.yunfei_reconcile import reconcile_account
    from yunfei_ball.yunfei_login import login, BASE_URL
except Exception:
    reconcile_account = None
    login = None
    BASE_URL = "https://www.ycyflh.com"

# 尝试导入本地的 reconcile_report / reconcile_ui（优先使用）
try:
    from gui.reconcile_report import generate_reconcile_report
except Exception:
    generate_reconcile_report = None

try:
    from gui.reconcile_ui import reconcile_for_account as reconcile_for_account_local
except Exception:
    reconcile_for_account_local = None

MAIN_SCRIPT = "main.py"  # 注意：可根据实际后端文件调整路径
ENV_TAG_KEY = "MINIQMT_MANAGED_ACCOUNT"  # 旧的环境标记（account）
ENV_UI_ID = "MINIQMT_UI_ID"  # 新增：GUI 给子进程的唯一 id

class AccountProcess:
    """
    AccountProcess 中 self.account 现在存放 account_id（字符串），以保证所有系统调用/环境变量/命令行参数都使用资金账号 ID 而不是显示名。
    """
    def __init__(self, account, config, widgets):
        # account here should be the account_id (ID string)
        self.account = account
        self.config = config
        self.proc = None
        self._started_with_group = False
        self.log_buffer = []
        self.log_thread = None
        self.running = False
        self.widgets = widgets  # dict: {status, log_text}
        self._stop_lock = threading.Lock()
        self.ui_id = None  # 每次 start() 时生成并传递

    def start(self):
        print(f"[AccountProcess] 启动账户参数: {self.account}")
        if self.proc and self.proc.poll() is None:
            print("[AccountProcess] 进程已在运行，忽略 start")
            return
        log_path = self.config["log_file"]
        log_dir = os.path.dirname(log_path)
        os.makedirs(log_dir, exist_ok=True)
        open(log_path, "w").close()

        # 生成唯一 ui_id（account + 时间 + uuid）
        uid = uuid.uuid4().hex[:8]
        ts = int(time.time())
        self.ui_id = f"{self.account}-{ts}-{uid}"

        # 传入环境变量标记，便于后代识别（使用 account_id）
        env = os.environ.copy()
        env[ENV_TAG_KEY] = str(self.account)
        env[ENV_UI_ID] = self.ui_id

        creationflags = 0
        start_new_session = False
        if platform.system() == "Windows":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            self._started_with_group = True
        else:
            start_new_session = True
            self._started_with_group = True

        # 把 ui_id 也放到命令行参数，main.py / helpers.parse_args 已支持 --ui-id
        cmd = ["python", MAIN_SCRIPT, "-a", self.account, "--ui-id", self.ui_id]

        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                encoding="utf-8",
                creationflags=creationflags,
                start_new_session=start_new_session,
                env=env
            )
        except TypeError:
            # 兼容某些环境（若传入参数导致 TypeError），回退到简单启动（仍传 env）
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                encoding="utf-8",
                env=env
            )
            self._started_with_group = False

        self.running = True
        self.log_thread = threading.Thread(target=self._read_log, daemon=True)
        self.log_thread.start()
        self.update_status()
        print(f"[AccountProcess] 已启动 pid={self.proc.pid}, ui_id={self.ui_id}")

    def stop(self):
        """
        非阻塞 stop：立即返回并在后台完成真正的杀进程工作。
        通过 ui_id 优先定位进程，作为精确匹配手段。
        """
        print(f"[AccountProcess] 请求停止账户: {self.account}, ui_id={self.ui_id}")
        if not self.proc and not self.ui_id:
            print("[AccountProcess] 无进程/ID，直接更新状态")
            self.running = False
            self.update_status()
            return

        if not self._stop_lock.acquire(blocking=False):
            print("[AccountProcess] stop 已在进行中，忽略重复调用")
            return

        # 立即让 UI 显示停止中
        self.running = False
        self.update_status()
        t = threading.Thread(target=self._do_stop, daemon=True)
        t.start()

    def _do_stop(self):
        """
        多阶段终止尝试，优先使用 ui_id（通过 cmdline 或 environ）来定位进程，然后递归终止。
        """
        try:
            target_ui = self.ui_id
            # 先收集 candidate pids 当作精确匹配目标
            candidates = set()

            # 如果 self.proc 存在并仍在运行，先把它加入候选
            if self.proc and self.proc.poll() is None:
                candidates.add(self.proc.pid)

            # 1) 尝试按 ui_id 在系统进程中匹配（cmdline 或环境变量）
            if target_ui:
                for p in psutil.process_iter(['pid', 'cmdline', 'name']):
                    try:
                        info = p.info
                        pid = info.get('pid')
                        cmdline = info.get('cmdline') or []
                        cmd_str = " ".join(cmdline)
                        if target_ui in cmd_str:
                            candidates.add(pid)
                            print(f"[AccountProcess._do_stop] cmdline 匹配 ui_id -> pid={pid}")
                            continue
                        # 尝试读 environ（不一定有权限）
                        try:
                            penv = p.environ()
                            if penv.get(ENV_UI_ID) == target_ui:
                                candidates.add(pid)
                                print(f"[AccountProcess._do_stop] environ 匹配 ui_id -> pid={pid}")
                                continue
                        except Exception:
                            pass
                    except Exception:
                        continue

            # 2) 如果没有匹配到任何候选，但存在 self.proc，则回退使用原有策略（按进程树/组）
            if not candidates and self.proc:
                candidates.add(self.proc.pid)

            # 3) 对 candidates 做逐个递归清理（先按组/会话，再按 psutil children）
            for pid in list(candidates):
                try:
                    print(f"[AccountProcess._do_stop] 清理候选 pid={pid}")
                    # 尝试组级终止（如果我们是用 start_new_session/CREATE_NEW_PROCESS_GROUP 启动）
                    try:
                        if self._started_with_group:
                            if platform.system() == "Windows":
                                try:
                                    p = psutil.Process(pid)
                                    proc_obj = p
                                    try:
                                        proc_obj.send_signal(signal.CTRL_BREAK_EVENT)
                                        print(f"[AccountProcess._do_stop] 发送 CTRL_BREAK_EVENT 给 pid={pid}")
                                    except Exception:
                                        pass
                                except Exception:
                                    pass
                            else:
                                try:
                                    pgid = os.getpgid(pid)
                                    os.killpg(pgid, signal.SIGTERM)
                                    print(f"[AccountProcess._do_stop] killpg SIGTERM pgid={pgid}")
                                except Exception:
                                    pass
                            try:
                                psutil.Process(pid).wait(timeout=4)
                                print(f"[AccountProcess._do_stop] pid={pid} 已退出 (组信号)")
                                continue
                            except Exception:
                                pass
                    except Exception:
                        pass

                    # 递归 children
                    try:
                        parent = psutil.Process(pid)
                        children = parent.children(recursive=True)
                        for c in children:
                            try:
                                c.terminate()
                            except Exception:
                                pass
                        gone, alive = psutil.wait_procs(children, timeout=4)
                        for a in alive:
                            try:
                                a.kill()
                            except Exception:
                                pass
                        # 终止 parent
                        try:
                            parent.terminate()
                            try:
                                parent.wait(timeout=4)
                            except Exception:
                                parent.kill()
                        except Exception:
                            pass
                    except psutil.NoSuchProcess:
                        pass
                    except Exception as e:
                        print(f"[AccountProcess._do_stop] 递归终止失败 pid={pid}: {e}")
                        pass

                except Exception as e:
                    print(f"[AccountProcess._do_stop] 清理候选 pid 异常: {e}")

            # 4) 全局兜底：再做一次基于 ui_id 的全系统扫描并强杀（防止 reparent）
            if target_ui:
                to_kill = []
                for p in psutil.process_iter(['pid', 'cmdline']):
                    try:
                        pid = p.info.get('pid')
                        cmdline = p.info.get('cmdline') or []
                        if target_ui in " ".join(cmdline):
                            try:
                                print(f"[AccountProcess._do_stop] 兜底匹配并终止 pid={pid}")
                                p.terminate()
                                to_kill.append(p)
                            except Exception:
                                pass
                    except Exception:
                        continue
                if to_kill:
                    gone, alive = psutil.wait_procs(to_kill, timeout=4)
                    for p in alive:
                        try:
                            p.kill()
                        except Exception:
                            pass

            # 5) 关闭 stdout，清理状态
            try:
                if self.proc and getattr(self.proc, 'stdout', None):
                    try:
                        self.proc.stdout.close()
                    except Exception:
                        pass
            except Exception:
                pass

            self.proc = None
            print(f"[AccountProcess._do_stop] 停止完成 account={self.account}, ui_id={self.ui_id}")

        finally:
            self._stop_lock.release()
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
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                while True:
                    if not self.proc:
                        break
                    stdout = getattr(self.proc, "stdout", None)
                    if not stdout:
                        break
                    line = stdout.readline()
                    if not line:
                        if self.proc.poll() is not None:
                            break
                        time.sleep(0.1)
                        continue
                    f.write(line)
                    f.flush()
                    self.log_buffer.append(line)
                    if len(self.log_buffer) > 1000:
                        self.log_buffer = self.log_buffer[-1000:]
                    try:
                        self.widgets["log_text"].after(0, self.update_log)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[AccountProcess._read_log] 异常: {e}")
        finally:
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
        log = self.get_log(500)
        try:
            self.widgets["log_text"].delete(1.0, "end")
            self.widgets["log_text"].insert("end", log)
            self.widgets["log_text"].see("end")
        except Exception:
            pass

    def update_status(self):
        try:
            self.widgets["status"].config(text=self.status())
        except Exception:
            pass

def _make_serializable(obj):
    # 递归把 Decimal -> float，其他不可序列化对象尽量转成 str
    if isinstance(obj, Decimal):
        try:
            return float(obj)
        except Exception:
            return str(obj)
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_serializable(i) for i in obj]
    if isinstance(obj, tuple):
        return tuple(_make_serializable(i) for i in obj)
    # fallback for objects with __dict__
    try:
        if hasattr(obj, '__dict__'):
            return _make_serializable(obj.__dict__)
    except Exception:
        pass
    return obj

def _show_reconcile_dialog(parent, result, account_id):
    dlg = Toplevel(parent)
    dlg.title("对账结果")
    dlg.geometry("900x700")
    dlg.transient(parent)

    fetched_at = result.get('fetched_at', '') or result.get('fetched_at_iso', '')
    warnings = result.get('warnings', []) or ( [result.get('warning')] if result.get('warning') else [] )
    batches = result.get('batches', {}) or ( { "1": result.get('items', []) } if result.get('items') is not None else {} )

    header = tb.Label(dlg, text=f"爬取时间: {fetched_at}    批次数: {len(batches)}", font=("微软雅黑", 11, "bold"))
    header.pack(anchor="w", padx=10, pady=(8,4))

    if warnings:
        warn_label = tb.Label(dlg, text="警告: " + "; ".join([str(w) for w in warnings]), foreground="red")
        warn_label.pack(anchor="w", padx=10, pady=(0,6))

    txt = ScrolledText(dlg, height=30, wrap='none', font=("Consolas", 10))
    txt.pack(fill=BOTH, expand=True, padx=10, pady=6)
    try:
        # Ensure the underlying text widget is writable before inserting
        try:
            txt.configure(state="normal")
        except Exception:
            # Some ScrolledText implementations expose inner text as .text or .widget
            try:
                getattr(txt, "text").configure(state="normal")
            except Exception:
                pass

        # make result JSON-serializable (handle Decimal etc.)
        serial = _make_serializable(result)
        try:
            txt.insert("end", json.dumps(serial, ensure_ascii=False, indent=2))
        except Exception:
            try:
                txt.delete(1.0, "end")
            except Exception:
                pass
            txt.insert("end", str(serial))
    except Exception:
        # Best-effort insert; if that fails, ignore
        try:
            txt.insert("end", str(result))
        except Exception:
            pass

    # Try to set the text widget to disabled/read-only where supported
    try:
        txt.configure(state="disabled")
    except Exception:
        try:
            getattr(txt, "text").configure(state="disabled")
        except Exception:
            pass

    # ----------------- buttons (保存/导出/可视化/关闭) -----------------
    btn_frame = tb.Frame(dlg)
    btn_frame.pack(fill=X, pady=6)

    # 原有的 _save 函数仍保留为“另存为”功能
    def _save():
        from tkinter.filedialog import asksaveasfilename
        path = asksaveasfilename(defaultextension=".json", filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(_make_serializable(result), f, ensure_ascii=False, indent=2)
                messagebox.showinfo("保存成功", f"已保存到 {path}")
            except Exception as e:
                messagebox.showerror("保存失败", str(e))

    # 新增：导出 JSON（保存到 reports/reconcile_{account_id}.json）
    def _export_json():
        try:
            # 优先使用 reconcile_ui.save_report_json if available
            if ru and hasattr(ru, "save_report_json"):
                path = ru.save_report_json(result, account_id)
            else:
                # 本地实现回退
                reports_dir = os.path.join(os.path.dirname(__file__), "..", "reports")
                os.makedirs(reports_dir, exist_ok=True)
                fname = f"reconcile_{account_id}.json"
                path = os.path.join(reports_dir, fname)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(_make_serializable(result), f, ensure_ascii=False, indent=2, default=str)
            if path:
                messagebox.showinfo("导出成功", f"已导出对账 JSON:\n{path}")
            else:
                messagebox.showerror("导出失败", "导出 JSON 失败")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))

    # 新增：生成可视化（调用 reconcile_ui.generate_visualization_from_report 或回退执行 viz 脚本）
    def _generate_viz():
        try:
            # 先确保 JSON 已保存
            if ru and hasattr(ru, "save_report_json"):
                json_path = ru.save_report_json(result, account_id)
            else:
                # 本地回退保存到 reports/
                reports_dir = os.path.join(os.path.dirname(__file__), "..", "reports")
                os.makedirs(reports_dir, exist_ok=True)
                fname = f"reconcile_{account_id}.json"
                json_path = os.path.join(reports_dir, fname)
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(_make_serializable(result), f, ensure_ascii=False, indent=2, default=str)

            if not json_path or not os.path.exists(json_path):
                messagebox.showerror("可视化失败", "JSON 保存失败，无法生成可视化")
                return

            # 首选使用 reconcile_ui.generate_visualization_from_report
            if ru and hasattr(ru, "generate_visualization_from_report"):
                out_html = os.path.join(os.path.dirname(json_path), f"reconcile_{account_id}_viz.html")
                res_html = ru.generate_visualization_from_report(json_path, out_html=out_html, blocks=30, scale="total", top=100)
                if res_html:
                    messagebox.showinfo("已生成并打开可视化", f"已生成可视化并在浏览器打开：\n{res_html}")
                else:
                    # ru 会在失败时弹窗已包含错误信息
                    pass
            else:
                # 回退：尝试执行 scripts/viz_per_instrument.py 或 viz_blocks.py
                repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
                script1 = os.path.join(repo_root, "scripts", "viz_per_instrument.py")
                script2 = os.path.join(repo_root, "viz_blocks.py")
                script = script1 if os.path.exists(script1) else (script2 if os.path.exists(script2) else None)
                if not script:
                    messagebox.showerror("可视化失败", f"找不到可视化脚本，期待：\n{script1}\n或\n{script2}")
                    return
                out_html = os.path.splitext(json_path)[0] + "_viz.html"
                cmd = [sys.executable, script, "--json", json_path, "--out", out_html, "--blocks", "30", "--scale", "total", "--top", "100"]
                proc = subprocess.run(cmd, capture_output=True, text=True)
                if proc.returncode != 0:
                    messagebox.showerror("可视化失败", f"可视化脚本返回错误 (rc={proc.returncode})\n\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}")
                    return
                webbrowser.open("file://" + os.path.abspath(out_html))
                messagebox.showinfo("可视化成功", f"已生成并打开: {out_html}")
        except Exception as e:
            messagebox.showerror("可视化失败", str(e))

    # 按钮布局（包含原有“保存到文件”与新增按钮）
    tb.Button(btn_frame, text="导出 JSON", command=_export_json, bootstyle="primary-outline").pack(side=LEFT, padx=6)
    tb.Button(btn_frame, text="生成可视化", command=_generate_viz, bootstyle="info-outline").pack(side=LEFT, padx=6)
    tb.Button(btn_frame, text="保存到文件", command=_save, bootstyle="secondary-outline").pack(side=LEFT, padx=6)
    tb.Button(btn_frame, text="关闭", command=dlg.destroy, bootstyle="secondary-outline").pack(side=RIGHT, padx=6)

def build_account_frame(root, acc_display, config):
    """
    acc_display: 显示用的别名（如 'shu'），用于 UI 标签
    config: 包含至少 log_file，可选 account_id（真实资金账号ID）
    内部所有识别/对账/进程均使用 account_id = config.get('account_id', acc_display)
    """
    account_id = config.get("account_id", acc_display)

    frame = tb.LabelFrame(root, text=f"账户：{acc_display} ({account_id})", padding=(10,8))
    frame.pack(side=LEFT, padx=10, pady=10, fill=BOTH, expand=True)

    status_label = tb.Label(frame, text="未启动", foreground="#2779aa", font=("微软雅黑", 10, "bold"))
    status_label.pack(anchor="w", pady=2)
    btn_frame = tb.Frame(frame)
    btn_frame.pack(fill=X, pady=3)
    btn_start = tb.Button(btn_frame, text="启动", width=10, bootstyle="success-outline")
    btn_stop = tb.Button(btn_frame, text="停止", width=10, bootstyle="danger-outline")
    btn_start.pack(side=LEFT, padx=3)
    btn_stop.pack(side=LEFT, padx=3)

    # 新增：强制刷新与对账按钮
    chk_force_var = tb.IntVar(value=0)
    chk_force = tb.Checkbutton(btn_frame, text="强制刷新", variable=chk_force_var)
    chk_force.pack(side=LEFT, padx=6)
    btn_reconcile = tb.Button(btn_frame, text="对账", width=10, bootstyle="primary-outline")
    btn_reconcile.pack(side=LEFT, padx=3)

    log_label = tb.Label(frame, text="日志窗口：")
    log_label.pack(anchor="w", pady=(6,0))
    log_text = ScrolledText(frame, height=10, width=50, font=("Consolas", 10), bootstyle="light")
    log_text.pack(fill=BOTH, expand=True, pady=2)
    btn_refresh = tb.Button(frame, text="刷新日志", bootstyle="info-outline")
    btn_refresh.pack(pady=2)

    widgets = {"status": status_label, "log_text": log_text}
    # 这里传入 account_id（ID）给 AccountProcess，确保所有后续操作都用 ID
    proc = AccountProcess(account_id, config, widgets)
    btn_start.config(command=lambda: [proc.start(), proc.update_status()])
    btn_stop.config(command=lambda: [proc.stop(), proc.update_status()])
    btn_refresh.config(command=proc.update_log)

    # 对账按钮回调（优先使用本地对账接口，否则使用 yunfei 的网络对账）
    def on_reconcile_click():
        # 优先使用本地文件比对接口（无需网络抓取）
        btn_reconcile.config(state="disabled", text="检测中...")
        force = bool(chk_force_var.get())

        def worker():
            result = None
            err = None
            used_local = False
            try:
                # 1) 首先尝试使用本地的 generate_reconcile_report / reconcile_for_account
                if generate_reconcile_report is not None:
                    try:
                        # generate_reconcile_report(account_id, require_today=False)
                        res = generate_reconcile_report(account_id, require_today=False)
                        result = res
                        used_local = True
                    except Exception as e_local:
                        print(f"[reconcile] generate_reconcile_report 失败: {e_local}")
                        result = None

                if result is None and reconcile_for_account_local is not None:
                    try:
                        res = reconcile_for_account_local(account_id)
                        result = res
                        used_local = True
                    except Exception as e_local:
                        print(f"[reconcile] reconcile_for_account_local 失败: {e_local}")
                        result = None

                # 2) 如果本地方法都不可用或失败，则回退到网络抓取的 reconcile_account（原有流程）
                if not used_local:
                    if reconcile_account is None or login is None:
                        raise RuntimeError("既没有本地对账函数，也没有 yunfei 对账模块可用")
                    # 先快速尝试 login 检查（轻量），如果未登录则引导用户在浏览器登录
                    session = login(username=None)
                    if not session:
                        # 回到主线程提示用户在浏览器登录
                        def prompt_login():
                            if messagebox.askyesno("未登录", "未检测到有效的云飞登录状态。是否在浏览器中打开登录页面以人工登录？"):
                                webbrowser.open(BASE_URL + "/F2/login.aspx")
                        root.after(0, prompt_login)
                        result = {'fetched_at': None, 'batches': {}, 'account_holdings': {}, 'warnings': ['not_logged_in']}
                    else:
                        # 已登录：调用 reconcile_account，传入 session via username if needed
                        result = reconcile_account(account=account_id, account_snapshot=None, xt_trader=None, username=None, force_fetch=force, cache_ttl=600)
            except Exception as e:
                err = e

            def on_done():
                # 处理结果中的 rate_limited 警告：若包含 retry_after，则禁用按钮直至冷却期
                def parse_retry_after(warnings):
                    for w in warnings:
                        if isinstance(w, str) and w.startswith('rate_limited:'):
                            # formats: rate_limited:retry_after=123 OR rate_limited:...
                            m = __import__('re').search(r'retry_after=(\d+)', w)
                            if m:
                                return int(m.group(1))
                            return None
                    return None

                retry_after = None
                if err:
                    messagebox.showerror("对账失败", f"对账出错: {err}")
                    btn_reconcile.config(state="normal", text="对账")
                    return
                if result:
                    warnings = result.get('warnings', []) or ( [result.get('warning')] if result.get('warning') else [] )
                    retry_after = parse_retry_after(warnings)
                    if retry_after:
                        # 提示用户并禁用按钮 retry_after 秒
                        messagebox.showwarning("限流提示", f"检测到云飞对当前请求限流，请等待约 {retry_after} 秒后重试，或在浏览器手动登录后重试。")
                        btn_reconcile.config(state="disabled", text=f"等待 {retry_after}s")
                        # 安排定时器以重新启用按钮（每秒更新文案）
                        start_ts = int(time.time())
                        def tick():
                            elapsed = int(time.time()) - start_ts
                            remain = retry_after - elapsed
                            if remain <= 0:
                                btn_reconcile.config(state="normal", text="对账")
                                return
                            btn_reconcile.config(text=f"等待 {remain}s")
                            root.after(1000, tick)
                        root.after(1000, tick)
                        _show_reconcile_dialog(root, result, account_id)
                        return

                    # 其他 warnings: 显示提示但不禁用太久
                    if warnings:
                        w = "; ".join([str(x) for x in warnings])
                        messagebox.showwarning("对账警告", f"对账完成，但存在警告: {w}\n请按提示登录或强制刷新后重试。")

                btn_reconcile.config(state="normal", text="对账")
                _show_reconcile_dialog(root, result, account_id)

            try:
                root.after(0, on_done)
            except Exception:
                on_done()

        threading.Thread(target=worker, daemon=True).start()

    btn_reconcile.config(command=on_reconcile_click)

    return proc

def save_plan(plan_text, plan_file):
    os.makedirs(os.path.dirname(plan_file), exist_ok=True)
    with open(plan_file, "w", encoding="utf-8") as f:
        f.write(plan_text)
    messagebox.showinfo("提示", f"计划已保存到 {plan_file}")

def load_plan(plan_file):
    if os.path.exists(plan_file):
        with open(plan_file, "r", encoding="utf-8") as f:
            return f.read()
    return ""