// Design tokens ported from the mello.ai console mockup. Inline styles reference these so the
// implementation stays pixel-faithful to the handoff without a sea of magic hex strings.

export const C = {
  pageBg: "#0b1610",
  sidebarBg: "#0b140f",
  sidebarBorder: "#18241d",
  panel: "#111f17", // primary panels
  panelAlt: "#15231b", // stat cards / search chips
  inset: "#0f1a14", // nested boxes inside panels
  card2: "#12201a", // avatar circles
  border: "#26382d",
  borderSoft: "#1d2b23",
  borderFaint: "#243029",
  divider: "#2a3c31",

  heading: "#ece7dd",
  display: "#dfe5dc",
  body: "#aebab0",
  text: "#cfd8cf",
  muted: "#8a978d",
  muted2: "#7e8c81",
  muted3: "#6c7a70",
  faint: "#586259",
  faint2: "#465049",
  faint3: "#5e6f64",

  green: "#3ecf8e",
  greenSoft: "#6ee7a8",
  greenDeep: "#2aa873",
  gold: "#d9a273",
  gold2: "#e3a977",
  goldText: "#e3a977",
} as const;

export const FONT = {
  serif: "var(--font-spectral), Georgia, serif",
  sans: "var(--font-inter), system-ui, sans-serif",
  mono: "var(--font-mono), 'JetBrains Mono', monospace",
} as const;

// The main content area's radial-gradient backdrop.
export const MAIN_BG =
  "radial-gradient(135% 95% at 50% -5%, #1b2d21 0%, #0f1d16 44%, #0b1610 100%)";
