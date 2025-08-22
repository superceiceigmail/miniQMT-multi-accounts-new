from flask import Flask, request, jsonify
import os
import sys
import json
import subprocess
import threading
from datetime import datetime

app = Flask(__name__)

# 账户配置
ACCOUNT_CONFIG_MAP = {
    "shu": "core_parameters/account/8886006288.json",
    "1234": "core_parameters/account/1234567890.json",
}

account_processes = {}
account_status = {k: "未启动" for k in ACCOUNT_CONFIG_MAP}
main_script = "main.py"

SETTING_PATH = "core_parameters/setting/setting.json"

# 日志目录和格式
LOG_DIR = os.path.join(os.getcwd(), "zz_log")
LOG_FILE_FMT = "log_%Y%m%d.log"

# ------------------------ 工具函数 ------------------------

def get_today_log_path():
    day_str = datetime.now().strftime("%Y%m%d")
    return os.path.join(LOG_DIR, f"log_{day_str}.log")

def read_last_lines(log_file, n=200):
    """读取日志文件最后n行"""
    if not os.path.exists(log_file):
        return ""
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        try:
            lines = f.readlines()
            return "".join(lines[-n:])
        except Exception:
            return ""

def start_account_backend(account_name):
    """启动账户进程"""
    if account_name in account_processes and account_processes[account_name].poll() is None:
        return "🟢 运行中"
    cmd = ["python", "-u", main_script, "-a", account_name]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=os.path.abspath(os.path.dirname(main_script)),
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        )
        account_processes[account_name] = proc
        account_status[account_name] = "运行中"
        # 不再单独维护 output
        return "🟢 运行中"
    except Exception as e:
        account_status[account_name] = "启动失败"
        return f"🔴 启动失败: {e}"

def stop_account_backend(account_name):
    """停止账户进程"""
    import psutil
    proc = account_processes.get(account_name)
    if proc and proc.poll() is None:
        try:
            parent = psutil.Process(proc.pid)
            children = parent.children(recursive=True)
            for child in children:
                child.terminate()
            parent.terminate()
            gone, alive = psutil.wait_procs([parent] + children, timeout=10)
            for p in alive:
                p.kill()
            account_status[account_name] = "已停止"
            return "⚪ 已停止"
        except Exception as e:
            account_status[account_name] = "停止失败"
            return f"🔴 停止失败: {e}"
    else:
        account_status[account_name] = "未启动"
        return "⚪ 未启动"

def get_status_backend(account_name):
    proc = account_processes.get(account_name)
    if proc and proc.poll() is None:
        account_status[account_name] = "运行中"
        return "🟢 运行中"
    elif account_status[account_name] not in ("启动失败", "停止失败"):
        account_status[account_name] = "未启动"
        return "⚪ 未启动"
    return f"🔴 {account_status[account_name]}"

def get_output_backend(account_name):
    """
    读取日志文件，从最后一个'===============程序开始执行================'行开始，展示到结尾
    """
    log_file = get_today_log_path()
    if not os.path.exists(log_file):
        return ""
    start_marker = "===============程序开始执行================"
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    # 从最后一行往上找到最新一次start_marker
    marker_idx = None
    for idx in range(len(lines)-1, -1, -1):
        if start_marker in lines[idx]:
            marker_idx = idx
            break
    if marker_idx is not None:
        return "".join(lines[marker_idx:])
    else:
        # 没有分割线就返回最后100行
        return "".join(lines[-100:])

# ------------------------ 接口路由 ------------------------

@app.route('/setting/save', methods=['POST'])
def save_setting():
    """
    保存 setting.json
    POST body: 直接传 json 数据
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "msg": "内容为空"}), 400
        os.makedirs(os.path.dirname(SETTING_PATH), exist_ok=True)
        with open(SETTING_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return jsonify({"success": True, "msg": "保存成功！"})
    except Exception as e:
        return jsonify({"success": False, "msg": f"保存失败: {e}"}), 500

@app.route('/accounts/list', methods=['GET'])
def accounts_list():
    """
    获取所有账户信息及状态
    """
    account_list = []
    for name in ACCOUNT_CONFIG_MAP:
        account_list.append({
            "name": name,
            "status": account_status.get(name, "未知"),
            # 输出只读日志最后N行
            "output": get_output_backend(name)
        })
    return jsonify({"accounts": account_list})

@app.route("/account/start", methods=["POST"])
def api_account_start():
    """
    启动账户进程
    POST body: {"account_name": "shu"}
    """
    data = request.get_json() or {}
    account_name = data.get("account_name")
    if not account_name or account_name not in ACCOUNT_CONFIG_MAP:
        return jsonify({"success": False, "msg": "账户名无效"}), 400
    status = start_account_backend(account_name)
    return jsonify({"success": "运行中" in status, "status": status, "output": get_output_backend(account_name)})

@app.route("/account/stop", methods=["POST"])
def api_account_stop():
    """
    停止账户进程
    POST body: {"account_name": "shu"}
    """
    data = request.get_json() or {}
    account_name = data.get("account_name")
    if not account_name or account_name not in ACCOUNT_CONFIG_MAP:
        return jsonify({"success": False, "msg": "账户名无效"}), 400
    status = stop_account_backend(account_name)
    return jsonify({"success": "已停止" in status, "status": status, "output": get_output_backend(account_name)})

@app.route("/account/status", methods=["GET"])
def api_account_status():
    """
    获取账户运行状态
    GET params: account_name=shu
    """
    account_name = request.args.get("account_name")
    if not account_name or account_name not in ACCOUNT_CONFIG_MAP:
        return jsonify({"success": False, "msg": "账户名无效"}), 400
    status = get_status_backend(account_name)
    return jsonify({"success": True, "status": status})

@app.route("/account/output", methods=["GET"])
def api_account_output():
    """
    获取账户进程输出日志
    GET params: account_name=shu
    """
    account_name = request.args.get("account_name")
    if not account_name or account_name not in ACCOUNT_CONFIG_MAP:
        return jsonify({"success": False, "msg": "账户名无效"}), 400
    output = get_output_backend(account_name)
    return jsonify({"success": True, "output": output})

@app.route("/")
def hello():
    """
    根路径提示
    """
    return (
        "Flask is running! Endpoints:<br>"
        "/accounts/list (GET)<br>"
        "/setting/save (POST)<br>"
        "/account/start (POST)<br>"
        "/account/stop (POST)<br>"
        "/account/status (GET)<br>"
        "/account/output (GET)<br>"
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860, debug=True)