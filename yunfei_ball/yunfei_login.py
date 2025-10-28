# yunfei_ball/yunfei_login.py
# 提取自原来的 yunfei_connect_follow.py 的登录与代理/SSL 处理逻辑。
# 提供 login(username, password, max_retries)、is_logged_in(html_or_session)、kill_and_reset_geph()

import os
import time
import subprocess
from typing import Optional
import requests
from requests.exceptions import SSLError
from bs4 import BeautifulSoup

# 默认常量（与原文件保持一致路径/URL）
LOGIN_URL = 'https://www.ycyflh.com/F2/login.aspx'
BASE_URL = 'https://www.ycyflh.com'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
}

# 默认凭据占位（强烈建议由 GUI/配置注入）
DEFAULT_USERNAME = os.environ.get('YUNFEI_USERNAME', 'ceicei')
DEFAULT_PASSWORD = os.environ.get('YUNFEI_PASSWORD', 'ceicei628')

def get_value_by_name(soup, name):
    tag = soup.find('input', {'name': name})
    return tag['value'] if tag else ''

def is_logged_in(html_or_session) -> bool:
    """
    可传入完整 html 字符串，或 requests.Response, 或 requests.Session（会尝试 GET 主页）
    """
    try:
        if isinstance(html_or_session, str):
            html_text = html_or_session
        elif hasattr(html_or_session, 'text'):
            html_text = html_or_session.text
        else:
            # treat as session
            session = html_or_session
            resp = session.get(BASE_URL + '/F2/b_follow.aspx', headers=HEADERS, timeout=10, proxies={})
            resp.encoding = resp.apparent_encoding
            html_text = resp.text
    except Exception:
        return False
    return ("退出" in html_text or "个人资料" in html_text or "Hi," in html_text)

def kill_and_reset_geph():
    """
    复用原有逻辑：检测到 SSL 错误尝试关闭 geph 并重置系统代理
    """
    try:
        print("检测到SSL错误，尝试关闭迷雾通及重置系统代理！")
        for proc in ["geph4-client.exe", "gephgui-wry.exe", "geph4.exe"]:
            subprocess.run(['taskkill', '/F', '/IM', proc], check=False)
        subprocess.run('netsh winhttp reset proxy', shell=True)
        subprocess.run(
            'reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" /v ProxyServer /f',
            shell=True)
        subprocess.run(
            'reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" /v ProxyEnable /f',
            shell=True)
        print("已关闭所有 geph 进程并重置系统代理设置")
    except Exception as e:
        print("关闭 geph 或重置代理失败:", e)

def login(username: Optional[str] = None, password: Optional[str] = None, max_retries: int = 3) -> Optional[requests.Session]:
    """
    返回已登录的 requests.Session 或 None
    - username/password: 优先使用传入值；若均为 None 则使用环境变量或默认占位
    - max_retries: 如果遇到 SSL 错误，会做少量重试
    """
    if username is None:
        username = DEFAULT_USERNAME
    if password is None:
        password = DEFAULT_PASSWORD

    attempt = 0
    while attempt < max_retries:
        attempt += 1
        session = requests.Session()
        session.trust_env = False
        session.headers.update(HEADERS)
        try:
            resp = session.get(LOGIN_URL, proxies={}, timeout=10)
        except SSLError as e:
            print("遇到SSL错误:", e)
            kill_and_reset_geph()
            time.sleep(5)
            continue
        except Exception as e:
            print("其他网络异常:", e)
            # 若是第一次失败，可以稍等并重试
            time.sleep(1 + attempt)
            continue

        soup = BeautifulSoup(resp.text, 'html.parser')
        viewstate = get_value_by_name(soup, '__VIEWSTATE')
        eventvalidation = get_value_by_name(soup, '__EVENTVALIDATION')
        viewstategen = get_value_by_name(soup, '__VIEWSTATEGENERATOR')
        data = {
            '__VIEWSTATE': viewstate,
            '__EVENTVALIDATION': eventvalidation,
            '__VIEWSTATEGENERATOR': viewstategen,
            'txt_name_2020_byf': username,
            'txt_pwd_2020_byf': password,
            'ckb_UserAgreement': 'on',
            'btn_login': '登 录',
        }
        try:
            login_resp = session.post(LOGIN_URL, data=data, proxies={}, timeout=10)
        except Exception as e:
            print("登录请求异常:", e)
            time.sleep(1 + attempt)
            continue

        if not is_logged_in(login_resp.text):
            print("登录失败，可能用户名密码不正确或页面表单变化。")
            # 不立即重试太多次；上层可决定替换凭据或中止
            time.sleep(1)
            return None

        print("登录成功")
        return session

    print("达到最大重试次数，登录失败。")
    return None