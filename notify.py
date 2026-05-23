"""邮件通知 - 发送日报链接到邮箱"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime


def send_report_email():
    """发送日报通知邮件"""
    # 从环境变量读取配置
    smtp_host = os.environ.get("SMTP_HOST", "smtp.qq.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "465"))
    sender = os.environ.get("SMTP_SENDER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    receiver = os.environ.get("SMTP_RECEIVER", sender)

    if not sender or not password:
        print("未配置邮箱，跳过通知")
        return

    date_str = datetime.now().strftime("%Y-%m-%d")
    pages_url = os.environ.get("PAGES_URL", "https://chentle7.github.io/Make_Money")

    # 构建邮件
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"港股ETF日报 {date_str}"
    msg["From"] = sender
    msg["To"] = receiver

    # 纯文本版本
    text = f"港股ETF日报已生成，点击查看: {pages_url}/latest.html"

    # HTML版本
    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #0F172A, #1E293B); border-radius: 12px; padding: 24px; color: #F0F4F8;">
            <h2 style="margin: 0 0 8px; color: #F0F4F8;">港股ETF日报</h2>
            <p style="margin: 0 0 20px; color: #94A3B8; font-size: 14px;">{date_str}</p>
            <a href="{pages_url}/latest.html"
               style="display: inline-block; background: #3B82F6; color: white; padding: 12px 28px;
                      border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 15px;">
                查看日报
            </a>
            <p style="margin: 20px 0 0; color: #64748B; font-size: 12px;">
                包含: 大盘指数 | 市场要闻 | 11只ETF分析 | 网格参数建议
            </p>
        </div>
        <p style="color: #94A3B8; font-size: 12px; text-align: center; margin-top: 16px;">
            数据仅供参考，不构成投资建议
        </p>
    </div>
    """

    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    # 发送
    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(sender, password)
            server.sendmail(sender, receiver, msg.as_string())
        print(f"通知邮件已发送至 {receiver}")
    except Exception as e:
        print(f"邮件发送失败: {e}")


if __name__ == "__main__":
    send_report_email()
