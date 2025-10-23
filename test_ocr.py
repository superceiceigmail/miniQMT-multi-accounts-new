from PIL import Image
import pytesseract
import shutil, sys, os

print("Python:", sys.executable)
print("Pillow version:", Image.__version__)
print("pytesseract import ok:", hasattr(pytesseract, "__version__") or True)

# 如果没有把 tesseract 加入 PATH，请取消下一行并按你电脑实际路径修改
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

print("tesseract on PATH (shutil.which):", shutil.which("tesseract"))

try:
    # get_tesseract_version() 需要 pytesseract >= 某版本，若抛出异常可忽略
    print("tesseract version (via pytesseract):", pytesseract.get_tesseract_version())
except Exception as e:
    print("get_tesseract_version() failed:", e)

# 小 OCR 测试（需把 test.jpg 放在同目录或修改路径）
img = "test.jpg"
if os.path.exists(img):
    try:
        text = pytesseract.image_to_string(Image.open(img), lang="eng")
        print("\nOCR result:\n", text)
    except Exception as e:
        print("运行 OCR 时出错：", e)
else:
    print(f"\n未找到测试图片 {img}。请放一张名为 test.jpg 的图片到此目录，或修改脚本中的 img 路径。")