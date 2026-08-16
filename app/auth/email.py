from uuid import UUID

from app.notifications.email import OutgoingEmail, ResendEmailSender


class ResendLoginCodeSender:
    def __init__(
        self,
        *,
        api_key: str,
        sender_from: str,
        base_url: str,
        timeout_seconds: float,
        subject_prefix: str = "[Dota AI Decision Lab]",
    ) -> None:
        self._sender = ResendEmailSender(
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
        self._sender_from = sender_from
        self._subject_prefix = subject_prefix

    async def send_login_code(
        self,
        *,
        email: str,
        code: str,
        challenge_id: UUID,
        ttl_seconds: int,
    ) -> None:
        minutes = max(1, (ttl_seconds + 59) // 60)
        subject = f"{self._subject_prefix} 登录验证码"
        text_body = (
            "Dota AI Decision Lab 登录验证码\n\n"
            f"验证码：{code}\n"
            f"有效期：{minutes} 分钟\n\n"
            "如果不是你本人发起登录，请忽略这封邮件。"
        )
        html_body = f"""<!doctype html>
<html lang="zh-CN">
<body style="margin:0;background:#f4f4f4;color:#161616;font-family:Arial,sans-serif">
<div style="max-width:560px;margin:32px auto;background:#fff;border-radius:16px;overflow:hidden">
<div style="padding:24px;background:#161616;color:#fff">
<div style="font-size:13px;color:#aaa">Dota AI Decision Lab</div>
<h1 style="margin:8px 0 0;font-size:22px">登录验证码</h1>
</div>
<div style="padding:28px">
<p style="margin-top:0">使用下面的验证码完成登录：</p>
<div style="font-size:34px;font-weight:700;letter-spacing:8px;margin:24px 0">{code}</div>
<p>验证码将在 {minutes} 分钟后失效。</p>
<p style="color:#666;font-size:13px">如果不是你本人发起登录，请忽略这封邮件。</p>
</div>
</div>
</body>
</html>"""
        await self._sender.send(
            OutgoingEmail(
                sender=self._sender_from,
                recipients=(email,),
                subject=subject,
                text_body=text_body,
                html_body=html_body,
                idempotency_key=f"email-login/{challenge_id}",
            )
        )

    async def close(self) -> None:
        await self._sender.close()
