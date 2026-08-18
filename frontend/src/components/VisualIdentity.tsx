import React from "react";
import {
  Calendar,
  Checkmark,
  Group,
  Layers,
  Language,
  Locked,
  Logout,
  MagicWand,
  Menu,
  Notification,
  Star,
  Ticket,
  Time,
  Trophy,
  User
} from "@carbon/icons-react";
import type { MapSummary } from "../api";
import { useTeamDirectory } from "../teamDirectoryApi";
import { teamHref } from "../teams";
import {
  eventAbbreviation,
  getOfficialEventArtwork,
  getOfficialTeamLogoUrl,
  getValveTeamLogoUrl,
  teamAbbreviation
} from "../utils/officialVisuals";

type TeamIdentity = MapSummary["team_a"];
type VisualSize = "sm" | "md" | "lg" | "hero";

type IconName =
  | "ai"
  | "calendar"
  | "check"
  | "clock"
  | "layers"
  | "language"
  | "lock"
  | "logout"
  | "menu"
  | "notification"
  | "spark"
  | "star"
  | "ticket"
  | "trophy"
  | "user"
  | "users";

export const TeamCrest: React.FC<{
  team: TeamIdentity;
  fallbackName?: string;
  size?: Exclude<VisualSize, "hero">;
  link?: boolean;
}> = ({ team, fallbackName, size = "md", link = true }) => {
  const [failed, setFailed] = React.useState(false);
  const directory = useTeamDirectory();
  const profile = team ? directory.data?.find((item) => item.id === team.id) : undefined;
  const officialCompetitionLogo = getOfficialTeamLogoUrl(team);
  const registryLogo = profile?.logo_url || getValveTeamLogoUrl(profile?.valve_team_id);
  const logo = officialCompetitionLogo || registryLogo;
  const logoSource = officialCompetitionLogo
    ? "valve-ti2026"
    : profile?.logo_url
      ? profile.logo_source || "team-registry"
      : profile?.valve_team_id
        ? "valve-steam"
        : "fallback";
  const name = team?.name || fallbackName || "TBD";
  const href = link ? teamHref(profile?.slug) : null;

  React.useEffect(() => {
    setFailed(false);
  }, [logo]);

  const className = `team-crest team-crest-${size} ${logo && !failed ? "has-image" : "is-fallback"}${href ? " is-link" : ""}`;
  const content = logo && !failed ? (
    <img src={logo} alt="" loading="lazy" decoding="async" onError={() => setFailed(true)} />
  ) : (
    <b aria-hidden="true">{teamAbbreviation(team, fallbackName)}</b>
  );

  if (href) {
    return (
      <a
        className={className}
        data-team-logo-source={logo && !failed ? logoSource : "fallback"}
        title={name}
        href={href}
        aria-label={name}
      >
        {content}
      </a>
    );
  }

  return (
    <span
      className={className}
      data-team-logo-source={logo && !failed ? logoSource : "fallback"}
      title={name}
    >
      {content}
    </span>
  );
};

export const EventMark: React.FC<{
  eventName: string;
  size?: VisualSize;
  decorative?: boolean;
}> = ({ eventName, size = "md", decorative = false }) => {
  const [failed, setFailed] = React.useState(false);
  const artwork = getOfficialEventArtwork(eventName);
  const useArtwork = Boolean(artwork && !failed);

  return (
    <span
      className={`event-mark event-mark-${size} ${useArtwork ? "has-image" : "is-fallback"}`}
      data-event-art-source={useArtwork ? artwork?.sourceName : "fallback"}
      title={decorative ? undefined : eventName}
      aria-hidden={decorative || undefined}
    >
      {useArtwork && artwork ? (
        <img
          src={artwork.src}
          alt={decorative ? "" : eventName}
          loading={size === "hero" ? "eager" : "lazy"}
          decoding="async"
          style={{ objectPosition: artwork.objectPosition }}
          onError={() => setFailed(true)}
        />
      ) : (
        <b aria-hidden="true">{eventAbbreviation(eventName)}</b>
      )}
    </span>
  );
};

export const UiIcon: React.FC<{ name: IconName; size?: number }> = ({ name, size = 14 }) => {
  const props = { className: `ui-icon ui-icon-${name}`, size, "aria-hidden": true };
  if (name === "ai" || name === "spark") return <MagicWand {...props} />;
  if (name === "calendar") return <Calendar {...props} />;
  if (name === "check") return <Checkmark {...props} />;
  if (name === "clock") return <Time {...props} />;
  if (name === "layers") return <Layers {...props} />;
  if (name === "language") return <Language {...props} />;
  if (name === "lock") return <Locked {...props} />;
  if (name === "logout") return <Logout {...props} />;
  if (name === "menu") return <Menu {...props} />;
  if (name === "notification") return <Notification {...props} />;
  if (name === "star") return <Star {...props} />;
  if (name === "ticket") return <Ticket {...props} />;
  if (name === "trophy") return <Trophy {...props} />;
  if (name === "user") return <User {...props} />;
  return <Group {...props} />;
};
