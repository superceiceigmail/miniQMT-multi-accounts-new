import subprocess
import logging
import os
from datetime import datetime

def push_project_to_github(project_path, commit_msg="auto push by scheduler"):
    logging.info(f"--- Git自动推送任务 --- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    original_cwd = os.getcwd()
    try:
        os.chdir(project_path)
        subprocess.run(["git", "pull"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "add", "."], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "commit", "-m", commit_msg], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "push"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logging.info("✅ miniQMT-frontend 已自动推送到 GitHub")
    except subprocess.CalledProcessError as e:
        logging.error(f"❌ Git命令执行失败: {e}\nstdout: {e.stdout.decode('utf-8', errors='ignore')}\nstderr: {e.stderr.decode('utf-8', errors='ignore')}")
    except Exception as e:
        logging.error(f"❌ push_project_to_github 异常: {e}")
    finally:
        os.chdir(original_cwd)