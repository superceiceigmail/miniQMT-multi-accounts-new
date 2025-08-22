from flask import Flask, request, render_template_string
import threading

app = Flask(__name__)

# 全部账号的上报数据存内存
data = {}

@app.route('/report', methods=['POST'])
def report():
    info = request.json
    account = info.get("account_id", "unknown")
    data[account] = info
    return "OK"

@app.route('/')
def dashboard():
    # 可选：自动刷新页面
    html = """
    <html>
    <head>
        <title>多账号监控面板</title>
        <meta http-equiv="refresh" content="3">
        <style>
            body { font-family: 'Consolas', monospace; }
            table { border-collapse: collapse; }
            td, th { border: 1px solid #ccc; padding: 6px 12px; }
        </style>
    </head>
    <body>
        <h2>账号监控面板</h2>
        <table>
            <tr>
                <th>账号</th>
                <th>状态</th>
                <th>最后上报时间</th>
                <th>日志</th>
            </tr>
            {% for acc, info in data.items() %}
            <tr>
                <td>{{ acc }}</td>
                <td>{{ info.get('status', '-') }}</td>
                <td>{{ info.get('time', '-') }}</td>
                <td><pre style="white-space: pre-wrap;">{{ info.get('log', '-') }}</pre></td>
            </tr>
            {% endfor %}
        </table>
    </body>
    </html>
    """
    return render_template_string(html, data=data)

def run():
    app.run(debug=True, port=5000, host='0.0.0.0')

if __name__ == "__main__":
    run()