import requests
import time

for i in range(10):
    resp = requests.post(
        'http://localhost:5000/report',
        json={
            "account_id": "test_account_01",
            "status": "运行中",
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "log": f"第{i}次上报，测试日志内容"
        }
    )
    print(resp.text)
    time.sleep(2)