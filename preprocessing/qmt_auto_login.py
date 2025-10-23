#!/usr/bin/env python3
# preprocessing/qmt_auto_login.py
# 精简版：仅保留“粘贴密码（坐标点击 + 剪贴板）”和“自动识别并粘贴验证码（OCR -> 计算 -> 粘贴）”两个功能。
#
# 说明：
# - 验证码形式为简单的算术表达式（例如 "5 + 14" 或 "7-2"），脚本会截屏 captcha 区域做 OCR，解析表达式并计算结果，然后粘贴到验证码输入框。
# - OCR 使用 pytesseract（依赖系统安装的 Tesseract OCR），并对图像做基本预处理以提高识别率。
# - 粘贴采用坐标点击 + Ctrl+V（pyautogui / pyperclip）或逐字符输入回退。
#
# 依赖（请先安装）：
# pip install pywinauto pyperclip pyautogui pillow opencv-python pytesseract
# 另外还需在系统上安装 Tesseract OCR 可执行文件：
# - Windows 推荐安装：https://github.com/tesseract-ocr/tesseract/wiki/Downloads
# - 若非默认安装路径，请在脚本顶部设置 pytesseract.pytesseract.tesseract_cmd
#
# 使用：
# 1. 以与 QMT 相同的权限运行（若 QMT 以管理员权限运行，脚本也需管理员权限）
# 2. 打开 QMT 登录窗口并置于前台
# 3. 运行脚本：python preprocessing/qmt_auto_login.py
# 4. 点击 “粘贴密码” 或 “识别并粘贴验证码” 按钮
#
# 注意：OCR 对截图质量和字体敏感。若识别错误，可使用“导出控件”观察控件坐标，或手动输入验证码（我也保留了在识别后确认的交互）。

import time
import logging
import tkinter as tk
from tkinter import messagebox, simpledialog
import json
import os
import re

# OCR / image
try:
    import pytesseract
    from PIL import Image
    import cv2
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

# automation libs
try:
    from pywinauto import Application, findwindows
    from pywinauto.keyboard import send_keys
    PYWIN_AVAILABLE = True
except Exception as e:
    PYWIN_AVAILABLE = False
    _PYWIN_ERR = e

try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
except Exception:
    PYPERCLIP_AVAILABLE = False

try:
    import pyautogui
    PYAUTO_AVAILABLE = True
except Exception:
    PYAUTO_AVAILABLE = False

# config
USERNAME = "6006288"
PASSWORD = "628428"
WINDOW_HINTS = ["XtMiniQmt"]
LOG_LEVEL = logging.INFO

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")

# If tesseract is installed in non-standard path, uncomment and set:
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ---------------- window helpers ----------------
def find_window_handle(timeout=8):
    if not PYWIN_AVAILABLE:
        raise RuntimeError(f"pywinauto 未安装: {_PYWIN_ERR}")
    end = time.time() + timeout
    patterns = [f".*{h}.*" for h in WINDOW_HINTS] + [".*QMT.*", ".*国金.*", ".*"]
    while time.time() < end:
        for pat in patterns:
            try:
                handles = findwindows.find_windows(title_re=pat, top_level_only=True)
            except Exception:
                handles = []
            if handles:
                logging.info("找到窗口 pattern=%s, handle=%s", pat, handles[0])
                return handles[0]
        time.sleep(0.4)
    return None

def focus_window_by_handle(h):
    try:
        app = Application(backend="uia").connect(handle=h)
        dlg = app.window(handle=h)
        dlg.set_focus()
        return dlg
    except Exception:
        logging.exception("focus_window_by_handle 失败")
        return None

# ---------------- fill / paste helpers ----------------
def try_click_input_and_send_clip(ctrl, text):
    """ctrl.click_input + send_keys('^v')"""
    if not PYPERCLIP_AVAILABLE:
        logging.warning("pyperclip 未安装")
        return False
    try:
        pyperclip.copy(text)
    except Exception:
        logging.exception("pyperclip.copy 失败")
        return False
    try:
        ctrl.click_input()
        time.sleep(0.12)
        send_keys("^v")
        time.sleep(0.12)
        logging.info("ctrl.click_input + send_keys('^v') 成功")
        return True
    except Exception:
        logging.exception("ctrl.click_input + send_keys 失败")
    return False

def try_coords_click_and_clip_rect(rect, text):
    """直接按 rectangle（左上/宽高）坐标点击并粘贴"""
    if not PYAUTO_AVAILABLE or not PYPERCLIP_AVAILABLE:
        logging.warning("pyautogui/pyperclip 不可用")
        return False
    try:
        left, top, right, bottom = rect
        x = int((left + right) / 2)
        y = int((top + bottom) / 2)
        pyperclip.copy(text)
        pyautogui.click(x, y)
        time.sleep(0.12)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.12)
        logging.info("坐标点击并 Ctrl+V 粘贴 已尝试")
        return True
    except Exception:
        logging.exception("坐标点击并粘贴 失败")
    return False

def try_coords_click_and_type_rect(rect, text):
    """按矩形坐标点击并逐字符输入"""
    if not PYAUTO_AVAILABLE:
        logging.warning("pyautogui 不可用")
        return False
    try:
        left, top, right, bottom = rect
        x = int((left + right) / 2)
        y = int((top + bottom) / 2)
        pyautogui.click(x, y)
        time.sleep(0.08)
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.04)
        pyautogui.press('backspace')
        time.sleep(0.04)
        pyautogui.write(text, interval=0.06)
        time.sleep(0.06)
        logging.info("坐标点击并逐字符输入 已尝试")
        return True
    except Exception:
        logging.exception("坐标点击并逐字符输入 失败")
    return False

# ---------------- locate edits / controls ----------------
def find_edits(dlg):
    try:
        edits = dlg.descendants(control_type="Edit")
    except Exception:
        edits = []
    return edits

def locate_captcha_edit(edits):
    """优先按 name 中包含 '验'/'验证码' 定位；否则按典型顺序第3个 edit；若都失败则返回相对位于密码下方的 edit"""
    if not edits:
        return None
    for e in edits:
        try:
            name = (e.element_info.name or "").lower()
        except Exception:
            name = ""
        if any(k in name for k in ("验", "验证码", "verify", "code", "vertify")):
            return e
    if len(edits) >= 3:
        return edits[2]
    # fallback: pick the bottom-most edit (largest top)
    try:
        rects = []
        for e in edits:
            try:
                r = e.rectangle()
                rects.append((e, r.top))
            except Exception:
                rects.append((e, 0))
        rects_sorted = sorted(rects, key=lambda x: x[1])
        return rects_sorted[-1][0]
    except Exception:
        return edits[-1]

def get_rect_of_ctrl(ctrl):
    try:
        r = ctrl.rectangle()
        return (r.left, r.top, r.right, r.bottom)
    except Exception:
        return None

# ---------------- captcha capture + ocr + parse ----------------
def capture_captcha_image_by_edit(dlg, edit_ctrl):
    """
    尝试通过 edit_ctrl 的 rectangle 推断 captcha 图片区域并截图返回 PIL.Image。
    策略：
    - 首先尝试在 edit 右侧一定偏移区域截图（常见布局：验证码图片在输入框右侧）
    - 若该区域太小或出错，则尝试在 edit 上方/下方做小范围截图
    """
    if not PYAUTO_AVAILABLE:
        logging.warning("pyautogui 不可用，无法截图")
        return None
    rect = get_rect_of_ctrl(edit_ctrl)
    if not rect:
        return None
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top
    # 右侧区域：从 edit.right + 6, top-4, 大小取 height x (width*0.8) 或限定最小/最大
    cap_left = right + 6
    cap_top = max(top - 6, 0)
    cap_w = int(min(max(width * 0.8, 40), 200))
    cap_h = int(max(height + 8, 20))
    try:
        img = pyautogui.screenshot(region=(cap_left, cap_top, cap_w, cap_h))
        logging.info("已截取候选验证码区域（右侧）：%s", (cap_left, cap_top, cap_w, cap_h))
        return img
    except Exception:
        logging.exception("右侧截图失败，尝试上方截图")
    # fallback: 上方小图
    try:
        cap_left2 = left
        cap_top2 = max(top - cap_h - 6, 0)
        img2 = pyautogui.screenshot(region=(cap_left2, cap_top2, cap_w, cap_h))
        logging.info("已截取候选验证码区域（上方）")
        return img2
    except Exception:
        logging.exception("备用截图失败")
    return None

def preprocess_for_ocr(pil_img):
    """
    转为灰度、二值化并放大，返回 OpenCV image (numpy) 或 PIL if pytesseract can accept.
    """
    try:
        img = cv2.cvtColor(cv2.imread, cv2.COLOR_BGR2GRAY)  # dummy to ensure cv2 imported
    except Exception:
        pass
    try:
        # convert PIL->np array
        img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # resize larger for better OCR
        h, w = gray.shape[:2]
        scale = 2.0 if max(w, h) < 200 else 1.5
        new_w = int(w * scale)
        new_h = int(h * scale)
        gray = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
        # adaptive threshold
        th = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 11, 2)
        # apply some morph to remove noise
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2,2))
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kernel)
        # invert back if needed (tesseract expects dark text on light background)
        th_inv = cv2.bitwise_not(th)
        return th_inv
    except Exception:
        logging.exception("preprocess_for_ocr 失败")
        try:
            return pil_img.convert("L")
        except Exception:
            return pil_img

# safe eval for simple arithmetic
def parse_and_eval_expression(s):
    """
    从字符串中抽取简单的二元整数算术表达式并返回整数结果。
    支持 +, -, x, X, *, /
    返回 (expr_str, result) 或 (None, None) 如果无法解析。
    """
    if not s:
        return None, None
    # keep only digits and operators and spaces
    s2 = re.sub(r"[^0-9+\-xX*/ ]", " ", s)
    # find pattern like 12 + 3 or 4-5
    m = re.search(r"(\d+)\s*([+\-xX*/])\s*(\d+)", s2)
    if not m:
        return None, None
    a = int(m.group(1))
    op = m.group(2)
    b = int(m.group(3))
    if op in ("+",):
        return f"{a}+{b}", a + b
    if op in ("-",):
        return f"{a}-{b}", a - b
    if op in ("x","X","*"):
        return f"{a}*{b}", a * b
    if op in ("/",):
        if b == 0:
            return f"{a}/{b}", None
        return f"{a}/{b}", a // b  # integer division for captcha
    return None, None

def ocr_recognize_expression(pil_img):
    """对截图进行 OCR 识别并解析表达式 -> 返回 (recognized_text, expr, result)"""
    if not OCR_AVAILABLE:
        logging.warning("OCR 库不可用（请安装 pytesseract/opencv/pillow）")
        return None, None, None
    try:
        import numpy as np  # local import to avoid global import if not installed
        # preprocess
        img_cv = preprocess_for_ocr(pil_img)
        # pytesseract accepts PIL or numpy array; convert back to PIL for tesseract
        if isinstance(img_cv, (bytes, bytearray)):
            pil_for_tess = pil_img
        else:
            try:
                pil_for_tess = Image.fromarray(cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB))
            except Exception:
                try:
                    pil_for_tess = Image.fromarray(img_cv)
                except Exception:
                    pil_for_tess = pil_img
        # use whitelist digits and operators
        config = r"-c tessedit_char_whitelist=0123456789+-xX*/ --psm 7"
        text = pytesseract.image_to_string(pil_for_tess, config=config)
        text = text.strip()
        logging.info("OCR 原始识别: %r", text)
        expr, result = parse_and_eval_expression(text)
        if expr is None:
            # try looser: remove spaces and rerun regex
            expr, result = parse_and_eval_expression(text.replace(" ", ""))
        return text, expr, result
    except Exception:
        logging.exception("ocr_recognize_expression 失败")
        return None, None, None

# ---------------- UI actions: paste password & captcha using coords ----------------
def run_coords_paste_password():
    """定位密码输入框（按 Edit 列表，常见为第2个），并用坐标点击+粘贴密码"""
    if not PYWIN_AVAILABLE:
        messagebox.showerror("错误", f"pywinauto 未安装: {_PYWIN_ERR}")
        return
    if not (PYAUTO_AVAILABLE and PYPERCLIP_AVAILABLE):
        messagebox.showwarning("缺少依赖", "需要 pyautogui 与 pyperclip 来执行坐标粘贴。pip install pyautogui pyperclip")
    h = find_window_handle(timeout=8)
    if not h:
        messagebox.showerror("未找到窗口", "未能找到 QMT 窗口")
        return
    dlg = focus_window_by_handle(h)
    if not dlg:
        messagebox.showerror("失败", "连接并聚焦窗口失败")
        return
    edits = find_edits(dlg)
    if not edits:
        messagebox.showwarning("未找到", "未能定位 Edit 控件")
        return
    # 常见结构： edits[0]=username, edits[1]=password, edits[2]=captcha
    target = None
    for e in edits:
        try:
            name = (e.element_info.name or "").lower()
        except Exception:
            name = ""
        if any(k in name for k in ("密", "password")):
            target = e
            break
    if target is None and len(edits) >= 2:
        target = edits[1]
    if target is None:
        messagebox.showwarning("未找到", "未能定位密码控件")
        return
    rect = get_rect_of_ctrl(target)
    ok = False
    # try ctrl.click_input first
    try:
        ok = try_click_input_and_send_clip(target, PASSWORD)
    except Exception:
        ok = False
    if not ok:
        if rect:
            ok = try_coords_click_and_clip_rect(rect, PASSWORD)
    if not ok and rect:
        ok = try_coords_click_and_type_rect(rect, PASSWORD)
    messagebox.showinfo("完成", f"密码粘贴尝试结果: {ok}")

def run_ocr_and_paste_captcha():
    """自动截图识别验证码（算式），计算结果并粘贴到验证码输入框"""
    if not PYWIN_AVAILABLE:
        messagebox.showerror("错误", f"pywinauto 未安装: {_PYWIN_ERR}")
        return
    if not OCR_AVAILABLE:
        messagebox.showerror("错误", "缺少 OCR 支持库。请安装 pytesseract, pillow, opencv-python，并确保系统安装了 Tesseract OCR。")
        return
    h = find_window_handle(timeout=8)
    if not h:
        messagebox.showerror("未找到窗口", "未能找到 QMT 窗口")
        return
    dlg = focus_window_by_handle(h)
    if not dlg:
        messagebox.showerror("失败", "连接并聚焦窗口失败")
        return
    edits = find_edits(dlg)
    if not edits:
        messagebox.showwarning("未找到", "未能定位 Edit 控件")
        return
    captcha_edit = locate_captcha_edit(edits)
    if not captcha_edit:
        messagebox.showwarning("未找到", "未能定位验证码输入框")
        return
    # capture candidate captcha image area
    img = capture_captcha_image_by_edit(dlg, captcha_edit)
    if img is None:
        messagebox.showwarning("截图失败", "无法截取验证码区域，操作终止")
        return
    # OCR recognize and parse
    raw_text, expr, result = ocr_recognize_expression(img)
    # show recognized and allow user to confirm / edit
    prompt = f"OCR 识别: {raw_text!s}\n解析表达式: {expr!s}\n结果: {result!s}\n\n是否接受并粘贴结果？\n（你也可以手动编辑结果）"
    # default_text prefill
    default_text = "" if result is None else str(result)
    user_value = simpledialog.askstring("确认验证码结果", prompt, initialvalue=default_text)
    if user_value is None:
        return
    user_value = user_value.strip()
    if not user_value:
        messagebox.showwarning("取消", "你未输入验证码结果，操作已取消")
        return
    # perform paste into captcha edit
    rect = get_rect_of_ctrl(captcha_edit)
    ok = False
    try:
        ok = try_click_input_and_send_clip(captcha_edit, user_value)
    except Exception:
        ok = False
    if not ok and rect:
        ok = try_coords_click_and_clip_rect(rect, user_value)
    if not ok and rect:
        ok = try_coords_click_and_type_rect(rect, user_value)
    messagebox.showinfo("完成", f"验证码粘贴尝试结果: {ok}")

# ---------------- GUI (极简，只保留两项按钮) ----------------
def create_ui():
    root = tk.Tk()
    root.title("QMT AutoFill - 粘贴密码与验证码（OCR）")
    frm = tk.Frame(root, padx=12, pady=12)
    frm.pack()
    tk.Label(frm, text="说明：先打开 QMT 登录窗口并置于前台。").grid(row=0, column=0, columnspan=2, sticky="w")
    tk.Label(frm, text=f"将填入 用户: {USERNAME}  密码: {PASSWORD}").grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 10))
    tk.Button(frm, text="粘贴密码（坐标点击 + 剪贴板）", width=36, bg="#2E8BFF", fg="white", command=run_coords_paste_password).grid(row=2, column=0, columnspan=2, pady=(0, 6))
    tk.Button(frm, text="识别并粘贴验证码（OCR -> 计算 -> 粘贴）", width=36, bg="#FF8C00", fg="black", command=run_ocr_and_paste_captcha).grid(row=3, column=0, columnspan=2, pady=(0, 6))
    tk.Button(frm, text="退出", width=10, command=root.destroy).grid(row=4, column=1, sticky="e")
    root.mainloop()

if __name__ == "__main__":
    create_ui()