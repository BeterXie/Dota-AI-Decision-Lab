from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        if new in text:
            return
        raise RuntimeError(f"cleanup marker missing in {path}: {old!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "tests/test_production_lifecycle_replay.py",
        'assert revision == "0028_historical_start_time_provenance"',
        'assert revision == "0029_email_auth"',
    )
    replace_once(
        "tests/test_email_auth.py",
        "engine, _, sender, service = await _auth_fixture()\n",
        "engine, factory, sender, service = await _auth_fixture()\n",
    )
    replace_once(
        "tests/test_email_auth.py",
        "            service._session_factory,  # type: ignore[attr-defined]\n",
        "            factory,\n",
    )
    _insert_i18n()


def _insert_i18n() -> None:
    path = Path("frontend/src/i18n.tsx")
    text = path.read_text(encoding="utf-8")
    if "authLoginTitle:" in text:
        return
    english_marker = '    reviewWinnerTitle: "Winner",\n    selectMatchPrompt:'
    chinese_marker = '    reviewWinnerTitle: "获胜方",\n    selectMatchPrompt:'
    english = '''    reviewWinnerTitle: "Winner",
    authSessionUnavailable: "Unable to verify sign-in state",
    authRetry: "Retry",
    authLoginEyebrow: "Dota AI Decision Lab",
    authLoginTitle: "Sign in with email",
    authLoginDescription: "No password. We’ll send a one-time 6-digit code to your email.",
    authEmailLabel: "Email address",
    authEmailPlaceholder: "you@example.com",
    authSendCode: "Send login code",
    authSending: "Sending…",
    authCodeTitle: "Check your email",
    authCodeDescription: "Enter the 6-digit code sent to",
    authCodeLabel: "Login code",
    authCodePlaceholder: "000000",
    authVerify: "Sign in",
    authVerifying: "Verifying…",
    authChangeEmail: "Use another email",
    authResend: "Resend code",
    authResendIn: "Resend in {seconds}s",
    authCodePrivacy: "The code expires in 10 minutes and can only be used once.",
    authInvalidEmail: "Enter a valid email address.",
    authDeliveryFailed: "We couldn’t send the login email. Check the mail configuration and try again.",
    authInvalidCode: "That code is invalid or expired. Request a new code and try again.",
    authGenericError: "Sign-in failed. Please try again.",
    authSecureSession: "Secure session · HttpOnly cookie · no password stored",
    authCurrentAccount: "Current account",
    authSignOut: "Sign out",
    selectMatchPrompt:'''
    chinese = '''    reviewWinnerTitle: "获胜方",
    authSessionUnavailable: "无法确认登录状态",
    authRetry: "重试",
    authLoginEyebrow: "Dota AI Decision Lab",
    authLoginTitle: "使用邮箱登录",
    authLoginDescription: "无需密码。我们会向你的邮箱发送一个 6 位一次性验证码。",
    authEmailLabel: "邮箱地址",
    authEmailPlaceholder: "you@example.com",
    authSendCode: "发送登录验证码",
    authSending: "正在发送…",
    authCodeTitle: "检查你的邮箱",
    authCodeDescription: "请输入发送到以下邮箱的 6 位验证码",
    authCodeLabel: "登录验证码",
    authCodePlaceholder: "000000",
    authVerify: "登录",
    authVerifying: "正在验证…",
    authChangeEmail: "更换邮箱",
    authResend: "重新发送",
    authResendIn: "{seconds} 秒后可重发",
    authCodePrivacy: "验证码 10 分钟后失效，并且只能使用一次。",
    authInvalidEmail: "请输入有效的邮箱地址。",
    authDeliveryFailed: "登录邮件发送失败，请检查邮件配置后重试。",
    authInvalidCode: "验证码错误或已失效，请重新获取后再试。",
    authGenericError: "登录失败，请稍后重试。",
    authSecureSession: "安全会话 · HttpOnly Cookie · 不保存密码",
    authCurrentAccount: "当前账户",
    authSignOut: "退出",
    selectMatchPrompt:'''
    if english_marker not in text or chinese_marker not in text:
        raise RuntimeError("i18n insertion marker missing")
    text = text.replace(english_marker, english, 1)
    text = text.replace(chinese_marker, chinese, 1)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
