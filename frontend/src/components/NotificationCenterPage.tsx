import React, { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useI18n } from "../i18n";
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
            busy={bindEmail.isPending || preference.isPending || remove.isPending || pair.isPending}
            onBindEmail={() => bindEmail.mutate()}
            onPair={(value) => pair.mutate(value)}
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
  busy,
  onBindEmail,
  onPair,
  onPreference,
  onRemove
}: {
  channel: NotificationChannel;
  state: NotificationCenterState;
  userHasEmail: boolean;
  pairing: PairingCode | undefined;
  busy: boolean;
  onBindEmail: () => void;
  onPair: (channel: "QQ" | "WECHAT") => void;
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
              <span>{locale === "zh-CN" ? "发送给机器人" : "Send to the bot"}</span>
              <code>{pairing.command}</code>
              <small>
                {locale === "zh-CN" ? "10 分钟内有效；机器人确认后此处会出现绑定。" : "Valid for 10 minutes. Refresh after the bot confirms the binding."}
              </small>
            </div>
          ) : null}
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
      ? "生成一次性配对码，只能在 QQ 私聊中发送给机器人完成账号绑定；群聊不支持付费账号绑定。"
      : "Generate a one-time code and send it to the QQ bot in C2C chat. Group chats cannot be bound to a paid account.";
  }
  return locale === "zh-CN"
    ? "生成一次性配对码并发给微信机器人；机器人看到的会话才会成为你的推送目标。"
    : "Generate a one-time code and send it to the WeChat bot; only that verified chat becomes your destination.";
}
