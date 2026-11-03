/** Shared static route manifest; safe for build-time and client-side use. */
export const SECTIONS = [
  "overview", "containers", "monitoring", "servers",
  "projects", "deployments", "activity", "settings",
] as const;

export type Section = (typeof SECTIONS)[number];
