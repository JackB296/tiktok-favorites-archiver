export type NavigationLabel = "Feed" | "Gallery" | "Music" | "Stats" | "Sync" | "Storage" | "Backups" | "Discover" | "Lens" | "History" | "Memories" | "Curate" | "Vibes" | "Duplicates" | "Channels";

export type NavigationItem = {
  to: string;
  label: NavigationLabel;
  group: "Watch" | "Browse" | "Organize" | "Manage";
};

export type NavigationGroup = {
  label: NavigationItem["group"];
  items: NavigationItem[];
};

export const primaryNavigation: NavigationItem[] = [
  { to: "/", label: "Feed", group: "Watch" },
  { to: "/gallery", label: "Gallery", group: "Browse" },
  { to: "/sync", label: "Sync", group: "Manage" },
];

export const navigationGroups: NavigationGroup[] = [
  {
    label: "Watch",
    items: [
      { to: "/", label: "Feed", group: "Watch" },
      { to: "/memories", label: "Memories", group: "Watch" },
      { to: "/channels", label: "Channels", group: "Watch" },
    ],
  },
  {
    label: "Browse",
    items: [
      { to: "/gallery", label: "Gallery", group: "Browse" },
      { to: "/discover", label: "Discover", group: "Browse" },
      { to: "/lens", label: "Lens", group: "Browse" },
      { to: "/stats", label: "Stats", group: "Browse" },
      { to: "/history", label: "History", group: "Browse" },
    ],
  },
  {
    label: "Organize",
    items: [
      { to: "/music", label: "Music", group: "Organize" },
      { to: "/curate", label: "Curate", group: "Organize" },
      { to: "/vibes", label: "Vibes", group: "Organize" },
    ],
  },
  {
    label: "Manage",
    items: [
      { to: "/sync", label: "Sync", group: "Manage" },
      { to: "/storage", label: "Storage", group: "Manage" },
      { to: "/backups", label: "Backups", group: "Manage" },
      { to: "/duplicates", label: "Duplicates", group: "Manage" },
    ],
  },
];
