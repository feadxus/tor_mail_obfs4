import sys
import subprocess

# 自动安装指定的依赖工具(包括 Python 库和 age 加密工具)
packages = [
    "google-auth-oauthlib",
    "google-api-python-client",
    "age-cli"  # 通过 PyPI 提供的 age 命令行工具打包版
]

print("--> 安装依赖工具...")
subprocess.check_call([sys.executable, "-m", "pip", "install", *packages])
print("--> 所有工具安装完成!")

# 验证 age 是否安装成功
subprocess.check_call(["age", "--version"])
