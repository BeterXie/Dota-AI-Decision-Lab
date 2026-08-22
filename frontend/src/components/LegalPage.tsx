import React from "react";
import { LEGAL_CONTACT_EMAIL, PRODUCT_DOMAIN, PRODUCT_NAME } from "../brand";
import { useI18n, type Locale } from "../i18n";
import "./legal-page.css";

export type LegalPageKind = "terms" | "privacy";

interface LegalSection {
  id: string;
  title: string;
  paragraphs?: string[];
  bullets?: string[];
}

interface LegalDocument {
  eyebrow: string;
  title: string;
  intro: string;
  effective: string;
  highlights: Array<{ title: string; text: string }>;
  sections: LegalSection[];
}

export function LegalPage({ kind }: { kind: LegalPageKind }) {
  const { locale } = useI18n();
  const document = legalDocument(kind, locale);
  const relatedHref = kind === "terms" ? "/privacy" : "/terms";
  const relatedLabel = locale === "zh-CN"
    ? kind === "terms" ? "查看隐私政策" : "查看使用条款"
    : kind === "terms" ? "Read the Privacy Policy" : "Read the Terms of Use";

  React.useEffect(() => {
    const previous = window.document.title;
    window.document.title = `${document.title} · ${PRODUCT_NAME}`;
    return () => { window.document.title = previous; };
  }, [document.title]);

  return (
    <div className="legal-page">
      <header className="legal-hero product-container">
        <div className="legal-hero-copy">
          <span className="home-eyebrow">{document.eyebrow}</span>
          <h1>{document.title}</h1>
          <p>{document.intro}</p>
          <div className="legal-effective">
            <span>{locale === "zh-CN" ? "生效日期" : "Effective date"}</span>
            <strong>{document.effective}</strong>
          </div>
        </div>
        <div className="legal-signal" aria-hidden="true">
          <span>DATA</span><span>MODEL</span><span>POINTS</span>
        </div>
      </header>

      <section className="legal-highlights product-container" aria-label={locale === "zh-CN" ? "重要说明" : "Key points"}>
        {document.highlights.map((item) => (
          <article key={item.title}>
            <strong>{item.title}</strong>
            <p>{item.text}</p>
          </article>
        ))}
      </section>

      <div className="legal-layout product-container">
        <nav className="legal-toc" aria-label={locale === "zh-CN" ? "本页目录" : "On this page"}>
          <strong>{locale === "zh-CN" ? "本页目录" : "On this page"}</strong>
          {document.sections.map((section, index) => (
            <a key={section.id} href={`#${section.id}`}><span>{String(index + 1).padStart(2, "0")}</span>{section.title}</a>
          ))}
        </nav>
        <article className="legal-content">
          {document.sections.map((section, index) => (
            <section id={section.id} key={section.id}>
              <div className="legal-section-number">{String(index + 1).padStart(2, "0")}</div>
              <div>
                <h2>{section.title}</h2>
                {section.paragraphs?.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
                {section.bullets && <ul>{section.bullets.map((item) => <li key={item}>{item}</li>)}</ul>}
              </div>
            </section>
          ))}
          <aside className="legal-contact-card">
            <div>
              <span>{locale === "zh-CN" ? "法律与隐私联系" : "Legal and privacy contact"}</span>
              <strong>{LEGAL_CONTACT_EMAIL}</strong>
              <small>{PRODUCT_DOMAIN}</small>
            </div>
            <a href={`mailto:${LEGAL_CONTACT_EMAIL}`}>{locale === "zh-CN" ? "发送邮件" : "Send email"}<span>→</span></a>
          </aside>
          <div className="legal-next-link"><a href={relatedHref}>{relatedLabel}<span>→</span></a></div>
        </article>
      </div>
    </div>
  );
}

function legalDocument(kind: LegalPageKind, locale: Locale): LegalDocument {
  return kind === "terms" ? termsDocument(locale) : privacyDocument(locale);
}

function termsDocument(locale: Locale): LegalDocument {
  if (locale === "zh-CN") {
    return {
      eyebrow: "LEGAL / TERMS",
      title: "使用条款",
      intro: "本条款适用于 DotaScope 网站、账号、赛事数据、AI 预测、预测积分、赛事 Pass 与通知功能。使用服务即表示你接受本条款。",
      effective: "2026 年 8 月 21 日",
      highlights: [
        { title: "赛事分析服务", text: "DotaScope 根据阵容、实时比赛状态、历史与市场数据生成分析和模型预测。" },
        { title: "积分没有现金价值", text: "预测积分不能购买、充值、提现、转让或兑换商品、服务与其他有价物。" },
        { title: "不执行投注", text: "DotaScope 不接受、保管或代为提交投注，也不提供博彩账户或资金结算。" }
      ],
      sections: [
        {
          id: "service",
          title: "服务与条款接受",
          paragraphs: [
            "DotaScope 是独立的 Dota 赛事数据与 AI 预测服务。服务包括赛事目录、阵容与实时状态、模型概率、预测积分、赛后评估、账号权限和可选通知。",
            "你代表自己使用服务，并确认有能力接受本条款。若你不同意本条款，请停止访问账号、预测与付费功能。"
          ]
        },
        {
          id: "eligibility",
          title: "使用资格与账号",
          bullets: [
            "你应年满 18 周岁，或达到所在地法律要求的更高年龄。",
            "你应提供准确的登录信息，并妥善保护邮箱、Steam、Google 及通知渠道账号。",
            "不得共享、出售账号或绕过赛事 Pass、访问控制、速率限制与安全措施。",
            "发现未经授权的账号使用时，应及时停止会话并联系我们。"
          ]
        },
        {
          id: "predictions",
          title: "AI 预测与市场数据",
          paragraphs: [
            "模型输出来自当时可用的数据、质量门和计算过程。数据可能延迟、缺失、冲突或发生更正，任何预测都可能错误。",
            "市场数据仅作为比较基准和模型输入。DotaScope 不保证预测准确率、积分结果、市场可用性或任何现实世界结果。服务内容不构成下注执行、财务建议或收益承诺。"
          ]
        },
        {
          id: "points",
          title: "预测积分",
          bullets: [
            "积分只用于比较模型预测、置信度和长期表现。",
            "积分不能通过付款取得，也不能提现、转让、交易或兑换赛事 Pass、订阅、数字物品、实物或其他利益。",
            "积分结算可引用比赛结果和冻结的市场参考数据；它不会产生平台对用户的债务。",
            "出现数据错误、重复结算、滥用或规则更新时，DotaScope 可以更正、取消或重新计算积分与排名。"
          ]
        },
        {
          id: "paid-access",
          title: "赛事 Pass 与付费访问",
          paragraphs: [
            "赛事 Pass 和系列赛 Pass 是独立于预测积分的内容访问权限。价格、税费、币种、支付方式和最终订单信息以 Paddle 结账页为准。",
            "退款、撤销与强制性消费者权利按照适用法律、结账条款和支付服务商流程处理。退款或权限失效后，相关实时内容与通知可以停止。"
          ]
        },
        {
          id: "notifications",
          title: "通知功能",
          paragraphs: [
            "你可以选择绑定邮箱、QQ 或微信接收有权限查看的比赛通知。通知可能因网络、第三方平台、赛事状态或数据质量而延迟或未送达。你可以在通知设置中关闭渠道。"
          ]
        },
        {
          id: "acceptable-use",
          title: "可接受使用",
          bullets: [
            "不得攻击、探测、干扰服务，批量创建账号或规避访问限制。",
            "不得未经许可复制、转售、镜像或大规模抓取 DotaScope 内容与接口。",
            "不得利用服务实施欺诈、骚扰、侵权或其他违法行为。",
            "不得宣称自己代表 DotaScope、Valve、赛事方、战队或数据提供方。"
          ]
        },
        {
          id: "third-parties",
          title: "知识产权与第三方服务",
          paragraphs: [
            "DotaScope 的软件、界面、原创文字和模型输出受适用知识产权规则保护。Dota、Steam、战队、赛事和第三方标志归各自权利人所有。DotaScope 与 Valve 或赛事方不存在隶属或官方背书关系。",
            "登录、支付、通知与数据功能可能依赖 Google、Steam、Paddle、Resend、QQ、微信及赛事数据提供方。使用这些服务时，其各自条款和隐私规则可能同时适用。"
          ]
        },
        {
          id: "availability",
          title: "服务变更与可用性",
          paragraphs: [
            "赛事数据源、模型、功能和访问方案可能更新、中断或终止。DotaScope 会尽合理努力保持核心数据可审计，但不承诺服务始终无错误或不间断。"
          ]
        },
        {
          id: "liability",
          title: "责任边界",
          paragraphs: [
            "你应自行判断如何使用赛事信息和模型预测。在适用法律允许的范围内，DotaScope 不对基于预测采取的外部行动、第三方服务中断、数据源错误或间接损失承担责任。本条款不排除法律不能排除的消费者权利或责任。"
          ]
        },
        {
          id: "termination",
          title: "暂停、终止与条款更新",
          paragraphs: [
            "违反本条款、安全要求或适用法律时，DotaScope 可以限制或终止账号和功能访问。我们可以更新本条款；重大变更会通过网站、账号界面或可用联系方式提示，并标注新的生效日期。"
          ]
        }
      ]
    };
  }

  return {
    eyebrow: "LEGAL / TERMS",
    title: "Terms of Use",
    intro: "These Terms apply to the DotaScope website, accounts, match data, AI predictions, prediction points, Competition Passes, and notifications. By using the Service, you accept these Terms.",
    effective: "21 August 2026",
    highlights: [
      { title: "Match intelligence", text: "DotaScope uses draft, live match, historical, and market data to produce analysis and model predictions." },
      { title: "Points have no cash value", text: "Prediction points cannot be bought, topped up, withdrawn, transferred, or redeemed for anything of value." },
      { title: "No wager execution", text: "DotaScope does not accept, hold, or place wagers and does not provide gambling accounts or cash settlement." }
    ],
    sections: [
      { id: "service", title: "Service and acceptance", paragraphs: ["DotaScope is an independent Dota match-data and AI-prediction service. It includes event listings, draft and live state, model probabilities, prediction points, post-match evaluation, account access, and optional notifications.", "You use the Service on your own behalf and confirm that you can accept these Terms. If you do not accept them, stop using account, prediction, and paid-access features."] },
      { id: "eligibility", title: "Eligibility and accounts", bullets: ["You must be at least 18 years old, or any higher age required where you live.", "Provide accurate sign-in information and protect your email, Steam, Google, and notification-channel accounts.", "Do not share or sell accounts or bypass Competition Passes, access controls, rate limits, or security measures.", "If you discover unauthorized account use, end the session and contact us promptly."] },
      { id: "predictions", title: "AI predictions and market data", paragraphs: ["Model outputs use the data, quality gates, and computation available at that time. Data can be delayed, missing, conflicting, or corrected, and every prediction can be wrong.", "Market data is an analytical benchmark and model input. DotaScope does not guarantee prediction accuracy, points outcomes, market availability, or any real-world result. The Service does not provide wager execution, financial advice, or a promise of returns."] },
      { id: "points", title: "Prediction points", bullets: ["Points compare model predictions, confidence, and long-run performance.", "Points cannot be obtained by payment and cannot be withdrawn, transferred, traded, or redeemed for passes, subscriptions, digital items, physical goods, or another benefit.", "Points settlement may reference match results and frozen market observations; it creates no debt owed by DotaScope to a user.", "DotaScope may correct, cancel, or recalculate points and rankings after data errors, duplicate settlement, abuse, or a rules update."] },
      { id: "paid-access", title: "Competition Passes and paid access", paragraphs: ["Event and Series Passes are content-access rights separate from prediction points. Prices, taxes, currency, payment methods, and final order details are shown by Paddle at checkout.", "Refunds, reversals, and mandatory consumer rights are handled under applicable law, checkout terms, and the payment provider's process. Related live content and notifications may stop after a refund or access expiry."] },
      { id: "notifications", title: "Notifications", paragraphs: ["You may connect email, QQ, or WeChat to receive alerts for matches your account can access. Alerts can be delayed or undelivered because of networks, third-party platforms, match state, or data quality. You can disable channels in notification settings."] },
      { id: "acceptable-use", title: "Acceptable use", bullets: ["Do not attack, probe, disrupt, bulk-register for, or bypass restrictions on the Service.", "Do not copy, resell, mirror, or scrape DotaScope content or interfaces at scale without permission.", "Do not use the Service for fraud, harassment, infringement, or unlawful activity.", "Do not claim to represent DotaScope, Valve, an event organizer, a team, or a data provider."] },
      { id: "third-parties", title: "Intellectual property and third parties", paragraphs: ["DotaScope software, interface, original copy, and model output are protected under applicable intellectual-property rules. Dota, Steam, team, event, and third-party marks belong to their respective owners. DotaScope is not affiliated with or endorsed by Valve or event organizers.", "Sign-in, payments, notifications, and data features may depend on Google, Steam, Paddle, Resend, QQ, WeChat, and match-data providers. Their own terms and privacy rules may also apply."] },
      { id: "availability", title: "Changes and availability", paragraphs: ["Match-data sources, models, features, and access plans can change, pause, or end. DotaScope uses reasonable efforts to keep core evidence auditable but does not promise uninterrupted or error-free operation."] },
      { id: "liability", title: "Responsibility and liability", paragraphs: ["You decide how to use match information and model predictions. To the extent permitted by law, DotaScope is not responsible for external actions taken from predictions, third-party outages, source-data errors, or indirect loss. These Terms do not exclude consumer rights or liability that the law does not allow us to exclude."] },
      { id: "termination", title: "Suspension, termination, and updates", paragraphs: ["DotaScope may restrict or terminate account and feature access after a breach of these Terms, security requirements, or applicable law. We may update these Terms and will identify a new effective date and provide notice of material changes through the site, account interface, or available contact details."] }
    ]
  };
}

function privacyDocument(locale: Locale): LegalDocument {
  if (locale === "zh-CN") {
    return {
      eyebrow: "LEGAL / PRIVACY",
      title: "隐私政策",
      intro: "本政策说明 DotaScope 在提供账号、赛事分析、付费访问和通知功能时处理哪些个人信息，以及你可以如何管理这些信息。",
      effective: "2026 年 8 月 21 日",
      highlights: [
        { title: "最少必要", text: "我们只处理运行账号、权限、支付、通知、安全和用户选择所需的信息。" },
        { title: "支付信息由 Paddle 处理", text: "DotaScope 保存订单与权限记录，不接收或保存完整银行卡信息。" },
        { title: "不出售个人信息", text: "我们不出售个人信息，也不使用跨站广告追踪来建立用户画像。" }
      ],
      sections: [
        {
          id: "scope",
          title: "适用范围与角色",
          paragraphs: [
            "本政策适用于 DotaScope 网站、账号、赛事 Pass、AI 预测查看、通知中心及相关支持功能。DotaScope 对自身决定如何处理的个人信息负责；第三方服务对其独立处理活动负责。"
          ]
        },
        {
          id: "data-collected",
          title: "我们处理的信息",
          bullets: [
            "账号信息：邮箱、显示名称、头像、登录提供方，以及 Google 或 Steam 返回的稳定账号标识。Steam 登录可能不提供邮箱。",
            "认证与安全信息：一次性验证码状态、会话标识、登录时间、IP 与必要的请求和安全日志。本站不保存用户密码。",
            "产品偏好：语言、关注的赛事、通知开关以及界面或账号选择。",
            "付费访问：Paddle 客户和交易引用、所选 Pass、赛事或系列赛范围、订单状态、退款与权限状态。完整支付卡信息由 Paddle 处理。",
            "通知绑定：经验证的邮箱，以及你主动绑定的 QQ 或微信账号标识、连接状态和投递记录。",
            "联系信息：你主动发送的隐私、法律或支持请求及后续沟通。"
          ]
        },
        {
          id: "use",
          title: "使用目的",
          bullets: [
            "创建和保护账号，发送并验证登录验证码。",
            "提供赛事数据、AI 预测、预测积分、排行榜与赛后评估。",
            "创建和核对付费访问，处理退款后的权限变化。",
            "按你的设置发送邮件、QQ 或微信通知。",
            "防止滥用、调查故障、保障服务和执行使用条款。",
            "履行会计、税务、消费者保护和其他适用法律义务。"
          ]
        },
        {
          id: "local-storage",
          title: "Cookie 与本地存储",
          paragraphs: [
            "登录会话使用带有 HttpOnly 与 SameSite 限制的 Cookie；生产 HTTPS 配置同时启用 Secure。浏览器本地存储用于保存语言和关注赛事等偏好。",
            "这些技术用于登录和产品功能，不用于跨站广告追踪。你可以清除浏览器数据，但这会退出登录或重置本地偏好。"
          ]
        },
        {
          id: "sharing",
          title: "服务提供方与信息共享",
          paragraphs: [
            "我们仅在提供功能、保护服务、完成交易或遵守法律所需的范围内共享信息。当前可能涉及的服务包括：Resend（邮件）、Google 与 Steam（可选登录）、Paddle（结账与账单）、QQ 与微信（可选通知）、托管与基础设施服务。",
            "我们也可能在依法收到有效要求、保护用户与服务安全，或完成经通知的业务重组时披露必要信息。"
          ]
        },
        {
          id: "international",
          title: "跨境处理",
          paragraphs: [
            "DotaScope 使用海外基础设施并依赖可能在不同国家处理数据的服务提供方。我们会根据适用要求选择合同、安全与访问控制措施。使用服务即可能涉及向你所在地之外传输信息。"
          ]
        },
        {
          id: "retention",
          title: "保存期限",
          paragraphs: [
            "我们仅在提供账号和权限、保障安全、处理争议以及履行法律义务所需的期间保存个人信息。登录验证码和临时绑定会话保存较短时间；订单、权限、安全和审计记录可能因会计、防欺诈或法律要求保存更久。",
            "匿名或无法合理关联个人的数据可用于长期的模型质量、可靠性和产品统计。"
          ]
        },
        {
          id: "security",
          title: "信息安全",
          paragraphs: [
            "我们使用访问控制、HttpOnly 会话、签名验证、秘密信息隔离、最小权限和审计记录等措施。任何互联网服务都无法保证绝对安全；如发现与自己账号有关的异常，请及时联系我们。"
          ]
        },
        {
          id: "rights",
          title: "你的选择与权利",
          bullets: [
            "你可以在浏览器中修改语言和关注偏好，在通知中心关闭或解绑通知渠道。",
            "你可以要求访问、更正或删除与账号有关的个人信息，也可以反对或限制特定处理；具体权利取决于适用法律。",
            "部分订单、安全和审计记录可能因法律义务或建立、行使、抗辩法律请求而继续保存。",
            `提交请求时，请使用账号关联邮箱联系 ${LEGAL_CONTACT_EMAIL}。我们可能需要验证身份。`
          ]
        },
        {
          id: "children",
          title: "未成年人",
          paragraphs: [
            "DotaScope 面向年满 18 周岁的用户，不会故意收集未成年人的个人信息。如果你认为未成年人向我们提供了信息，请联系我们处理。"
          ]
        },
        {
          id: "changes",
          title: "政策更新与联系",
          paragraphs: [
            `我们可能根据产品、服务提供方或法律变化更新本政策，并在页面标注新的生效日期。隐私问题和数据请求可发送至 ${LEGAL_CONTACT_EMAIL}。`
          ]
        }
      ]
    };
  }

  return {
    eyebrow: "LEGAL / PRIVACY",
    title: "Privacy Policy",
    intro: "This Policy explains the personal information DotaScope processes for accounts, match intelligence, paid access, and notifications, and how you can manage it.",
    effective: "21 August 2026",
    highlights: [
      { title: "Data minimization", text: "We process information needed to operate accounts, access, payments, notifications, security, and user choices." },
      { title: "Paddle handles payment details", text: "DotaScope stores order and access records but does not receive or store full card details." },
      { title: "No sale of personal information", text: "We do not sell personal information or use cross-site advertising trackers to profile users." }
    ],
    sections: [
      { id: "scope", title: "Scope and roles", paragraphs: ["This Policy applies to the DotaScope website, accounts, Competition Passes, AI-prediction access, Notification Center, and related support. DotaScope is responsible for processing it determines; third-party services are responsible for their independent processing."] },
      { id: "data-collected", title: "Information we process", bullets: ["Account data: email, display name, avatar, sign-in provider, and stable account identifiers returned by Google or Steam. Steam sign-in may not provide an email.", "Authentication and security data: one-time-code state, session identifiers, sign-in time, IP address, and necessary request and security logs. We do not store user passwords.", "Product preferences: language, followed events, notification choices, and interface or account selections.", "Paid access: Paddle customer and transaction references, selected Pass and event or series scope, order state, refunds, and entitlement state. Paddle processes full payment-card data.", "Notification bindings: verified email and identifiers, connection state, and delivery records for QQ or WeChat accounts you choose to connect.", "Contact data: privacy, legal, or support requests you send and related correspondence."] },
      { id: "use", title: "How we use information", bullets: ["Create and protect accounts and send and verify sign-in codes.", "Provide match data, AI predictions, prediction points, leaderboards, and post-match evaluation.", "Create and reconcile paid access and apply entitlement changes after refunds.", "Send email, QQ, or WeChat alerts under your settings.", "Prevent abuse, investigate faults, secure the Service, and enforce the Terms.", "Meet accounting, tax, consumer-protection, and other applicable legal duties."] },
      { id: "local-storage", title: "Cookies and local storage", paragraphs: ["Sign-in uses a session cookie with HttpOnly and SameSite restrictions. Production HTTPS configuration also enables Secure. Browser local storage keeps preferences such as language and followed events.", "These technologies support sign-in and product functions and are not used for cross-site advertising tracking. Clearing browser data can sign you out or reset local preferences."] },
      { id: "sharing", title: "Service providers and disclosures", paragraphs: ["We disclose information only as needed to provide features, protect the Service, complete transactions, or comply with law. Current providers may include Resend for email, Google and Steam for optional sign-in, Paddle for checkout and billing, QQ and WeChat for optional notifications, and hosting and infrastructure providers.", "We may also disclose necessary information in response to a valid legal request, to protect users and the Service, or as part of a notified business reorganization."] },
      { id: "international", title: "International processing", paragraphs: ["DotaScope uses overseas infrastructure and providers that may process data in different countries. We use contractual, security, and access-control measures where applicable. Using the Service may involve transferring information outside your location."] },
      { id: "retention", title: "Retention", paragraphs: ["We retain personal information only while needed for accounts and access, security, dispute handling, and legal duties. Sign-in challenges and temporary pairing sessions are short-lived; order, entitlement, security, and audit records may be retained longer for accounting, fraud prevention, or legal requirements.", "Anonymous data, or data that cannot reasonably be linked to an individual, may be retained for model quality, reliability, and product statistics."] },
      { id: "security", title: "Security", paragraphs: ["We use access controls, HttpOnly sessions, signature verification, secret isolation, least privilege, and audit records. No internet service can guarantee absolute security. Contact us promptly if you notice activity affecting your account."] },
      { id: "rights", title: "Your choices and rights", bullets: ["You can change language and followed-event preferences in your browser and disable or disconnect channels in Notification Center.", "You may request access, correction, or deletion of account-related personal information and may object to or restrict certain processing where applicable law provides those rights.", "Some order, security, and audit records may remain where required by law or needed to establish, exercise, or defend legal claims.", `Use the email associated with your account to contact ${LEGAL_CONTACT_EMAIL}. We may need to verify your identity.`] },
      { id: "children", title: "Children", paragraphs: ["DotaScope is intended for users aged 18 or older and does not knowingly collect personal information from children. Contact us if you believe a child has provided information."] },
      { id: "changes", title: "Changes and contact", paragraphs: [`We may update this Policy as the product, providers, or law changes and will identify a new effective date. Privacy questions and data requests may be sent to ${LEGAL_CONTACT_EMAIL}.`] }
    ]
  };
}
