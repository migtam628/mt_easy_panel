/** Faithful navigation and page order from web/index.html (legacy MT Panel). */
export const SECTIONS = [
  "overview", "servers", "projects", "containers", "images",
  "networks", "volumes", "activity", "monitoring",
  "deployments", "settings",
] as const;
export type Section = (typeof SECTIONS)[number];

export const PAGE: Record<Section, {title: string; subtitle: string; table: string; icon: string}> = {
  overview: { title: "Infrastructure overview", subtitle: "A real-time snapshot of your local Docker host.", table: "Container inventory", icon: "◫" },
  servers: { title: "Servers", subtitle: "Monitor verified agent identities and signed host health. Remote Docker access remains disabled.", table: "Fleet health", icon: "▧" },
  projects: { title: "Projects", subtitle: "Configuration-only application workspaces.", table: "Projects", icon: "◇" },
  containers: { title: "Containers", subtitle: "Inspect running and stopped workloads.", table: "All containers", icon: "▤" },
  images: { title: "Container images", subtitle: "Available local Docker images.", table: "Images", icon: "◈" },
  networks: { title: "Networks", subtitle: "Docker network inventory.", table: "Network inventory", icon: "⌘" },
  volumes: { title: "Volumes", subtitle: "Named persistent Docker volumes (mount paths hidden).", table: "Volume inventory", icon: "▣" },
  activity: { title: "Activity", subtitle: "Recent administrative sign-in and sign-out events.", table: "Security audit log", icon: "◷" },
  monitoring: { title: "Monitoring", subtitle: "Read-only host capacity and signed fleet signals.", table: "Host and identity health", icon: "◉" },
  deployments: { title: "Deployments", subtitle: "Configuration drafts only. Execution is disabled.", table: "Deployment preparation", icon: "◇" },
  settings: { title: "Security settings", subtitle: "Review effective settings without exposing secrets.", table: "Security posture", icon: "⚙" },
};
