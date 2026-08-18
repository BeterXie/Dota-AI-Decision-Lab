import React from "react";
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

type IconName = "calendar" | "clock" | "layers" | "spark" | "trophy" | "users";

export const TeamCrest: React.FC<{
  team: TeamIdentity;
  fallbackName?: string;
  size?: Exclude<VisualSize, "hero">;
  link?: boolean;
}> = ({ team, fallbackName, size = "md", link = true }) => {
  const [failed, setFailed] = React.useState(false);
  const directory = useTeamDirectory();
  const profile = team ? directory.data?.find((item) => item.id === team.id) : undefined;
  const registryLogo = profile?.logo_url || getValveTeamLogoUrl(profile?.valve_team_id);
  const compatibilityLogo = getOfficialTeamLogoUrl(team);
  const logo = registryLogo || compatibilityLogo;
  const logoSource = profile?.logo_url
    ? profile.logo_source || "team-registry"
    : profile?.valve_team_id
      ? "valve-steam"
      : compatibilityLogo
        ? "valve-steam-compat"
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

export const UiIcon: React.FC<{ name: IconName; size?: number }> = ({ name, size = 14 }) => (
  <svg
    className={`ui-icon ui-icon-${name}`}
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    {iconPath(name)}
  </svg>
);

function iconPath(name: IconName): React.ReactNode {
  if (name === "calendar") {
    return <><path d="M6 3v3M18 3v3M4 9h16" /><rect x="4" y="5" width="16" height="15" rx="2" /></>;
  }
  if (name === "clock") {
    return <><circle cx="12" cy="12" r="8.5" /><path d="M12 7v5l3 2" /></>;
  }
  if (name === "layers") {
    return <><path d="m12 4 8 4-8 4-8-4 8-4Z" /><path d="m4 12 8 4 8-4M4 16l8 4 8-4" /></>;
  }
  if (name === "spark") {
    return <><path d="m12 3 1.4 4.2L18 9l-4.6 1.8L12 15l-1.4-4.2L6 9l4.6-1.8L12 3Z" /><path d="m18.5 15 .7 2.1 2.1.7-2.1.7-.7 2.1-.7-2.1-2.1-.7 2.1-.7.7-2.1Z" /></>;
  }
  if (name === "trophy") {
    return <><path d="M8 4h8v4a4 4 0 0 1-8 0V4Z" /><path d="M8 6H5v1a4 4 0 0 0 4 4M16 6h3v1a4 4 0 0 1-4 4M12 12v4M9 20h6M10 16h4" /></>;
  }
  return <><circle cx="9" cy="8" r="3" /><circle cx="17" cy="9" r="2.4" /><path d="M3.5 19c.5-3.7 2.4-5.5 5.5-5.5s5 1.8 5.5 5.5M14 14.5c3.5-.5 5.6 1 6.5 4.5" /></>;
}
