#!/usr/bin/env python3
# preprocessing/qmt_auto_login.py
# Single-file: paste password, use Tencent Cloud OCR to recognize captcha and auto-login (headless mode supported).
# Username is NOT filled by this script (assumed prefilled by QMT as 'qmt').
#
# Notes:
# - This script prefers local secrets_local.py (TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY).
#   If not present, it falls back to environment variables.
# - Local pytesseract / local OCR has been removed by design.
# - It uses tc3_sign if available in preprocessing/tencent_tc3_sign.py; otherwise an inline signer is used.
# - Run headless: python preprocessing/qmt_auto_login.py auto
# - Interactive GUI: python preprocessing/qmt_auto_login.py

from __future__ import annotations
import time
import logging
import tkinter as tk
from tkinter import messagebox, simpledialog
import sys
import json
import os
import re
import tempfile
import base64
import requests
from typing import Optional, Tuple

# ------------------------------------------------------------------
# Pillow imports (used for preprocessing). If Pillow not available we skip local preprocessing.
# ------------------------------------------------------------------
try:
    from PIL import Image, ImageOps, ImageFilter, ImageEnhance
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

# ------------------------------------------------------------------
# Try to read secrets from a local file (secrets_local.py) first.
# secrets_local.py should define TENCENTCLOUD_SECRET_ID and TENCENTCLOUD_SECRET_KEY.
# ------------------------------------------------------------------
DEFAULT_TC_SID = None
DEFAULT_TC_SK = None
try:
    from preprocessing import secrets_local as _secrets

    DEFAULT_TC_SID = getattr(_secrets, "TENCENTCLOUD_SECRET_ID", None) or getattr(_secrets, "SECRET_ID", None)
    DEFAULT_TC_SK  = getattr(_secrets, "TENCENTCLOUD_SECRET_KEY", None) or getattr(_secrets, "SECRET_KEY", None)
except Exception:
    DEFAULT_TC_SID = None
    DEFAULT_TC_SK = None

# ------------------------------------------------------------------
# Try project tc3_sign helper; if not found, provide an inline fallback signer.
# ------------------------------------------------------------------
tc3_sign = None
try:
    from preprocessing.tencent_tc3_sign import tc3_sign as _tc3  # type: ignore
    tc3_sign = _tc3
except Exception:
    tc3_sign = None
# after the attempt to import:
if tc3_sign is not None:
    logging.info("Using tc3_sign from module: %s", getattr(tc3_sign, "__module__", "<unknown>"))
else:
    logging.info("Using inline tc3_sign fallback defined in qmt_auto_login.py")

if tc3_sign is None:
    # Inline minimal TC3 signer
    import hashlib, hmac


    def _sha256_hex(msg: bytes) -> str:
        return hashlib.sha256(msg).hexdigest()


    def _hmac_sha256(key: bytes, msg: bytes) -> bytes:
        # 正确地传入 msg 和 digestmod
        return hmac.new(key, msg, hashlib.sha256).digest()

    def tc3_sign(secret_id: str, secret_key: str, service: str, host: str, region: str,
                 action: str, version: str, payload: dict, timestamp: int = None,
                 content_type: str = "application/json; charset=utf-8") -> Tuple[dict, str]:
        if timestamp is None:
            timestamp = int(time.time())
        t = timestamp
        date = time.strftime("%Y-%m-%d", time.gmtime(t))
        http_request_method = "POST"
        canonical_uri = "/"
        canonical_querystring = ""
        body_str = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        body_bytes = body_str.encode("utf-8")
        hashed_request_payload = _sha256_hex(body_bytes)
        canonical_headers = f"content-type:{content_type}\nhost:{host}\n"
        signed_headers = "content-type;host"
        canonical_request = (
            f"{http_request_method}\n"
            f"{canonical_uri}\n"
            f"{canonical_querystring}\n"
            f"{canonical_headers}\n"
            f"{signed_headers}\n"
            f"{hashed_request_payload}"
        )
        algorithm = "TC3-HMAC-SHA256"
        credential_scope = f"{date}/{service}/tc3_request"
        hashed_canonical_request = _sha256_hex(canonical_request.encode("utf-8"))
        string_to_sign = f"{algorithm}\n{t}\n{credential_scope}\n{hashed_canonical_request}"
        secret_date = _hmac_sha256(("TC3" + secret_key).encode("utf-8"), date.encode("utf-8"))
        secret_service = _hmac_sha256(secret_date, service.encode("utf-8"))
        secret_signing = _hmac_sha256(secret_service, b"tc3_request")
        signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        authorization = (
            f"{algorithm} "
            f"Credential={secret_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )
        headers = {
            "Authorization": authorization,
            "Content-Type": content_type,
            "Host": host,
            "X-TC-Action": action,
            "X-TC-Version": version,
            "X-TC-Region": region,
            "X-TC-Timestamp": str(t),
        }
        return headers, body_str

# ------------------------------------------------------------------
# Automation libraries
# ------------------------------------------------------------------
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

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
USERNAME = "qmt"  # informational only
# 原来的硬编码密码作为回退（保留以兼容历史），优先使用传入的 password 参数
PASSWORD_DEFAULT = "628428"
WINDOW_HINTS = ["XtMiniQmt"]
LOG_LEVEL = logging.INFO

# OCR retry/threshold config
OCR_CONF_THRESHOLD = 70    # minimal confidence to accept immediately
OCR_MAX_RETRIES = 3        # attempts (including first)

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")

# ---------------- utility: save debug image ----------------
def _save_debug_image(pil_img, prefix="captcha"):
    try:
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        debug_dir = os.path.join(desktop, "qmt_ocr_debug")
        os.makedirs(debug_dir, exist_ok=True)
        ts = int(time.time())
        fname = f"{prefix}_{ts}.png"
        path = os.path.join(debug_dir, fname)
        try:
            pil_img.save(path)
        except Exception:
            try:
                from PIL import Image as _Image
                pil = _Image.fromarray(pil_img)
                pil.save(path)
            except Exception:
                logging.exception("保存调试图片到 %s 失败", path)
                return None
        logging.info("Saved debug captcha image to %s", path)
        return path
    except Exception:
        logging.exception("创建调试目录或保存图片失败")
        return None

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

# ---------------- basic paste helpers ----------------
def try_click_input_and_send_clip(ctrl, text):
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
        try:
            send_keys("^a")
            time.sleep(0.06)
            send_keys("{BACKSPACE}")
            time.sleep(0.06)
        except Exception:
            pass
        send_keys("^v")
        time.sleep(0.12)
        logging.info("ctrl.click_input + send_keys Ctrl+A/Backspace + Ctrl+V 成功")
        return True
    except Exception:
        logging.exception("ctrl.click_input + send_keys 失败")
    return False

def try_coords_click_and_clip_rect(rect, text):
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
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.04)
        pyautogui.press('backspace')
        time.sleep(0.04)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.12)
        logging.info("坐标点击并 Ctrl+A/Backspace + Ctrl+V 粘贴 已尝试")
        return True
    except Exception:
        logging.exception("坐标点击并粘贴 失败")
    return False

def try_coords_click_and_type_rect(rect, text):
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
        logging.info("pyautogui 逐字符输入 已尝试")
        return True
    except Exception:
        logging.exception("pyautogui 逐字符输入 失败")
    return False

# ---------------- locate edits / controls ----------------
def find_edits(dlg):
    try:
        edits = dlg.descendants(control_type="Edit")
    except Exception:
        edits = []
    return edits

def locate_captcha_edit(edits):
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

# ---------------- capture captcha image ----------------
def capture_captcha_image_by_edit(dlg, edit_ctrl, save_debug=True):
    if not PYAUTO_AVAILABLE:
        logging.warning("pyautogui 不可用，无法截图")
        return None
    rect = get_rect_of_ctrl(edit_ctrl)
    if not rect:
        return None
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top
    cap_left = right + 6
    cap_top = max(top - 6, 0)
    cap_w = int(min(max(int(width * 0.8), 40), 300))
    cap_h = int(max(height + 8, 20))
    try:
        img = pyautogui.screenshot(region=(cap_left, cap_top, cap_w, cap_h))
        logging.info("已截取候选验证码区域（右侧）：%s", (cap_left, cap_top, cap_w, cap_h))
        if save_debug:
            saved = _save_debug_image(img, prefix="captcha_right")
            if saved:
                logging.info("captcha saved: %s", saved)
        return img
    except Exception:
        logging.exception("右侧截图失败，尝试上方截图")
    try:
        cap_left2 = left
        cap_top2 = max(top - cap_h - 6, 0)
        img2 = pyautogui.screenshot(region=(cap_left2, cap_top2, cap_w, cap_h))
        logging.info("已截取候选验证码区域（上方）")
        if save_debug:
            saved2 = _save_debug_image(img2, prefix="captcha_top")
            if saved2:
                logging.info("captcha saved: %s", saved2)
        return img2
    except Exception:
        logging.exception("上方截图失败，尝试扩展区域截图")
    try:
        variants = [
            ("left", max(left - int(width * 1.2), 0), max(top - 10, 0), int(width * 1.5), cap_h),
            ("right_wide", right - int(width*0.2), max(top - 10, 0), int(width * 1.8), cap_h),
            ("above_wide", left - 20, max(top - cap_h - 20, 0), int(width*1.6), cap_h*2),
        ]
        for name, lx, ty, w, h in variants:
            try:
                imgv = pyautogui.screenshot(region=(int(lx), int(ty), int(w), int(h)))
                logging.info("已截取候选验证码区域（%s）：%s", name, (int(lx), int(ty), int(w), int(h)))
                if save_debug:
                    sv = _save_debug_image(imgv, prefix=f"captcha_{name}")
                    if sv:
                        logging.info("captcha saved: %s", sv)
                return imgv
            except Exception:
                logging.exception("尝试区域 %s 截图失败", name)
    except Exception:
        logging.exception("所有备用截图策略均失败")
    return None

# ---------------- parse expression ----------------
def parse_and_eval_expression(s):
    if not s:
        return None, None
    s2 = re.sub(r"[^0-9+\-xX*/ ]", " ", s)
    m = re.search(r"(\d+)\s*([+\-xX*/])\s*(\d+)", s2)
    if not m:
        return None, None
    a = int(m.group(1))
    op = m.group(2)
    b = int(m.group(3))
    if op == "+":
        return f"{a}+{b}", a + b
    if op == "-":
        return f"{a}-{b}", a - b
    if op in ("x", "X", "*"):
        return f"{a}*{b}", a * b
    if op == "/":
        if b == 0:
            return f"{a}/{b}", None
        return f"{a}/{b}", a // b
    return None, None

# ---------------- PIL-only preprocessing helper ----------------
def _otsu_threshold_from_histogram(gray_img):
    hist = gray_img.histogram()
    total = sum(hist)
    if total == 0:
        return 128
    sum_total = sum(i * h for i, h in enumerate(hist))
    sumB = 0
    wB = 0
    max_var = 0.0
    threshold = 0
    for i in range(256):
        wB += hist[i]
        if wB == 0:
            continue
        wF = total - wB
        if wF == 0:
            break
        sumB += i * hist[i]
        mB = sumB / wB
        mF = (sum_total - sumB) / wF
        var_between = wB * wF * (mB - mF) * (mB - mF)
        if var_between > max_var:
            max_var = var_between
            threshold = i
    return threshold

def preprocess_captcha_pil(img_pil, save_debug=True, prefix="preproc"):
    if not PIL_AVAILABLE:
        logging.warning("Pillow 未安装或不可用，跳过本地预处理")
        return img_pil
    try:
        img = img_pil.convert("RGB")
        r, g, b = img.split()
        base = b
        base = ImageOps.autocontrast(base, cutoff=0)
        enhancer = ImageEnhance.Contrast(base)
        base = enhancer.enhance(1.8)
        scale = 4
        new_w = max(int(base.width * scale), base.width + 1)
        new_h = max(int(base.height * scale), base.height + 1)
        base = base.resize((new_w, new_h), Image.LANCZOS)
        base = base.filter(ImageFilter.UnsharpMask(radius=1, percent=150, threshold=3))
        gray = base.convert("L")
        thr = _otsu_threshold_from_histogram(gray)
        bw = gray.point(lambda p: 255 if p > thr else 0, mode="1").convert("L")
        bw = bw.filter(ImageFilter.MedianFilter(size=3))
        bw = bw.filter(ImageFilter.MinFilter(size=3))
        bw = bw.filter(ImageFilter.MaxFilter(size=3))
        hist = bw.histogram()
        white_count = hist[255] if len(hist) > 255 else 0
        black_count = hist[0] if len(hist) > 0 else 0
        if black_count > white_count:
            try:
                bw = ImageOps.invert(bw.convert("L"))
            except Exception:
                pass
        bw = ImageOps.autocontrast(bw)
        if save_debug:
            try:
                desktop = os.path.join(os.path.expanduser("~"), "Desktop")
                debug_dir = os.path.join(desktop, "qmt_ocr_debug")
                os.makedirs(debug_dir, exist_ok=True)
                fname = f"{prefix}_{int(time.time())}.png"
                path = os.path.join(debug_dir, fname)
                bw.save(path)
                logging.info("Saved preprocessed captcha to %s", path)
            except Exception:
                logging.exception("Saving preprocessed debug image failed")
        return bw
    except Exception:
        logging.exception("preprocess_captcha_pil failed")
        return img_pil.convert("L")

# ---------------- cloud OCR (tc3_sign) - returns (text, confidence) ----------------
def ocr_via_cloud_save_and_recognize_with_conf(pil_img, region="ap-shanghai", retries=1) -> Tuple[Optional[str], float]:
    try:
        pil_to_use = preprocess_captcha_pil(pil_img, save_debug=True, prefix="for_ocr")
    except Exception:
        pil_to_use = pil_img

    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp_name = tmp.name
        pil_to_use.save(tmp_name)
        tmp.close()
    except Exception:
        logging.exception("保存临时图片失败")
        return None, 0.0

    try:
        _save_debug_image(pil_to_use, prefix="captcha_for_ocr")
    except Exception:
        pass

    secret_id = DEFAULT_TC_SID or os.getenv("TENCENTCLOUD_SECRET_ID")
    secret_key = DEFAULT_TC_SK or os.getenv("TENCENTCLOUD_SECRET_KEY")
    logging.debug("TENCENTCLOUD_SECRET_ID present? %s", bool(secret_id))

    if not secret_id or not secret_key:
        logging.warning("未设置腾讯云凭证（secrets_local.py 或 环境变量），无法使用云 OCR")
        try:
            os.unlink(tmp_name)
        except Exception:
            pass
        return None, 0.0

    try:
        with open(tmp_name, "rb") as f:
            b = f.read()
        img_b64 = base64.b64encode(b).decode("utf-8")
        payload = {"ImageBase64": img_b64}
        service = "ocr"
        host = "ocr.tencentcloudapi.com"
        action = "GeneralAccurateOCR"
        version = "2018-11-19"
        headers, body = tc3_sign(
            secret_id=secret_id,
            secret_key=secret_key,
            service=service,
            host=host,
            region=region,
            action=action,
            version=version,
            payload=payload,
        )
        url = f"https://{host}/"
        resp = requests.post(url, headers=headers, data=body.encode("utf-8"), timeout=30)
        try:
            resp_json = resp.json()
        except Exception:
            resp_json = None
        logging.info("Cloud HTTP status: %s", resp.status_code if resp is not None else "N/A")
        try:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            debug_dir = os.path.join(desktop, "qmt_ocr_debug")
            os.makedirs(debug_dir, exist_ok=True)
            resp_path = os.path.join(debug_dir, f"resp_{int(time.time())}.json")
            with open(resp_path, "w", encoding="utf-8") as f:
                json.dump(resp_json if resp_json is not None else {"raw": resp.text}, f, ensure_ascii=False, indent=2)
            logging.info("Saved cloud OCR raw response to %s", resp_path)
        except Exception:
            logging.exception("保存云 OCR 响应失败")
        if resp_json:
            items = resp_json.get("TextDetections") or resp_json.get("Response", {}).get("TextDetections") or []
            best_text = None
            best_conf = -1.0
            for it in items:
                det = it.get("DetectedText") or it.get("Text") or ""
                conf = it.get("Confidence")
                if conf is None:
                    try:
                        conf = float(it.get("Score", -1))
                    except Exception:
                        conf = -1
                if det and (conf is None or conf > best_conf):
                    best_conf = conf if conf is not None else best_conf
                    best_text = det
            if best_text:
                try:
                    os.unlink(tmp_name)
                except Exception:
                    pass
                return best_text.strip(), float(best_conf)
    except Exception:
        logging.exception("云 OCR via direct HTTP 调用失败")

    try:
        os.unlink(tmp_name)
    except Exception:
        pass

    return None, 0.0

# ---------------- login button and orchestrator ----------------
def click_login_button(dlg):
    try:
        btns = dlg.descendants(control_type="Button")
    except Exception:
        btns = []
    for b in btns:
        try:
            name = (b.element_info.name or "").lower()
        except Exception:
            name = ""
        if any(k in name for k in ("登录", "登 录", "确定", "ok", "sign in", "signin", "login")):
            try:
                b.click_input()
                time.sleep(0.2)
                logging.info("点击按钮 name=%r 成功", name)
                return True
            except Exception:
                logging.exception("通过 click_input 点击登录按钮失败，尝试坐标点击")
                try:
                    r = b.rectangle()
                    x = int((r.left + r.right) / 2)
                    y = int((r.top + r.bottom) / 2)
                    if PYAUTO_AVAILABLE:
                        pyautogui.click(x, y)
                        time.sleep(0.2)
                        return True
                except Exception:
                    logging.exception("坐标点击登录按钮失败")
    try:
        send_keys('{ENTER}')
        time.sleep(0.2)
        return True
    except Exception:
        logging.exception("按回车作为登录点击的回退失败")
    return False

def _get_edit_value(ctrl) -> str:
    """
    Try several methods to read current text/value of an Edit control.
    Returns stripped string (may be empty).
    """
    if ctrl is None:
        return ""
    try:
        # UIA wrapper: get_value()
        v = ctrl.get_value()
        if v is not None:
            return str(v).strip()
    except Exception:
        pass
    try:
        v = ctrl.window_text()
        if v is not None:
            return str(v).strip()
    except Exception:
        pass
    try:
        v = ctrl.texts()
        if isinstance(v, (list, tuple)):
            joined = " ".join([str(x) for x in v if x])
            if joined:
                return joined.strip()
    except Exception:
        pass
    try:
        ai = getattr(ctrl, "element_info", None)
        if ai is not None:
            name = getattr(ai, "name", None)
            if name:
                return str(name).strip()
    except Exception:
        pass
    return ""

def _looks_like_placeholder(s: str) -> bool:
    """
    Heuristics to detect placeholder or label-like texts in the edit control
    (e.g. "请输入验证码", "验证码", "verify code").
    """
    if not s:
        return True
    ss = s.strip()
    # common placeholders or labels
    if len(ss) == 0:
        return True
    if re.search(r"请输入|请输|验证码|verify|code|vertify|请输入验证码", ss, re.I):
        # if it looks like a prompt rather than an entered value, treat as empty
        return True
    # sometimes masked with bullets; treat a single bullet as empty
    if all(ch in "●*•·" for ch in ss):
        return True
    return False

def run_auto_fill_and_login(silent=True, password: Optional[str] = None):
    """
    High-level flow: focus window -> fill password -> OCR captcha -> paste -> click login.
    silent=True: do not show interactive dialogs; only log and return boolean.

    password: optional plaintext password. If None, PASSWORD_DEFAULT is used.

    New behaviour: if on startup the captcha Edit already contains a non-placeholder value,
    do NOT call Tencent OCR. In that case we will leave the existing captcha value as-is
    and proceed to click login (still fill password).
    """
    if not PYWIN_AVAILABLE:
        logging.error("pywinauto 未安装: %s", _PYWIN_ERR)
        return False
    h = find_window_handle(timeout=8)
    if not h:
        logging.error("未找到 QMT 窗口，请先打开并置前台")
        return False
    dlg = focus_window_by_handle(h)
    if not dlg:
        logging.error("连接并聚焦窗口失败")
        return False

    edits = find_edits(dlg)
    # fill password only (do NOT fill username)
    try:
        password_done = False
        pwd_to_use = password if password is not None else PASSWORD_DEFAULT
        for e in edits:
            name = (e.element_info.name or "").lower()
            if any(k in name for k in ("密", "password")):
                try_click_input_and_send_clip(e, pwd_to_use)
                password_done = True
                time.sleep(0.12)
                break
        if not password_done and len(edits) >= 2:
            try_click_input_and_send_clip(edits[1], pwd_to_use)
            password_done = True
    except Exception:
        logging.exception("填写密码失败")
        return False

    captcha_edit = locate_captcha_edit(edits)
    if not captcha_edit:
        logging.error("未能定位验证码输入框；已填写密码，但无法自动填写验证码")
        return False

    # New logic: if captcha edit already contains a non-placeholder value, skip OCR and keep it.
    current_val = ""
    try:
        current_val = _get_edit_value(captcha_edit)
    except Exception:
        current_val = ""
    logging.debug("captcha edit current value: %r", current_val)
    if current_val and (not _looks_like_placeholder(current_val)):
        logging.info("检测到验证码输入框已有值（%r），将保持原值并跳过云 OCR。", current_val)
        clicked = click_login_button(dlg)
        logging.info("自动流程完成（已保留页面中已有验证码）：点击登录=%s", clicked)
        return clicked

    # Try OCR with retries and confidence threshold (only when captcha is empty/placeholder)
    img = capture_captcha_image_by_edit(dlg, captcha_edit)
    if img is None:
        logging.error("无法截取验证码区域，操作终止")
        return False

    attempt = 0
    best_text = None
    best_conf = 0.0
    while attempt < OCR_MAX_RETRIES:
        attempt += 1
        txt, conf = ocr_via_cloud_save_and_recognize_with_conf(img)
        logging.info("OCR attempt %d -> text=%r conf=%s", attempt, txt, conf)
        if txt:
            best_text = txt
            best_conf = conf or 0.0
        if best_conf >= OCR_CONF_THRESHOLD:
            break
        logging.warning("OCR confidence %s < %s, retrying (attempt %d/%d)", best_conf, OCR_CONF_THRESHOLD, attempt, OCR_MAX_RETRIES)
        time.sleep(0.6)
        img = capture_captcha_image_by_edit(dlg, captcha_edit)
        if img is None:
            break

    if not best_text:
        logging.error("OCR 未识别到有效文本，放弃自动填写")
        return False

    expr, result = parse_and_eval_expression(best_text)
    if expr is None:
        expr, result = parse_and_eval_expression(best_text.replace(" ", ""))
    if expr is None:
        value_to_paste = best_text.strip()
        logging.info("使用 OCR 原始文本填入验证码：%r (conf=%s)", value_to_paste, best_conf)
    else:
        value_to_paste = str(result)
        logging.info("解析算式 %s -> %s (conf=%s)", expr, value_to_paste, best_conf)

    rect = get_rect_of_ctrl(captcha_edit)
    ok = False
    try:
        ok = try_click_input_and_send_clip(captcha_edit, value_to_paste)
    except Exception:
        ok = False
    if not ok and rect:
        ok = try_coords_click_and_clip_rect(rect, value_to_paste)
    if not ok and rect:
        ok = try_coords_click_and_type_rect(rect, value_to_paste)

    if not ok:
        logging.error("验证码已识别为 %s，但粘贴到输入框失败。", value_to_paste)
        return False

    clicked = click_login_button(dlg)
    logging.info("自动流程完成：验证码=%s 填写成功=%s 点击登录=%s", value_to_paste, ok, clicked)
    return clicked

# ---------------- remaining helpers and GUI ----------------
def run_coords_paste_password():
    if not PYWIN_AVAILABLE:
        messagebox.showerror("错误", f"pywinauto 未安装: {_PYWIN_ERR}")
        return
    if not PYPERCLIP_AVAILABLE and not PYAUTO_AVAILABLE:
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
    target = None
    for e in edits:
        name = (e.element_info.name or "").lower()
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
    try:
        ok = try_click_input_and_send_clip(target, PASSWORD_DEFAULT)
    except Exception:
        ok = False
    if not ok:
        if rect:
            ok = try_coords_click_and_clip_rect(rect, PASSWORD_DEFAULT)
    if not ok and rect:
        ok = try_coords_click_and_type_rect(rect, PASSWORD_DEFAULT)
    messagebox.showinfo("完成", f"密码粘贴尝试结果: {ok}")

def run_coords_paste_captcha_manual():
    if not PYWIN_AVAILABLE:
        messagebox.showerror("错误", f"pywinauto 未安装: {_PYWIN_ERR}")
        return
    val = simpledialog.askstring("输入验证码", "请在此粘贴或输入你识别到的验证码，然后点击确定：")
    if val is None:
        return
    val = val.strip()
    if not val:
        messagebox.showwarning("空验证码", "你没有输入任何验证码文本，操作已取消。")
        return
    h = find_window_handle(timeout=8)
    if not h:
        messagebox.showerror("未找到窗口", "未能找到 QMT 窗口，请先打开并置前台")
        return
    dlg = focus_window_by_handle(h)
    if not dlg:
        messagebox.showerror("失败", "连接并聚焦窗口失败")
        return
    edits = find_edits(dlg)
    target = locate_captcha_edit(edits)
    if not target:
        messagebox.showwarning("未找到", "未能定位验证码输入框")
        return
    rect = get_rect_of_ctrl(target)
    ok = False
    try:
        ok = try_click_input_and_send_clip(target, val)
    except Exception:
        ok = False
    if not ok and rect:
        ok = try_coords_click_and_clip_rect(rect, val)
    if not ok and rect:
        ok = try_coords_click_and_type_rect(rect, val)
    messagebox.showinfo("完成", f"验证码粘贴尝试结果: {ok}")

def run_highlight_password():
    if not PYWIN_AVAILABLE:
        messagebox.showerror("错误", f"pywinauto 未安装: {_PYWIN_ERR}")
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
    target = None
    for e in edits:
        name = (e.element_info.name or "").lower()
        if any(k in name for k in ("密", "password")):
            target = e
            break
    if target is None and len(edits) >= 2:
        target = edits[1]
    if not target:
        messagebox.showwarning("未找到", "未能定位密码控件")
        return
    try:
        target.draw_outline(colour='red', thickness=3)
    except Exception:
        try:
            rect = target.rectangle()
            x = int((rect.left + rect.right) / 2)
            y = int((rect.top + rect.bottom) / 2)
            if PYAUTO_AVAILABLE:
                pyautogui.moveTo(x, y, duration=0.2)
        except Exception:
            pass
    messagebox.showinfo("高亮", "已尝试高亮/定位密码控件")

def create_ui():
    root = tk.Tk()
    root.title("QMT AutoFill - 仅自动填写密码/验证码并登录")
    frm = tk.Frame(root, padx=12, pady=12)
    frm.pack()
    tk.Label(frm, text="说明：QMT 会自动预填用户名 qmt，请确保登录窗口已置于前台。\n脚本仅填写密码、识别验证码并尝试登录。").grid(row=0, column=0, columnspan=2, sticky="w")
    tk.Label(frm, text=f"将填入 密码: {PASSWORD_DEFAULT}（用户名由 QMT 预填）").grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 10))
    tk.Button(frm, text="粘贴密码（坐标点击 + 剪贴板）", width=36, bg="#2E8BFF", fg="white", command=run_coords_paste_password).grid(row=2, column=0, columnspan=2, pady=(0, 6))
    tk.Button(frm, text="自动填写并登录", width=36, bg="#228B22", fg="white", command=lambda: run_auto_fill_and_login(silent=False)).grid(row=3, column=0, columnspan=2, pady=(0, 6))
    tk.Button(frm, text="手动粘贴验证码", width=36, command=run_coords_paste_captcha_manual).grid(row=4, column=0, columnspan=2, pady=(0, 6))
    tk.Button(frm, text="高亮/定位密码控件（尝试）", width=18, command=run_highlight_password).grid(row=5, column=0, pady=6, sticky="w")
    tk.Button(frm, text="退出", width=10, command=root.destroy).grid(row=5, column=1, sticky="e")
    root.mainloop()

if __name__ == "__main__":
    auto = False
    if len(sys.argv) > 1 and sys.argv[1].lower() in ("auto", "--auto", "--headless"):
        auto = True
    if os.environ.get("QMT_AUTO_RUN") == "1":
        auto = True

    if auto:
        success = run_auto_fill_and_login(silent=True)
        if not success:
            logging.error("自动登录失败（check logs and Desktop/qmt_ocr_debug for artifacts）")
            sys.exit(2)
        else:
            logging.info("自动登录流程已完成（headless）")
            sys.exit(0)
    else:
        create_ui()