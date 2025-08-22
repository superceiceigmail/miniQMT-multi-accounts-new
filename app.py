from flask import Flask, request, jsonify
import os
import sys
import json
import subprocess
import threading

app = Flask(__name__)

# 账户配置
ACCOUNT_CONFIG_MAP = {
    "shu": "core_parameters/account/8886006288.json",
    "1234": "core_parameters/account/1234567890.json",
}

account_processes = {}
account_status = {k: "未启动" for k in ACCOUNT_CONFIG_MAP}
account_outputs = {k: "" for k in ACCOUNT_CONFIG_MAP}
main_script = "main.py"

SETTING_PATH = "core_parameters/setting/setting.json"

# ------------------------ 工具函数 ------------------------

def read_output(account_name, proc):
    """持续读取子进程stdout，将日志累计到 account_outputs"""
    try:
        for line in proc.stdout:
            account_outputs[account_name] += line
    except Exception:
        pass
    finally:
        try:
            proc.stdout.close()
        except:
            pass

def start_account_backend(account_name):
    """启动账户进程"""
    if account_name in account_processes and account_processes[account_name].poll() is None:
        return "🟢 运行中", account_outputs[account_name]
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
        account_outputs[account_name] = ""
        t = threading.Thread(target=read_output, args=(account_name, proc), daemon=True)
        t.start()
        return "🟢 运行中", account_outputs[account_name]
    except Exception as e:
        account_status[account_name] = "启动失败"
        return f"🔴 启动失败: {e}", account_outputs[account_name]

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
            return "⚪ 已停止", account_outputs[account_name]
        except Exception as e:
            account_status[account_name] = "停止失败"
            return f"🔴 停止失败: {e}", account_outputs[account_name]
    else:
        account_status[account_name] = "未启动"
        return "⚪ 未启动", account_outputs[account_name]

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
    return account_outputs[account_name]

# ------------------------ 接口路由 ------------------------

@app.route('/setting/save', methods=['POST'])
def save_setting():
    """
    保存 setting.json
    POST body: {"json_text": "<用户粘贴的json字符串>"}
    """
    try:
        data = request.get_json()
        json_text = data.get('json_text', '').strip()
        if not json_text:
            return jsonify({"success": False, "msg": "内容为空"}), 400
        obj = json.loads(json_text)
        os.makedirs(os.path.dirname(SETTING_PATH), exist_ok=True)
        with open(SETTING_PATH, 'w', encoding='utf-8') as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
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
            "output": account_outputs.get(name, "")
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
    status, output = start_account_backend(account_name)
    return jsonify({"success": "运行中" in status, "status": status, "output": output})

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
    status, output = stop_account_backend(account_name)
    return jsonify({"success": "已停止" in status, "status": status, "output": output})

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