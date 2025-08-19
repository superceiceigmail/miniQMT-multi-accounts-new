import gradio as gr
import subprocess
import threading
import psutil
import json
import os



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

def read_output(account_name, proc):
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

def start_account(account_name):
    if account_name in account_processes and account_processes[account_name].poll() is None:
        return "🟢 运行中", account_outputs[account_name]
    cmd = ["python", "-u", main_script, "-a", account_name]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        account_processes[account_name] = proc
        account_status[account_name] = "运行中"
        account_outputs[account_name] = ""
        t = threading.Thread(target=read_output, args=(account_name, proc), daemon=True)
        t.start()
        return "🟢 运行中", account_outputs[account_name]
    except Exception as e:
        account_status[account_name] = "启动失败"
        return f"🔴 启动失败: {e}", account_outputs[account_name]

def stop_account(account_name):
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

def get_status(account_name):
    proc = account_processes.get(account_name)
    if proc and proc.poll() is None:
        account_status[account_name] = "运行中"
        return "🟢 运行中"
    elif account_status[account_name] not in ("启动失败", "停止失败"):
        account_status[account_name] = "未启动"
        return "⚪ 未启动"
    return f"🔴 {account_status[account_name]}"

def get_output(account_name):
    return account_outputs[account_name]

def refresh_all():
    return [get_status(account) for account in ACCOUNT_CONFIG_MAP] + [get_output(account) for account in ACCOUNT_CONFIG_MAP]

def save_setting(json_text):
    try:
        data = json.loads(json_text)
        os.makedirs(os.path.dirname(SETTING_PATH), exist_ok=True)
        with open(SETTING_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return gr.update(value=""), "保存成功！"
    except Exception as e:
        return gr.update(), f"保存失败: {e}"

with gr.Blocks() as demo:
    gr.Markdown("### 多账户 miniQMT 管理（每账号一栏 横向排版）")

    with gr.Row():
        refresh_btn = gr.Button("刷新全部状态和输出")
        # 设置输入框初始高度较低，max_lines=20
        setting_input = gr.Textbox(label="粘贴setting.json内容", lines=2, max_lines=20)
        save_btn = gr.Button("保存setting.json", visible=True)
        save_status = gr.Markdown("")

    status_boxes = {}
    output_boxes = {}

    with gr.Row():
        for account in ACCOUNT_CONFIG_MAP:
            with gr.Column():
                gr.Markdown(f"**账户：{account}**")
                status_md = gr.Markdown(get_status(account))
                start_btn = gr.Button("启动")
                stop_btn = gr.Button("停止")
                output_box = gr.Textbox(get_output(account), label="后台输出", lines=4, interactive=False)
                status_boxes[account] = status_md
                output_boxes[account] = output_box
                start_btn.click(start_account, inputs=[gr.State(account)], outputs=[status_md, output_box])
                stop_btn.click(stop_account, inputs=[gr.State(account)], outputs=[status_md, output_box])

    refresh_btn.click(
        refresh_all,
        outputs=list(status_boxes.values()) + list(output_boxes.values())
    )

    # 输入框有内容才显示保存按钮（美观体验）
    def on_input_change(text):
        return gr.update(visible=bool(text.strip()))
    setting_input.change(on_input_change, inputs=setting_input, outputs=[save_btn])

    save_btn.click(save_setting, inputs=[setting_input], outputs=[setting_input, save_status])

if __name__ == "__main__":
    demo.launch(server_port=7860)