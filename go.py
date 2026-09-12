import sys
import subprocess

# 1. 安装 pip 依赖库
pip_packages = [
    "google-auth-oauthlib",
    "google-api-python-client"
]

print("--> 1. 正在安装 Python 依赖库...")
subprocess.check_call([sys.executable, "-m", "pip", "install", *pip_packages])

# 2. 通过 apt 安装原生的 age 工具
print("--> 2. 正在安装 system 工具 (age)...")
subprocess.check_call(["sudo", "apt-get", "update", "-qq"])
subprocess.check_call(["sudo", "apt-get", "install", "-y", "age"])

print("--> 所有依赖和工具安装完成!")

# 3. 验证 age 是否成功安装
subprocess.check_call(["age", "--version"])
