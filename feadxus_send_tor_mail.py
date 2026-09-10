import os
import json
import base64
import time
from datetime import datetime
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ['https://google.com']

def get_credentials_from_secrets():
    """核心修正：完全从系统环境变量加载 JSON 凭据，并支持动态刷新"""
    # 从 GitHub Secrets 映射的环境变量中读取完整的 JSON 字符串
    env_token = os.environ.get("GMAIL_TOKEN_JSON_FEADXUS")
    if not env_token:
        raise Exception("❌ 错误：未在环境中检测到 GMAIL_TOKEN_JSON_FEADXUS。请检查 GitHub Secrets 配置！")
    
    try:
        token_info = json.loads(env_token)
    except Exception as e:
        raise Exception(f"❌ 错误：Secrets 中的 JSON 格式不正确，解析失败: {e}")
        
    # 重构为谷歌官方支持的 Credentials 对象
    creds = Credentials(
        token=token_info.get("token"),
        refresh_token=token_info.get("refresh_token"),
        token_uri=token_info.get("token_uri"),
        client_id=token_info.get("client_id"),
        client_secret=token_info.get("client_secret"),
        scopes=SCOPES
    )

    # 在内存中自动刷新已过期的 Access Token
    if creds.expired and creds.refresh_token:
        print("🔄 检测到 Access Token 已过期，正在利用 Refresh Token 自动刷新...")
        creds.refresh(Request())
        print("✅ Access Token 刷新成功，继续执行后续任务。")
                
    return creds

def fetch_tor_reply(service, start_time):
    """【收信闭环】等待并自动抓取 Tor 官方发回的网桥邮件"""
    print("⏳ 正在等待 Tor 官方的回信（预计需要 15-30 秒，请保持耐心）...")
    
    # 循环尝试 6 次，每次间隔 10 秒（共计等待 1 分钟）
    for attempt in range(1, 7):
        time.sleep(10)
        print(f"🔍 第 {attempt} 次尝试检索未读回信...")
        
        # 过滤条件：来自 torproject、在脚本启动之后收到、且为未读邮件
        query = f"from:bridges@torproject.org after:{int(start_time)} is:unread"
        try:
            results = service.users().messages().list(userId='me', q=query).execute()
            messages = results.get('messages', [])
            
            if messages:
                # 获取最新收到的一封邮件内容
                msg_id = messages[0]['id']
                message = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
                
                # 解码提取邮件纯文本正文
                payload = message.get('payload', {})
                parts = payload.get('parts', [])
                body = ""
                
                if parts:
                    for part in parts:
                        if part.get('mimeType') == 'text/plain':
                            body = base64.urlsafe_b64decode(part['body']['data'].encode('ASCII')).decode('utf-8')
                            break
                else:
                    body = base64.urlsafe_b64decode(payload['body']['data'].encode('ASCII')).decode('utf-8')
                
                print("\n================ 🎉 成功获取最新 Tor 网桥节点 ================")
                # 遍历行，精准筛选出带有网桥数据的行并直接打印在 GitHub Actions 日志里
                found_bridge = False
                for line in body.split('\n'):
                    if "obfs4 " in line:
                        print(line.strip())
                        found_bridge = True
                
                if not found_bridge:
                    # 如果过滤失败，打印前几行防止出错
                    print("未能自动过滤出 obfs4 特征行，邮件原文前 300 字如下：")
                    print(body[:300])
                print("=========================================================\n")
                
                # 【防污染】成功读取后，自动将该邮件标记为已读，防止下次拉取到重复数据
                service.users().messages().batchModify(
                    userId='me', 
                    body={'ids': [msg_id], 'removeLabelIds': ['UNREAD']}
                ).execute()
                print("🗑️ 已自动将该邮件标记为已读。")
                return
                
        except Exception as e:
            print(f"⚠️ 检索回信时发生异常: {e}")
            
    print("❌ 超过 1 分钟仍未收到 Tor 的回信，可能是官方系统延迟，请稍后去您的 Gmail 收件箱查看。")

def main():
    start_timestamp = time.time()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. 纯内存安全认证
    creds = get_credentials_from_secrets()
    service = build('gmail', 'v1', credentials=creds)

    # 2. 规范化组装 Tor 申请邮件
    msg = EmailMessage()
    msg["To"] = "bridges@torproject.org"
    msg["From"] = "feadxus@gmail.com" # 确保此邮箱与您申请 OAuth2 令牌的邮箱完全一致
    msg["Subject"] = "get transport obfs4"
    msg.set_content("get transport obfs4")

    # 3. 编码并安全发送
    encoded_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    create_message = {"raw": encoded_message}

    try:
        sent_msg = service.users().messages().send(userId="me", body=create_message).execute()
        print(f"[{now_str}] ✅ 成功向 Tor 官方邮箱提交申请。邮件 ID: {sent_msg['id']}")
        
        # 4. 触发闭环收信监听
        fetch_tor_reply(service, start_timestamp)
        
    except Exception as e:
        print(f"[{now_str}] ❌ 流程中断，发生错误: {e}")

if __name__ == '__main__':
    main()
