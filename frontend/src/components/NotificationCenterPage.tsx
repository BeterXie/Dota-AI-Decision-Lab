import React, { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useI18n } from "../i18n";
import { UiIcon } from "./VisualIdentity";
import {
  bindVerifiedEmail,
  createPairingCode,
  disableNotificationBinding,
  fetchNotificationCenter,
  setNotificationPreference,
  type NotificationBinding,
  type NotificationCenterState,
  type NotificationChannel,
  type PairingCode
} from "../notificationApi";
import "./notification-center.css";

const centerKey = ["notification-center"] as const;
const channels: NotificationChannel[] = ["EMAIL", "QQ", "WECHAT"];

export function NotificationCenterPage({ userEmail }: { userEmail: string | null }) {
  const { locale } = useI18n();
  const queryClient = useQueryClient();
  const [pairing, setPairing] = useState<Partial<Record<"QQ" | "WECHAT", PairingCode>>>({});
  const [copiedChannel, setCopiedChannel] = useState<"QQ" | "WECHAT" | null>(null);
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
            copied={channel === "EMAIL" ? false : copiedChannel === channel}
            busy={bindEmail.isPending || preference.isPending || remove.isPending || pair.isPending}
            error={pair.error instanceof Error && pair.variables === channel ? pair.error.message : null}
            onBindEmail={() => bindEmail.mutate()}
            onPair={(value) => { pair.reset(); pair.mutate(value); }}
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
  copied,
  busy,
  error,
  onBindEmail,
  onPair,
  onCopy,
  onPreference,
  onRemove
}: {
  channel: NotificationChannel;
  state: NotificationCenterState;
  userHasEmail: boolean;
  pairing: PairingCode | undefined;
  copied: boolean;
  busy: boolean;
  error: string | null;
  onBindEmail: () => void;
  onPair: (channel: "QQ" | "WECHAT") => void;
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
            aria-label={`${channel} AI decision alerts`}
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
                  : locale === "zh-CN" ? "在对应机器人私聊中发送这条命令；确认后刷新本页即可看到连接。" : "Send this command in a direct chat with the matching bot, then refresh after confirmation."}
              </small>
              {!pairing.share_url && !pairing.contact_url ? (
                <small className="notification-pairing-missing-entry">
                  {locale === "zh-CN"
                    ? "当前未配置公开机器人入口；请先打开管理员提供的 QQ/微信机器人私聊。"
                    : "No public bot entry is configured; open the direct-chat entry supplied by the administrator first."}
                </small>
              ) : null}
            </div>
          ) : null}
          {error ? <p className="notification-inline-error" role="alert">{error}</p> : null}
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
      ? "每个 QQ 用户单独配对；官方入口会打开同一个机器人，不会把管理员登录态分享给你。"
      : "Pair your own QQ chat. The official entry opens the shared bot without exposing the administrator session.";
  }
  return locale === "zh-CN"
    ? "每个微信私聊单独配对；管理员只负责让机器人在线，不会替普通用户绑定。"
    : "Pair your own WeChat chat. The administrator only keeps the shared bot online; your chat remains your destination.";
}

function formatPairingExpiry(value: string, locale: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return locale === "zh-CN" ? "有效期未知" : "Expiry unknown";
  return `${locale === "zh-CN" ? "有效至" : "Expires"} ${new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en", {
    hour: "2-digit",
    minute: "2-digit"
  }).format(date)}`;
}
