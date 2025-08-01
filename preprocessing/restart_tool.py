import sys
import os

def restart_self():
    """
    重启本main.py进程（原地拉起同参数的自己）
    """
    print("正在重启main.py本进程...")
    python = sys.executable
    os.execl(python, python, *sys.argv)