"""Seed the org library with a ready-to-use "send-email" SMTP tool.

Creates the tool through the full governance chain (create → submit →
review approve → org credentials → enable) so it lands in the same state
as one configured via the UI. Idempotent: re-running refreshes the
definition/credentials and re-enables.

Usage:
    SEED_EMAIL_PASSWORD='xxx' uv run python scripts/seed_email_tool.py

Credentials other than the password (host/port/username/from) come from
the defaults below and may be overridden by env vars of the same name
upper-cased with a ``SEED_EMAIL_`` prefix.
"""
import asyncio
import os
import sys

from app.db.mongodb import close_mongodb_client, get_database
from app.services.user_tool_service import UserToolError, UserToolService
from loguru import logger

TOOL_NAME = "send-email"

DESCRIPTION = "通过组织 SMTP 邮箱发送邮件（支持多个收件人，逗号分隔；正文纯文本）"

# 凭证默认值按邮件配置表单落地；密码只从环境变量读取，不落盘。
CREDENTIALS = {
    "from_addr": os.environ.get("SEED_EMAIL_FROM_ADDR", "elena_fu@amaxgs.com"),
    "smtp_host": os.environ.get("SEED_EMAIL_SMTP_HOST", "mail.amaxgs.com"),
    "smtp_port": os.environ.get("SEED_EMAIL_SMTP_PORT", "587"),
    "username": os.environ.get("SEED_EMAIL_USERNAME", "elena_fu@amaxgs.com"),
    "password": os.environ.get("SEED_EMAIL_PASSWORD", ""),
}

USER_ARGS_SCHEMA = {
    "type": "object",
    "properties": {
        "from_addr": {
            "type": "string",
            "description": "默认发件人邮箱",
        },
        "smtp_host": {
            "type": "string",
            "description": "邮件服务器地址",
        },
        "smtp_port": {
            "type": "string",
            "description": "邮件服务器端口（465 SSL / 587 STARTTLS）",
        },
        "username": {
            "type": "string",
            "description": "邮件登录用户名",
        },
        "password": {
            "type": "string",
            "description": "邮件登录密码",
            "sensitive": True,
        },
    },
    "required": ["from_addr", "smtp_host", "smtp_port", "username", "password"],
}

LLM_ARGS_SCHEMA = {
    "type": "object",
    "properties": {
        "to": {"type": "string", "description": "收件人邮箱，多个用英文逗号分隔"},
        "subject": {"type": "string", "description": "邮件主题"},
        "body": {"type": "string", "description": "邮件正文（纯文本）"},
    },
    "required": ["to", "subject", "body"],
}

# 凭证经 USER_ 前缀环境变量注入（无沙箱 fallback 与沙箱路径语义一致）。
CODE = '''
import os
import smtplib
from email.header import Header
from email.mime.text import MIMEText


def run(to: str, subject: str, body: str) -> str:
    """通过配置的 SMTP 账号发送邮件。"""
    host = os.environ.get("USER_smtp_host", "")
    port = int(os.environ.get("USER_smtp_port", "587") or 587)
    username = os.environ.get("USER_username", "")
    password = os.environ.get("USER_password", "")
    from_addr = os.environ.get("USER_from_addr") or username

    recipients = [a.strip() for a in to.split(",") if a.strip()]
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = from_addr
    msg["To"] = ",".join(recipients)

    # 465 → SMTP_SSL；587 → STARTTLS；其余端口按服务器明文握手
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        server.ehlo()
        if port == 587:
            server.starttls()
            server.ehlo()
    try:
        server.login(username, password)
        server.sendmail(from_addr, recipients, msg.as_string())
    finally:
        server.quit()
    return "邮件已发送：%s → %s（主题：%s）" % (from_addr, ",".join(recipients), subject)
'''


async def main() -> None:
    if not CREDENTIALS["password"]:
        sys.exit("缺少邮件密码：请通过 SEED_EMAIL_PASSWORD 环境变量传入，不落盘。")

    admin = await get_database()["users"].find_one({"role": "admin"}, {"_id": 1})
    if admin is None:
        sys.exit("未找到 admin 用户，无法执行审查/配置/开启。")
    admin_id = admin["_id"]

    existing = await UserToolService.find_by_name(TOOL_NAME)
    if existing is None:
        doc = await UserToolService.create_tool(
            admin_id,
            name=TOOL_NAME,
            description=DESCRIPTION,
            source="code",
            user_args_schema=USER_ARGS_SCHEMA,
            llm_args_schema=LLM_ARGS_SCHEMA,
            code=CODE,
            tags=["email", "smtp"],
        )
        tool_id = doc["id"]
        await UserToolService.submit_for_review(admin_id, tool_id)
        await UserToolService.review_tool(tool_id, "approve", reviewer=admin_id)
        logger.info("send-email tool created via governance chain: {}", tool_id)
    else:
        # 幂等刷新：更新定义（含 code/schema），治理态由下方统一收敛
        tool_id = existing["_id"]
        from app.models.base import utc_now

        await UserToolService._col().update_one(
            {"_id": tool_id},
            {"$set": {
                "description": DESCRIPTION,
                "user_args_schema": USER_ARGS_SCHEMA,
                "llm_args_schema": LLM_ARGS_SCHEMA,
                "code": CODE,
                "updated_at": utc_now().isoformat(),
            }},
        )
        logger.info("send-email tool refreshed: {}", tool_id)

    await UserToolService.save_org_args(admin_id, tool_id, CREDENTIALS)
    doc = await UserToolService.enable_tool(admin_id, tool_id, True)

    print(f"✅ send-email 就绪：{tool_id} status={doc['status']} enabled={doc['enabled']}")
    print("   可在 Agent 绑定 / 工作流工具节点中选择「send-email」。")
    await close_mongodb_client()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except UserToolError as e:
        sys.exit(f"种子失败：{e.message}")
