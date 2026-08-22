import React, { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import QRCode from "qrcode";
import { useI18n } from "../i18n";
import { UiIcon } from "./VisualIdentity";
import {
  bindVerifiedEmail,
  cancelQrBinding,
  createPairingCode,
  disableNotificationBinding,
  fetchNotificationCenter,
  pollQrBinding,
  setNotificationPreference,
  startQrBinding,
  type NotificationBinding,
  type NotificationCenterState,
  type NotificationChannel,
  type PairingCode,
  type QrBindingSession
} from "../notificationApi";
import "./notification-center.css";

const centerKey = ["notification-center"] as const;
const channels: NotificationChannel[] = ["EMAIL", "QQ", "WECHAT"];

export function NotificationCenterPage({ userEmail }: { userEmail: string | null }) {
  const { locale } = useI18n();
  const queryClient = useQueryClient();
  const [pairing, setPairing] = useState<Partial<Record<"QQ" | "WECHAT", PairingCode>>>({});
  const [qrBinding, setQrBinding] = useState<Partial<Record<"QQ" | "WECHAT", QrBindingSession>>>({});
  const [qrErrors, setQrErrors] = useState<Partial<Record<"QQ" | "WECHAT", string>>>({});
  const [verifyCodes, setVerifyCodes] = useState<Partial<Record<"QQ" | "WECHAT", string>>>({});
  const [copiedChannel, setCopiedChannel] = useState<"QQ" | "WECHAT" | null>(null);
  const qrTimers = useRef(new Map<string, number>());
  const qrPolling = useRef(new Set<string>());
  const center = useQuery({
    queryKey: centerKey,
    queryFn: fetchNotificationCenter,
    refetchInterval: 15_000
  });
  const bindEmail = useMutation({
    mutationFn: bindVerifiedEmail,
    onSuccess: (data) => queryClient.setQueryData(centerKey, data)
  });
  const preference = useMutation({
    mutationFn: ({ channel, enabled }: { channel: NotificationChannel; enabled: boolean }) =>
      setNotificationPreference(channel, enabled),
    onSuccess: (data) => queryClient.setQueryData(centerKey, data)
  });
  const remove = useMutation({
    mutationFn: disableNotificationBinding,
    onSuccess: (data) => queryClient.setQueryData(centerKey, data)
  });
  const pair = useMutation({
    mutationFn: (channel: "QQ" | "WECHAT") => createPairingCode(channel),
    onSuccess: (data) => setPairing((current) => ({ ...current, [data.channel]: data }))
  });

  const scheduleQrPoll = (session: QrBindingSession) => {
    if (["BOUND", "FAILED", "EXPIRED", "CANCELLED", "NEED_VERIFY_CODE"].includes(session.status)) return;
    const key = `${session.channel}:${session.session_id}`;
    if (qrTimers.current.has(key) || qrPolling.current.has(key)) return;
    const timer = window.setTimeout(async () => {
      qrTimers.current.delete(key);
      qrPolling.current.add(key);
      try {
        const next = await pollQrBinding(session.channel, session.session_id);
        setQrBinding((current) => ({ ...current, [next.channel]: next }));
        setQrErrors((current) => ({ ...current, [next.channel]: undefined }));
        if (next.status === "BOUND") {
          await center.refetch();
        } else {
          scheduleQrPoll(next);
        }
      } catch (error) {
        setQrErrors((current) => ({
          ...current,
          [session.channel]: error instanceof Error ? error.message : String(error)
        }));
      } finally {
        qrPolling.current.delete(key);
      }
    }, session.status === "SCANNED" ? 800 : 1600);
    qrTimers.current.set(key, timer);
  };

  useEffect(() => () => {
    qrTimers.current.forEach((timer) => window.clearTimeout(timer));
    qrTimers.current.clear();
    qrPolling.current.clear();
  }, []);

  const beginQrBinding = async (channel: "QQ" | "WECHAT") => {
    [...qrTimers.current.keys()]
      .filter((key) => key.startsWith(`${channel}:`))
      .forEach((key) => {
        const timer = qrTimers.current.get(key);
        if (timer !== undefined) window.clearTimeout(timer);
        qrTimers.current.delete(key);
      });
    setQrErrors((current) => ({ ...current, [channel]: undefined }));
    try {
      const session = await startQrBinding(channel);
      setQrBinding((current) => ({ ...current, [channel]: session }));
      scheduleQrPoll(session);
    } catch (error) {
      setQrErrors((current) => ({
        ...current,
        [channel]: error instanceof Error ? error.message : String(error)
      }));
    }
  };

  const submitVerifyCode = async (channel: "QQ" | "WECHAT") => {
    const session = qrBinding[channel];
    if (!session) return;
    try {
      const next = await pollQrBinding(channel, session.session_id, verifyCodes[channel]);
      setQrBinding((current) => ({ ...current, [channel]: next }));
      setVerifyCodes((current) => ({ ...current, [channel]: "" }));
      if (next.status === "BOUND") await center.refetch();
      else scheduleQrPoll(next);
    } catch (error) {
      setQrErrors((current) => ({
        ...current,
        [channel]: error instanceof Error ? error.message : String(error)
      }));
    }
  };

  const stopQrBinding = async (channel: "QQ" | "WECHAT") => {
    const session = qrBinding[channel];
    if (!session) return;
    [...qrTimers.current.keys()]
      .filter((key) => key.startsWith(`${channel}:`))
      .forEach((key) => {
        const timer = qrTimers.current.get(key);
        if (timer !== undefined) window.clearTimeout(timer);
        qrTimers.current.delete(key);
      });
    try {
      const next = await cancelQrBinding(channel, session.session_id);
      setQrBinding((current) => ({ ...current, [channel]: next }));
    } catch (error) {
      setQrErrors((current) => ({
        ...current,
        [channel]: error instanceof Error ? error.message : String(error)
      }));
    }
  };

  const copyCommand = async (value: PairingCode) => {
    try {
      if (!navigator.clipboard) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(value.command);
      setCopiedChannel(value.channel);
      window.setTimeout(() => setCopiedChannel((current) => current === value.channel ? null : current), 1800);
    } catch {
      setCopiedChannel(null);
    }
  };

  if (center.isLoading) {
    return <div className="notification-page"><div className="notification-loading">Notification Center…</div></div>;
  }
  if (center.error || !center.data) {
    return (
      <div className="notification-page">
        <section className="notification-hero">
          <a className="notification-back" href="/">← {locale === "zh-CN" ? "返回首页" : "Back home"}</a>
          <h1>Notification Center</h1>
          <p role="alert">{locale === "zh-CN" ? "通知设置加载失败，请刷新重试。" : "Failed to load notification settings."}</p>
        </section>
      </div>
    );
  }

  const state = center.data;
  return (
    <div className="notification-page">
      <section className="notification-hero">
        <div>
          <a className="notification-back" href="/">← {locale === "zh-CN" ? "返回首页" : "Back home"}</a>
          <div className="notification-eyebrow">REALTIME NOTIFICATIONS</div>
          <h1>Notification Center</h1>
          <p>
            {locale === "zh-CN"
              ? "选择你希望接收比赛提醒的渠道。发送前会再次检查账号权限，失效的 Pass 不会继续收到付费通知。"
              : "Choose where match alerts should reach you. Pass access is checked again before each paid notification is delivered."}
          </p>
        </div>
        <div className="notification-account">
          <span>{locale === "zh-CN" ? "当前账号" : "Account"}</span>
          <strong>{userEmail || (locale === "zh-CN" ? "尚未绑定邮箱" : "No email linked")}</strong>
        </div>
      </section>

      <section className="notification-grid" aria-label="Notification channels">
        {channels.map((channel) => (
          <ChannelCard
            key={channel}
            channel={channel}
            state={state}
            userHasEmail={Boolean(userEmail)}
            pairing={channel === "EMAIL" ? undefined : pairing[channel]}
            qrBinding={channel === "EMAIL" ? undefined : qrBinding[channel]}
            copied={channel === "EMAIL" ? false : copiedChannel === channel}
            busy={bindEmail.isPending || preference.isPending || remove.isPending || pair.isPending}
            error={pair.error instanceof Error && pair.variables === channel ? pair.error.message : null}
            qrError={channel === "EMAIL" ? null : qrErrors[channel] || null}
            onBindEmail={() => bindEmail.mutate()}
            onPair={(value) => { pair.reset(); pair.mutate(value); }}
            onStartQr={beginQrBinding}
            onSubmitVerify={submitVerifyCode}
            onCancelQr={stopQrBinding}
            verifyCode={channel === "EMAIL" ? "" : verifyCodes[channel] || ""}
            onVerifyCodeChange={(value) => channel !== "EMAIL" && setVerifyCodes((current) => ({ ...current, [channel]: value }))}
            onCopy={copyCommand}
            onPreference={(value, enabled) => preference.mutate({ channel: value, enabled })}
            onRemove={(bindingId) => remove.mutate(bindingId)}
          />
        ))}
      </section>

      <section className="notification-history">
        <div className="notification-section-heading">
          <div>
            <div className="notification-eyebrow">DELIVERY LEDGER</div>
            <h2>{locale === "zh-CN" ? "最近推送" : "Recent deliveries"}</h2>
          </div>
          <button type="button" onClick={() => void center.refetch()}>
            {locale === "zh-CN" ? "刷新" : "Refresh"}
          </button>
        </div>
        {state.recent_deliveries.length === 0 ? (
          <p className="notification-empty">{locale === "zh-CN" ? "还没有推送记录。" : "No deliveries yet."}</p>
        ) : (
          <div className="notification-delivery-list">
            {state.recent_deliveries.map((delivery) => (
              <div className="notification-delivery-row" key={delivery.id}>
                <span className={`notification-status status-${delivery.status.toLowerCase()}`}>{delivery.status}</span>
                <strong>{channelLabel(delivery.channel, locale)}</strong>
                <span>{new Date(delivery.created_at).toLocaleString()}</span>
                {delivery.last_error ? <span title={delivery.last_error}>{delivery.last_error}</span> : null}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function ChannelCard({
  channel,
  state,
  userHasEmail,
  pairing,
  qrBinding,
  copied,
  busy,
  error,
  qrError,
  onBindEmail,
  onPair,
  onStartQr,
  onSubmitVerify,
  onCancelQr,
  verifyCode,
  onVerifyCodeChange,
  onCopy,
  onPreference,
  onRemove
}: {
  channel: NotificationChannel;
  state: NotificationCenterState;
  userHasEmail: boolean;
  pairing: PairingCode | undefined;
  qrBinding: QrBindingSession | undefined;
  copied: boolean;
  busy: boolean;
  error: string | null;
  qrError: string | null;
  onBindEmail: () => void;
  onPair: (channel: "QQ" | "WECHAT") => void;
  onStartQr: (channel: "QQ" | "WECHAT") => void;
  onSubmitVerify: (channel: "QQ" | "WECHAT") => void;
  onCancelQr: (channel: "QQ" | "WECHAT") => void;
  verifyCode: string;
  onVerifyCodeChange: (value: string) => void;
  onCopy: (pairing: PairingCode) => void;
  onPreference: (channel: NotificationChannel, enabled: boolean) => void;
  onRemove: (bindingId: string) => void;
}) {
  const { locale } = useI18n();
  const bindings = state.bindings.filter((item) => item.channel === channel && item.status === "ACTIVE");
  const enabled = state.preferences[channel] ?? true;
  return (
    <article className="notification-channel-card">
      <header>
        <div>
          <div className="notification-channel-code">{channel}</div>
          <h2>{channelLabel(channel, locale)}</h2>
        </div>
        <label className="notification-toggle">
          <input
            aria-label={`${channel} AI prediction alerts`}
            type="checkbox"
            checked={enabled}
            disabled={busy}
            onChange={(event) => onPreference(channel, event.target.checked)}
          />
          <span>{enabled ? (locale === "zh-CN" ? "开启" : "On") : (locale === "zh-CN" ? "关闭" : "Off")}</span>
        </label>
      </header>

      <p className="notification-channel-description">{channelDescription(channel, locale, userHasEmail)}</p>
      <div className="notification-binding-list">
        {bindings.map((binding) => (
          <BindingRow key={binding.id} binding={binding} busy={busy} onRemove={onRemove} />
        ))}
      </div>
      <div className={`notification-binding-state ${bindings.length > 0 ? "is-active" : "is-empty"}`}>
        <span className="notification-state-dot" aria-hidden="true" />
        <span>
          {bindings.length > 0
            ? locale === "zh-CN" ? "已连接此渠道" : "Channel connected"
            : locale === "zh-CN" ? "尚未连接" : "Not connected"}
        </span>
      </div>

      {channel === "EMAIL" ? (
        <button
          className="notification-primary"
          type="button"
          disabled={busy || bindings.length > 0 || !userHasEmail}
          onClick={onBindEmail}
        >
          {bindings.length > 0
            ? locale === "zh-CN" ? "已绑定验证邮箱" : "Verified email bound"
            : !userHasEmail
              ? locale === "zh-CN" ? "先绑定邮箱" : "Link an email first"
              : locale === "zh-CN" ? "绑定登录邮箱" : "Bind login email"}
        </button>
      ) : (
        <div className="notification-pairing">
          <button
            className="notification-primary"
            type="button"
            disabled={busy || Boolean(qrBinding && !["FAILED", "EXPIRED", "CANCELLED", "BOUND"].includes(qrBinding.status))}
            onClick={() => onStartQr(channel)}
          >
            {locale === "zh-CN" ? "扫码绑定独立账号" : "Scan to bind your account"}
          </button>
          {qrBinding ? (
            <QrBindingPanel
              session={qrBinding}
              verifyCode={verifyCode}
              onVerifyCodeChange={onVerifyCodeChange}
              onSubmitVerify={() => onSubmitVerify(channel)}
              onCancel={() => onCancelQr(channel)}
              locale={locale}
            />
          ) : null}
          {qrError ? <p className="notification-inline-error" role="alert">{qrError}</p> : null}
          <details className="notification-manual-fallback">
             <summary>{locale === "zh-CN" ? "旧共享机器人迁移（新用户请勿使用）" : "Migrate a legacy shared bot (new users should scan)"}</summary>
          <button className="notification-primary" type="button" disabled={busy} onClick={() => onPair(channel)}>
            {locale === "zh-CN" ? "生成配对码" : "Generate pairing code"}
          </button>
          {pairing ? (
            <div className="notification-pairing-code" role="status">
              <div className="notification-pairing-heading">
                <span>{locale === "zh-CN" ? "完成此会话配对" : "Finish this chat pairing"}</span>
                <time dateTime={pairing.expires_at}>{formatPairingExpiry(pairing.expires_at, locale)}</time>
              </div>
              <div className="notification-pairing-actions">
                {pairing.share_url || pairing.contact_url ? (
                  <a
                    className="notification-contact-link"
                    href={pairing.share_url || pairing.contact_url || "#"}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    <span>{pairing.share_url ? (locale === "zh-CN" ? "打开 QQ 添加机器人" : "Open QQ and add bot") : (locale === "zh-CN" ? "打开机器人入口" : "Open bot entry")}</span>
                    <UiIcon name="launch" size={16} />
                  </a>
                ) : null}
                <button
                  className="notification-copy-button"
                  type="button"
                  onClick={() => onCopy(pairing)}
                  aria-label={locale === "zh-CN" ? "复制配对命令" : "Copy pairing command"}
                >
                  <UiIcon name={copied ? "check" : "copy"} size={16} />
                  {copied ? (locale === "zh-CN" ? "已复制" : "Copied") : (locale === "zh-CN" ? "复制命令" : "Copy command")}
                </button>
              </div>
              <code>{pairing.command}</code>
              <small>
                {channel === "QQ" && pairing.share_url
                  ? locale === "zh-CN" ? "打开官方入口后，机器人会把配对码带入好友申请；无需管理员再次扫码。" : "The official invite carries this code into the friend request; the admin does not scan again."
                   : locale === "zh-CN" ? "仅迁移旧共享机器人：在对应机器人私聊中发送命令。新用户请关闭此项并使用上方扫码。" : "Legacy migration only: send this command to the existing shared bot. New users should use the QR flow above."}
              </small>
              {!pairing.share_url && !pairing.contact_url ? (
                <small className="notification-pairing-missing-entry">
                  {locale === "zh-CN"
                     ? "旧共享机器人入口未配置；新用户无需添加机器人，直接使用上方扫码。"
                     : "No legacy shared-bot entry is configured; new users do not need to add a bot and should use the QR flow above."}
                </small>
              ) : null}
            </div>
          ) : null}
          {error ? <p className="notification-inline-error" role="alert">{error}</p> : null}
          </details>
        </div>
      )}
    </article>
  );
}

function BindingRow({
  binding,
  busy,
  onRemove
}: {
  binding: NotificationBinding;
  busy: boolean;
  onRemove: (bindingId: string) => void;
}) {
  const { locale } = useI18n();
  return (
    <div className="notification-binding-row">
      <div>
        <strong>{binding.label || destinationLabel(binding)}</strong>
        <span>{destinationLabel(binding)}</span>
      </div>
      <button type="button" disabled={busy} onClick={() => onRemove(binding.id)}>
        {locale === "zh-CN" ? "解除" : "Remove"}
      </button>
    </div>
  );
}

function QrBindingPanel({
  session,
  verifyCode,
  onVerifyCodeChange,
  onSubmitVerify,
  onCancel,
  locale
}: {
  session: QrBindingSession;
  verifyCode: string;
  onVerifyCodeChange: (value: string) => void;
  onSubmitVerify: () => void;
  onCancel: () => void;
  locale: string;
}) {
  const active = !["BOUND", "FAILED", "EXPIRED", "CANCELLED"].includes(session.status);
  return (
    <div className={`notification-qr-panel qr-${session.status.toLowerCase()}`} role="status">
      {session.qrcode_url && active ? (
        <QrCodeImage
          value={session.qrcode_url}
          alt={locale === "zh-CN" ? "扫码绑定账号" : "Scan to bind account"}
          locale={locale}
        />
      ) : null}
      <div className="notification-qr-copy">
        <strong>
          {session.status === "BOUND"
            ? locale === "zh-CN" ? "账号已绑定" : "Account bound"
            : session.status === "NEED_VERIFY_CODE"
              ? locale === "zh-CN" ? "需要验证码" : "Verification code required"
              : session.status === "FAILED" || session.status === "EXPIRED"
                ? locale === "zh-CN" ? "扫码未完成" : "QR binding did not complete"
                : locale === "zh-CN" ? "请用自己的手机扫码" : "Scan with your own phone"}
        </strong>
        <span>{session.message || (locale === "zh-CN" ? "二维码有效期 5 分钟" : "QR code expires in 5 minutes")}</span>
        <time dateTime={session.expires_at}>{formatPairingExpiry(session.expires_at, locale)}</time>
        {session.status === "NEED_VERIFY_CODE" ? (
          <div className="notification-qr-verify">
            <input
              value={verifyCode}
              onChange={(event) => onVerifyCodeChange(event.target.value)}
              placeholder={locale === "zh-CN" ? "输入验证码" : "Verification code"}
              inputMode="numeric"
            />
            <button type="button" onClick={onSubmitVerify} disabled={!verifyCode.trim()}>
              {locale === "zh-CN" ? "确认" : "Confirm"}
            </button>
          </div>
        ) : null}
        {active ? (
          <button type="button" className="notification-copy-button" onClick={onCancel}>
            {locale === "zh-CN" ? "取消扫码" : "Cancel"}
          </button>
        ) : null}
      </div>
    </div>
  );
}

function QrCodeImage({
  value,
  alt,
  locale
}: {
  value: string;
  alt: string;
  locale: string;
}) {
  const [source, setSource] = useState<string | null>(null);
  const isImageUrl = value.startsWith("data:image/") || value.startsWith("blob:") ||
    /\.(?:png|jpe?g|webp)(?:[?#].*)?$/i.test(value);

  useEffect(() => {
    let cancelled = false;
    if (isImageUrl) {
      setSource(value);
      return () => {
        cancelled = true;
      };
    }
    setSource(null);
    void QRCode.toDataURL(value, {
      width: 280,
      margin: 2,
      errorCorrectionLevel: "M"
    }).then((dataUrl) => {
      if (!cancelled) setSource(dataUrl);
    }).catch(() => {
      if (!cancelled) setSource(null);
    });
    return () => {
      cancelled = true;
    };
  }, [isImageUrl, value]);

  return source ? (
    <img className="notification-qr-image" src={source} alt={alt} />
  ) : (
    <div className="notification-qr-placeholder" role="img" aria-label={alt}>
      {locale === "zh-CN" ? "正在生成二维码…" : "Generating QR code…"}
    </div>
  );
}

function destinationLabel(binding: NotificationBinding): string {
  if (binding.channel === "EMAIL") return binding.destination.email || "Email";
  if (binding.channel === "QQ") return `${binding.destination.scope || "QQ"} · ${binding.destination.target_id || "bound"}`;
  return `${binding.destination.account_id || "WeChat"} · ${binding.destination.user_id || "bound"}`;
}

function channelLabel(channel: NotificationChannel, locale: string): string {
  if (channel === "EMAIL") return locale === "zh-CN" ? "邮件" : "Email";
  if (channel === "QQ") return "QQ Bot";
  return locale === "zh-CN" ? "微信机器人" : "WeChat Bot";
}

function channelDescription(
  channel: NotificationChannel,
  locale: string,
  userHasEmail: boolean
): string {
  if (channel === "EMAIL") {
    if (!userHasEmail) {
      return locale === "zh-CN"
        ? "Steam 登录不会生成虚假邮箱。绑定并验证邮箱后，才可以开启邮件通知。"
        : "Steam sign-in does not fabricate an email address. Link and verify one before enabling email alerts.";
    }
    return locale === "zh-CN"
      ? "使用当前账号已验证的登录邮箱，不允许填写未验证地址。"
      : "Uses the verified sign-in email for this account; arbitrary addresses are not accepted.";
  }
  if (channel === "QQ") {
    return locale === "zh-CN"
      ? "每个账号独立扫码绑定 QQ Bot，通知直接发送到你扫码的 QQ 账号。"
      : "Bind your own QQ Bot by QR code; alerts go directly to the account you scan.";
  }
  return locale === "zh-CN"
    ? "每个账号独立扫码绑定微信 ClawBot，通知直接发送到你扫码的微信账号。"
    : "Bind your own WeChat ClawBot by QR code; alerts go directly to the account you scan.";
}

function formatPairingExpiry(value: string, locale: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return locale === "zh-CN" ? "有效期未知" : "Expiry unknown";
  return `${locale === "zh-CN" ? "有效至" : "Expires"} ${new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en", {
    hour: "2-digit",
    minute: "2-digit"
  }).format(date)}`;
}
