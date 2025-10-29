# captcha_solver.py
import cv2
import numpy as np
from PIL import Image
import pytesseract
import re

# 如果需要，显式指定 tesseract 路径
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# 常见 OCR 错误映射
CHAR_MAP = {
    't': '+',  # 常见把 + 识别成 t
    'T': '+',
    '|': '1',
    'l': '1',
    'I': '1',
    'O': '0',
    'o': '0',
    'S': '5',
    's': '5',
    'B': '8',
    '—': '-', '–': '-', '−': '-',  # 各种减号
    'x': '*', 'X': '*', '×': '*', '÷': '/'
}

# 尝试解析简单二元表达式（a op b），返回 int 或 None
def safe_eval_simple(expr):
    expr = expr.strip()
    m = re.match(r'^\s*(\d+)\s*([+\-*/])\s*(\d+)\s*$', expr)
    if not m:
        return None
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    if op == '+': return a + b
    if op == '-': return a - b
    if op == '*': return a * b
    if op == '/': return a // b if b != 0 else None
    return None

# 应用字符映射与清理
def clean_ocr_text(raw):
    if not raw:
        return ''
    s = raw.strip()
    # 逐字替换常见错误
    s2 = ''.join(CHAR_MAP.get(ch, ch) for ch in s)
    # 去掉非数字/运算符/空格/括号字符
    s2 = re.sub(r'[^0-9+\-*/() ]+', '', s2)
    # collapse multiple spaces
    s2 = re.sub(r'\s+', ' ', s2).strip()
    return s2

# 颜色分割：提取蓝色文字区域（适配你截图中的蓝色字体）
def extract_blue_text_region(img_bgr):
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    # HSV 蓝色范围（这个范围可根据实际色调微调）
    lower = np.array([90, 40, 60])   # H,S,V 最小
    upper = np.array([140, 255, 255])# H,S,V 最大
    mask = cv2.inRange(hsv, lower, upper)
    # 去小点、闭合字符笔画
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3,3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    return mask

# 通用预处理（输入为单通道图像）
def preprocess_gray(gray):
    # 自适应阈值或 Otsu，先尝试 Otsu
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # 如果背景是深色则翻转（保证文字为黑/白统一）
    # 我们希望文字为黑色(0) on white(255) or vice versa, pytesseract 可以处理
    # 做一次开闭降低噪点
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2,2))
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, kernel, iterations=1)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kernel, iterations=1)
    # 放大以提高识别（2x）
    th = cv2.resize(th, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    return th

# 主处理流程：给定图片路径或 cv2 图片，返回 (raw_text, cleaned_expr, result)
def solve_captcha(image_path_or_cvimg):
    # 1. 读取图片（支持直接传入 cv2 image）
    if isinstance(image_path_or_cvimg, str):
        img = cv2.imread(image_path_or_cvimg)
        if img is None:
            raise FileNotFoundError(f"can't read {image_path_or_cvimg}")
    else:
        img = image_path_or_cvimg.copy()

    h, w = img.shape[:2]

    # 2. 尝试蓝色分割（优先）
    mask = extract_blue_text_region(img)
    # 如果 mask 面积太小，说明颜色分割失败
    if cv2.countNonZero(mask) > 20:
        # 将 mask 转为三通道图，然后与原图结合提取文字区域
        x,y,wc,hc = cv2.boundingRect(mask)
        # 扩展一点边界
        pad = int(max(3, min(w, h) * 0.02))
        x0 = max(0, x - pad); y0 = max(0, y - pad)
        x1 = min(w, x + wc + pad); y1 = min(h, y + hc + pad)
        crop = img[y0:y1, x0:x1]
        gray_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        proc = preprocess_gray(gray_crop)
    else:
        # 退回：直接对整个图做灰度+预处理（适合你直接裁剪验证码的小图）
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        proc = preprocess_gray(gray)

    # 3. 尝试多种 psm 配置并用白名单限制字符
    whitelist = '0123456789+-*/() '
    configs = [
        f'--psm 7 -c tessedit_char_whitelist={whitelist}',  # single text line
        f'--psm 6 -c tessedit_char_whitelist={whitelist}',  # block of text
        f'--psm 11 -c tessedit_char_whitelist={whitelist}', # sparse text
    ]
    candidates = []
    pil_img = Image.fromarray(proc)
    for cfg in configs:
        raw = pytesseract.image_to_string(pil_img, config=cfg)
        cleaned = clean_ocr_text(raw)
        if cleaned:
            res = safe_eval_simple(cleaned)
        else:
            res = None
        candidates.append((raw, cleaned, res, cfg))

    # 4. 选取最可能的结果：优先有成功解析结果的项，按解析成功与否选择
    for raw, cleaned, res, cfg in candidates:
        if res is not None:
            return raw, cleaned, res, cfg

    # 5. 如果都没解析出结果，返回最“干净”的候选（最长 cleaned）
    candidates.sort(key=lambda x: len(x[1] or ''), reverse=True)
    best = candidates[0]
    return best[0], best[1], best[2], best[3]

# 如果直接运行，示例：
if __name__ == '__main__':
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else 'captcha.png'
    raw, cleaned, result, used_cfg = solve_captcha(path)
    print("raw OCR      :", repr(raw))
    print("cleaned expr :", cleaned)
    print("parsed result:", result)
    print("used config  :", used_cfg)