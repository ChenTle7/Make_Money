"""邮件通知 - 发送网格推荐+日报链接到邮箱"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path


def _read_grid_html(date_str: str) -> str:
    """读取网格推荐文档HTML"""
    grid_path = Path(__file__).parent / "reports" / "output" / f"grid-{date_str}.html"
    if grid_path.exists():
        return grid_path.read_text(encoding="utf-8")
    return ""


def _build_text_body(date_str: str, grid_html: str) -> str:
    """从网格HTML中提取纯文本版本"""
    lines = [f"港股ETF日报 {date_str}", "=" * 40, ""]
    if not grid_html:
        lines.append("网格推荐文档未生成")
    else:
        lines.append("网格推荐已生成，详见HTML邮件")
    lines.append("")
    pages_url = os.environ.get("PAGES_URL", "https://chentle7.github.io/Make_Money")
    lines.append(f"查看完整日报: {pages_url}/latest.html")
    return "\n".join(lines)


def send_report_email():
    """发送日报通知邮件"""
    import sys

    # 从环境变量读取配置
    smtp_host = os.environ.get("SMTP_HOST", "smtp.qq.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "465"))
    sender = os.environ.get("SMTP_SENDER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    receiver = os.environ.get("SMTP_RECEIVER", sender)

    print(f"[notify] SMTP_HOST={smtp_host}, SMTP_PORT={smtp_port}")
    print(f"[notify] SENDER={'已配置' if sender else '未配置'}, RECEIVER={'已配置' if receiver else '未配置'}")
    print(f"[notify] PASSWORD={'已配置' if password else '未配置'}")

    if not sender or not password:
        print("[notify] 未配置邮箱，跳过通知")
        return

    date_str = datetime.now().strftime("%Y-%m-%d")
    pages_url = os.environ.get("PAGES_URL", "https://chentle7.github.io/Make_Money")

    # 读取网格推荐
    grid_html = _read_grid_html(date_str)
    print(f"[notify] 网格HTML长度: {len(grid_html)}")

    # 构建邮件
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"港股ETF日报 {date_str}"
    msg["From"] = sender
    msg["To"] = receiver

    # 纯文本版本
    text = _build_text_body(date_str, grid_html)
    msg.attach(MIMEText(text, "plain", "utf-8"))

    # HTML版本 - 网格推荐 + 查看完整日报按钮
    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px;">
        {grid_html}
        <div style="text-align: center; margin: 24px 0;">
            <a href="{pages_url}/latest.html"
               style="display: inline-block; background: #3B82F6; color: white; padding: 12px 28px;
                      border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 15px;">
                查看完整日报
            </a>
            <p style="margin: 12px 0 0; color: #94A3B8; font-size: 13px;">
                完整日报含: 大盘指数 | 市场要闻 | 趋势分析 | K线图表
            </p>
        </div>
        <p style="color: #94A3B8; font-size: 12px; text-align: center; margin-top: 16px;">
            数据仅供参考，不构成投资建议
        </p>
    </div>
    """
    msg.attach(MIMEText(html, "html", "utf-8"))

    # 发送（失败时抛异常让 workflow 报错，方便排查）
    with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
        print(f"[notify] 已连接SMTP服务器")
        server.login(sender, password)
        print(f"[notify] 登录成功")
        server.sendmail(sender, receiver, msg.as_string())
    print(f"[notify] 通知邮件已发送至 {receiver}")


if __name__ == "__main__":
    send_report_email()
