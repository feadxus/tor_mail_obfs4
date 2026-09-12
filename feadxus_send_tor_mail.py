#!/home/tor/.python-env/bin/python

import os
import json
import time
import email
import base64
import shutil
import subprocess
from abc import ABC, abstractmethod
from email import policy
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# ==========================================
# 1. 配置管理模块 (Config)
# ==========================================
class Config:
    SCOPES = ['https://mail.google.com/']
    BASE_DIR = Path(__file__).resolve().parent
    OUTPUT_DIR = BASE_DIR / 'tor_bridges'
    
    # 目标邮件地址
    TARGET_EMAIL = "bridges@torproject.org"
    # 我的邮箱地址
    SENDER_EMAIL = "feadxus@gmail.com"
    # 邮件标题
    REQUEST_SUBJECT = "get transport obfs4"
    # 邮件正文
    REQUEST_BODY = "get transport obfs4"
    
    POLL_INTERVAL = 10  # 轮询间隔(秒)
    MAX_RETRIES = 6     # 最大重试次数


# ==========================================
# 2. 身份认证与 Client 模块 (Auth)
# ==========================================
class GmailAuthManager:
    """负责从环境变量读取 Token,并在内存中刷新与构建 Gmail Service"""
    
    @staticmethod
    def get_service():
        creds = GmailAuthManager._load_credentials_from_env()

        # 内存中自动刷新 Token(无需写回本地文件)
        if creds and creds.expired and creds.refresh_token:
            print("🔄 Access Token 已过期,正在自动刷新...")
            creds.refresh(Request())
            print("✅ Access Token 刷新成功.")

        if not creds or not creds.valid:
            raise RuntimeError("❌ 未找到有效的凭据,请检查环境变量 GOOGLE_FEADXUS_GMAIL 是否配置正确.")

        return build('gmail', 'v1', credentials=creds)

    @staticmethod
    def _load_credentials_from_env():
        # Gmail 环境变量令牌
        env_token_str = os.environ.get("GOOGLE_FEADXUS_GMAIL")

        if not env_token_str:
            return None

        token_info = json.loads(env_token_str)
        return Credentials(
            token=token_info.get("token"),
            refresh_token=token_info.get("refresh_token"),
            token_uri=token_info.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_info.get("client_id"),
            client_secret=token_info.get("client_secret"),
            scopes=Config.SCOPES
        )


# ==========================================
# 3. 邮件导出与提取工具类 (Exporter)
# ==========================================
class EmailExporter:
    """负责将邮件提取为 eml/txt/附件文件"""
    
    @staticmethod
    def export_message(service, msg_id: str, save_dir: Path) -> Path:
        save_dir.mkdir(parents=True, exist_ok=True)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

        raw_msg = service.users().messages().get(userId='me', id=msg_id, format='raw').execute()
        raw_bytes = base64.urlsafe_b64decode(raw_msg['raw'].encode('ASCII'))

        # 1. 保存完整的 .eml
        eml_file = save_dir / f"tor_bridge_{timestamp_str}_{msg_id}.eml"
        eml_file.write_bytes(raw_bytes)
        print(f"💾 邮件原始文件已保存: {eml_file.resolve()}")

        # 2. 解析正文与附件
        parsed_msg = email.message_from_bytes(raw_bytes, policy=policy.default)
        for part in parsed_msg.walk():
            content_disposition = str(part.get("Content-Disposition", ""))
            content_type = part.get_content_type()

            if "attachment" in content_disposition or part.get_filename():
                filename = part.get_filename()
                if filename:
                    attachment_path = save_dir / f"{timestamp_str}_{filename}"
                    payload = part.get_payload(decode=True)
                    if payload:
                        attachment_path.write_bytes(payload)
                        print(f"🖼️ 附件/图片已提取保存: {attachment_path.resolve()}")

            elif content_type == "text/plain" and "attachment" not in content_disposition:
                body_text = part.get_payload(decode=True).decode(
                    part.get_content_charset() or 'utf-8', errors='ignore'
                )
                text_file = save_dir / f"tor_bridge_{timestamp_str}_{msg_id}.txt"
                text_file.write_text(body_text, encoding="utf-8")
                print(f"📝 邮件正文文本已导出: {text_file.resolve()}")

        return eml_file


# ==========================================
# 4. 工作流基类与步骤定义 (Workflow Steps)
# ==========================================
class WorkflowContext:
    """工作流上下文:用于在各个步骤间传递数据"""
    def __init__(self, service):
        self.service = service
        self.start_timestamp = time.time()
        self.sent_msg_id = None
        self.received_msg_ids = []


class Step(ABC):
    """抽象步骤接口"""
    @abstractmethod
    def execute(self, ctx: WorkflowContext) -> bool:
        pass


class SendTorRequestStep(Step):
    """步骤 1: 发送 Bridge 申请邮件"""
    def execute(self, ctx: WorkflowContext) -> bool:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = EmailMessage()
        msg["To"] = Config.TARGET_EMAIL
        msg["From"] = Config.SENDER_EMAIL
        msg["Subject"] = Config.REQUEST_SUBJECT
        msg.set_content(Config.REQUEST_BODY)

        encoded_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        create_message = {"raw": encoded_message}

        sent_msg = ctx.service.users().messages().send(userId="me", body=create_message).execute()
        ctx.sent_msg_id = sent_msg['id']
        print(f"[{now_str}] ✅ 已成功向 Tor 发送申请邮件.Message ID: {ctx.sent_msg_id}")
        return True


class PollAndProcessTorReplyStep(Step):
    """步骤 2: 监听 Tor 回信、保存并删除"""
    def execute(self, ctx: WorkflowContext) -> bool:
        print(f"⏳ 开始监听 Tor 官方回信 (保存目录: {Config.OUTPUT_DIR})...")
        query = f"from:{Config.TARGET_EMAIL} after:{int(ctx.start_timestamp)} is:unread"

        for attempt in range(1, Config.MAX_RETRIES + 1):
            time.sleep(Config.POLL_INTERVAL)
            print(f"🔍 第 {attempt} 次轮询检索: {query}")

            try:
                results = ctx.service.users().messages().list(userId='me', q=query).execute()
                messages = results.get('messages', [])

                if messages:
                    print("🎉 匹配到 Tor 官方回信!")
                    for msg_meta in messages:
                        msg_id = msg_meta['id']
                        EmailExporter.export_message(ctx.service, msg_id, Config.OUTPUT_DIR)
                        ctx.service.users().messages().delete(userId='me', id=msg_id).execute()
                        print(f"🗑️ 邮件 [{msg_id}] 已从 Gmail 彻底删除,清理完毕.")
                        ctx.received_msg_ids.append(msg_id)
                    return True

            except Exception as e:
                print(f"⚠️ 检索过程遇到异常: {e}")

        print("❌ 超过等待时长,未查收到匹配的 Tor 回信.")
        return False


class CompressAndEncryptStep(Step):
    """步骤 3: 打包压缩并用 age 加密"""
    def __init__(self, age_public_key: str):
        self.age_public_key = age_public_key

    def execute(self, ctx: WorkflowContext) -> bool:
        if not Config.OUTPUT_DIR.exists() or not any(Config.OUTPUT_DIR.iterdir()):
            print("⚠️ 文件夹不存在或为空,跳过压缩加密步骤.")
            return True

        date_str = datetime.now().strftime("%Y-%m-%d")
        output_filename = f"feadxus-gmail-{date_str}.tar.xz.age"
        output_filepath = Config.BASE_DIR / output_filename

        folder_to_compress = Config.OUTPUT_DIR.name

        cmd = (
            f"tar -cJf - -C '{Config.BASE_DIR}' '{folder_to_compress}' | "
            f"age -r '{self.age_public_key}' > '{output_filepath}'"
        )

        print(f"📦 正在打包压缩并加密文件夹 [{folder_to_compress}] -> {output_filename}...")

        try:
            subprocess.run(cmd, shell=True, check=True, cwd=Config.BASE_DIR)
            print(f"🔒 压缩加密完成!生成文件: {output_filepath.resolve()}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"❌ 压缩加密失败: {e}")
            return False


class UploadToGoogleDriveStep(Step):
    """步骤 4: 使用 rclone 上传至 Google Drive(具备自动建目录、自动重试与完整日志捕获)"""
    def __init__(self, remote_path: str = "FEADXUS-Google-Drive:/Gmail/"):
        self.remote_path = remote_path

    def execute(self, ctx: WorkflowContext) -> bool:
        # 1. 检查 rclone 是否安装
        if not shutil.which("rclone"):
            print("⚠️ 未检测到 rclone 命令，跳过 Google Drive 上传步骤。")
            return True

        # 2. 检查待上传文件是否存在
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_filename = f"feadxus-gmail-{date_str}.tar.xz.age"
        local_file = Config.BASE_DIR / output_filename

        if not local_file.exists():
            print(f"⚠️ 未找到待上传的文件 [{output_filename}]，跳过上传。")
            return True

        # 3. 健壮性增强 A:上传前自动检查并创建远程文件夹
        mkdir_cmd = f"rclone mkdir '{self.remote_path}'"
        print(f"📁 确保远程文件夹存在 -> {self.remote_path}")
        subprocess.run(mkdir_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 4. 健壮性增强 B:带有自动重试机制与详细日志捕获的上传命令
        # --retries 3: 网络抖动时自动重试 3 次；-v: 打印传输进度
        upload_cmd = f"rclone copy '{local_file}' '{self.remote_path}' --retries 3 -v"
        print(f"☁️ 正在上传文件到 Google Drive -> {self.remote_path}...")

        try:
            result = subprocess.run(
                upload_cmd,
                shell=True,
                check=True,
                capture_output=True,
                text=True
            )
            print(result.stdout)
            print(f"🎉 成功上传 [{output_filename}] 到 {self.remote_path}")
            return True

        except subprocess.CalledProcessError as e:
            print(f"❌ 上传至 Google Drive 失败 (退出状态码: {e.returncode})")
            print(f"📄 错误详情 (stderr):\n{e.stderr}")
            return False


# ==========================================
# 5. 流程调度管道 (Pipeline Runner)
# ==========================================
class TorBridgeWorkflow:
    def __init__(self, service):
        self.ctx = WorkflowContext(service)
        self.steps = []

    def add_step(self, step: Step):
        self.steps.append(step)
        return self

    def run(self):
        for index, step in enumerate(self.steps, start=1):
            step_name = step.__class__.__name__
            print(f"\n▶️ [Step {index}] 开始执行: {step_name}")
            success = step.execute(self.ctx)
            if not success:
                print(f"⛔ [Step {index}] 执行失败,终止后续流程.")
                return False
        print("\n✨ 所有步骤成功执行完成!")
        return True


# ==========================================
# 6. 主程序入口
# ==========================================
def main():
    try:
        service = GmailAuthManager.get_service()

        # 支持优先从环境变量读取 Age 公钥,若无则使用默认值
        AGE_PUBLIC_KEY = os.environ.get("AGE_PUBLIC_KEY", "age12qrn9as9d4z3glr09w8sn293ywxxgfehjpr74kavm4ut0esj29aqzcwmf8")

        workflow = TorBridgeWorkflow(service)
        workflow.add_step(SendTorRequestStep()) \
                .add_step(PollAndProcessTorReplyStep()) \
                .add_step(CompressAndEncryptStep(age_public_key=AGE_PUBLIC_KEY)) \
                .add_step(UploadToGoogleDriveStep(remote_path="FEADXUS-Google-Drive:/Gmail/"))

        workflow.run()

    except Exception as e:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now_str}] ❌ 运行抛出未捕获异常: {e}")


if __name__ == '__main__':
    main()
