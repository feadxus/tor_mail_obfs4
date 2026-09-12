import os
import sys
import tarfile
import urllib.request
import subprocess

# 1️⃣. 安装 pip 依赖库
pip_packages = [
    "google-auth-oauthlib",
    "google-api-python-client"
]

print("--> 1. 正在安装 Python 依赖库...")
subprocess.check_call([sys.executable, "-m", "pip", "install", *pip_packages])

# 2️⃣. 下载并安装特定版本的 age (v1.3.2)
age_version = "v1.3.2"
url = f"https://github.com/FiloSottile/age/releases/download/{age_version}/age-{age_version}-linux-amd64.tar.gz"
tar_path = "/tmp/age.tar.gz"
extract_dir = "/tmp/age_bin"

print(f"--> 2. 正在从 GitHub 下载 age {age_version}...")
urllib.request.urlretrieve(url, tar_path)

print("--> 正在解压并安装 age 二进制文件...")
os.makedirs(extract_dir, exist_ok=True)
with tarfile.open(tar_path, "r:gz") as tar:
    tar.extractall(path=extract_dir)

# 将解压出来的 age 和 age-keygen 文件复制/移动到 /usr/local/bin/
src_dir = os.path.join(extract_dir, "age")
subprocess.check_call(["sudo", "cp", f"{src_dir}/age", f"{src_dir}/age-keygen", "/usr/local/bin/"])
subprocess.check_call(["sudo", "chmod", "+x", "/usr/local/bin/age", "/usr/local/bin/age-keygen"])

print("--> age 安装完成!")

# 3️⃣. 验证 age 是否成功安装
subprocess.check_call(["age", "--version"])
