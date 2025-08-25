import gradio as gr
import requests
import json
import os

# ========================
# 修改这里为你的 Flask 服务地址
BASE_URL = "http://127.0.0.1:7860"
ACCOUNT_CONFIG_MAP = {
    "shu": "core_parameters/account/8886006288.json",
    "1234": "core_parameters/account/1234567890.json",
}
# ========================

def get_accounts_list():
    """获取所有账户状态和输出"""
    try:
        resp = requests.get(f"{BASE_URL}/accounts/list", timeout=3)
        data = resp.json()
        return data.get("accounts", [])
    except Exception as e:
        # 返回空状态
        return [{"name": k, "status": "接口异常", "output": ""} for k in ACCOUNT_CONFIG_MAP]

def start_account(account_name):
    try:
        resp = requests.post(f"{BASE_URL}/account/start", json={"account_name": account_name}, timeout=8)
        data = resp.json()
        return data.get("status", "未知"), data.get("output", "")
    except Exception as e:
        return f"❌ 启动接口异常: {e}", ""

def stop_account(account_name):
    try:
        resp = requests.post(f"{BASE_URL}/account/stop", json={"account_name": account_name}, timeout=8)
        data = resp.json()
        return data.get("status", "未知"), data.get("output", "")
    except Exception as e:
        return f"❌ 停止接口异常: {e}", ""

def get_status(account_name):
    try:
        resp = requests.get(f"{BASE_URL}/account/status", params={"account_name": account_name}, timeout=4)
        data = resp.json()
        return data.get("status", "未知")
    except Exception as e:
        return f"接口异常: {e}"

def get_output(account_name):
    try:
        resp = requests.get(f"{BASE_URL}/account/output", params={"account_name": account_name}, timeout=4)
        data = resp.json()
        return data.get("output", "")
    except Exception as e:
        return f"接口异常: {e}"

def refresh_all():
    accounts = get_accounts_list()
    status_list = [acc["status"] for acc in accounts]
    output_list = [acc["output"] for acc in accounts]
    return status_list + output_list

"""
def save_setting(json_text):
    try:
        obj = json.loads(json_text)
    except Exception as e:
        return gr.update(), f"不是合法的JSON: {e}"
    try:
        resp = requests.post(f"{BASE_URL}/setting/save", json=obj, timeout=6)
        data = resp.json()
        if data.get("success"):
            return gr.update(value=""), "保存成功！"
        return gr.update(), f"保存失败: {data.get('msg', '')}"
    except Exception as e:
        return gr.update(), f"保存接口异常: {e}"
"""
def save_setting(json_text):
    try:
        obj = json.loads(json_text)
    except Exception as e:
        return gr.update(), f"不是合法的JSON: {e}"
    try:
        save_path = os.path.abspath("core_parameters/setting/setting.json")
        # 自动创建目录（如果不存在）
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        return gr.update(value=""), f"保存成功！文件路径：{save_path}"
    except Exception as e:
        return gr.update(), f"保存文件异常: {e}"

with gr.Blocks() as demo:
    gr.Markdown("### 多账户 miniQMT 管理（每账号一栏 横向排版，所有操作走后端接口）")

    with gr.Row():
        refresh_btn = gr.Button("刷新全部状态和输出")
        setting_input = gr.Textbox(label="粘贴setting.json内容", lines=2, max_lines=20)
        save_btn = gr.Button("保存setting.json", visible=True)
        save_status = gr.Markdown("")

    # 动态控件
    status_boxes = {}
    output_boxes = {}

    # 取一次初始状态，确定账户列表顺序
    init_accounts = get_accounts_list()
    account_names = [acc["name"] for acc in init_accounts] if init_accounts else list(ACCOUNT_CONFIG_MAP.keys())

    with gr.Row():
        for idx, account in enumerate(account_names):
            with gr.Column():
                gr.Markdown(f"**账户：{account}**")
                # 初始状态和输出
                status_md = gr.Markdown(get_status(account))
                start_btn = gr.Button("启动")
                stop_btn = gr.Button("停止")
                output_box = gr.Textbox(get_output(account), label="后台输出", lines=4, interactive=False)
                status_boxes[account] = status_md
                output_boxes[account] = output_box
                start_btn.click(start_account, inputs=[gr.State(account)], outputs=[status_md, output_box])
                stop_btn.click(stop_account, inputs=[gr.State(account)], outputs=[status_md, output_box])

    # 刷新全部
    refresh_btn.click(
        refresh_all,
        outputs=[*status_boxes.values(), *output_boxes.values()]
    )

    def on_input_change(text):
        return gr.update(visible=bool(text.strip()))
    setting_input.change(on_input_change, inputs=setting_input, outputs=[save_btn])

    save_btn.click(save_setting, inputs=[setting_input], outputs=[setting_input, save_status])

if __name__ == "__main__":
    demo.launch(server_port=7861, show_api=False)