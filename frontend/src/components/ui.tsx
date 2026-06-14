"use client";

import React from "react";
import { C, FONT } from "@/lib/theme";
import { OccupancyGrid, OccupancyStatus, formatHour } from "@/lib/api";

// ---------------------------------------------------------------------------
// Icons (inline stroke SVGs, matching the mockup's lucide-style set)
// ---------------------------------------------------------------------------

type IconName =
  | "grid" | "phone" | "calendar" | "users" | "bar" | "settings"
  | "logout" | "search" | "bell" | "clock" | "check" | "volume" | "play";

const PATHS: Record<IconName, React.ReactNode> = {
  grid: (<><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /></>),
  phone: (<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z" />),
  calendar: (<><rect x="3" y="4" width="18" height="18" rx="2.5" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" /></>),
  users: (<><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M23 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></>),
  bar: (<><line x1="12" y1="20" x2="12" y2="10" /><line x1="18" y1="20" x2="18" y2="4" /><line x1="6" y1="20" x2="6" y2="16" /></>),
  settings: (<><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></>),
  logout: (<><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" /></>),
  search: (<><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></>),
  bell: (<><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" /></>),
  clock: (<><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></>),
  check: (<><circle cx="12" cy="12" r="10" /><polyline points="8 12 11 15 16 9" /></>),
  volume: (<><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" /><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07" /></>),
  play: (<polygon points="6 4 20 12 6 20 6 4" />),
};

export function Icon({
  name, size = 18, color = "currentColor", stroke = 1.7, fill = "none",
}: { name: IconName; size?: number; color?: string; stroke?: number; fill?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke={color}
      strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
      {PATHS[name]}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Layout primitives
// ---------------------------------------------------------------------------

export function Panel({
  eyebrow, title, right, children, padding = "24px 26px", style,
}: {
  eyebrow?: string; title?: React.ReactNode; right?: React.ReactNode;
  children?: React.ReactNode; padding?: string; style?: React.CSSProperties;
}) {
  return (
    <div style={{ padding, borderRadius: 16, background: C.panel, border: `1px solid ${C.border}`, ...style }}>
      {(eyebrow || title || right) && (
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
          <div>
            {eyebrow && <div style={{ fontSize: 11, letterSpacing: 2, color: C.muted3 }}>{eyebrow}</div>}
            {title && (
              <div style={{ fontFamily: FONT.serif, fontSize: 27, color: C.heading, fontWeight: 500, marginTop: 5 }}>
                {title}
              </div>
            )}
          </div>
          {right}
        </div>
      )}
      {children}
    </div>
  );
}

export function Avatar({ children, glow = false, size = 38 }: { children: React.ReactNode; glow?: boolean; size?: number }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: "50%", flexShrink: 0,
      display: "flex", alignItems: "center", justifyContent: "center",
      fontSize: size * 0.45, fontFamily: FONT.mono,
      ...(glow
        ? { background: "radial-gradient(circle at 35% 30%, #7fffc4, #1fae6e 60%, #0c5a3a)", color: "#06321f", fontWeight: 600 }
        : { background: "rgba(62,207,142,0.12)", border: "1px solid rgba(62,207,142,0.25)", color: C.greenSoft }),
    }}>
      {children}
    </div>
  );
}

const BADGE_BASE: React.CSSProperties = {
  fontSize: 11.5, padding: "5px 11px", borderRadius: 999, fontFamily: FONT.mono,
  letterSpacing: 0.3, whiteSpace: "nowrap",
};

type BadgeKind = "booked" | "missed" | "handled" | "active" | "expired" | "neutral" | "gold";

export function Badge({ kind, children }: { kind: BadgeKind; children: React.ReactNode }) {
  const styles: Record<BadgeKind, React.CSSProperties> = {
    booked: { color: C.greenSoft, border: "1px solid rgba(62,207,142,0.3)", background: "rgba(62,207,142,0.07)" },
    active: { color: C.greenSoft, border: "1px solid rgba(62,207,142,0.28)", background: "transparent" },
    handled: { color: "#9aa89e", border: `1px solid ${C.divider}`, background: "transparent" },
    neutral: { color: "#9aa89e", border: `1px solid ${C.divider}`, background: "transparent" },
    missed: { color: C.gold2, border: "1px solid rgba(217,162,115,0.35)", background: "rgba(217,162,115,0.07)" },
    expired: { color: C.gold2, border: "1px solid rgba(217,162,115,0.3)", background: "rgba(217,162,115,0.06)" },
    gold: { color: C.gold2, border: "1px solid rgba(217,162,115,0.4)", background: "rgba(217,162,115,0.1)" },
  };
  return <span style={{ ...BADGE_BASE, ...styles[kind] }}>{children}</span>;
}

// ---------------------------------------------------------------------------
// Page header (date row · big serif title · subtitle · search + bell)
// ---------------------------------------------------------------------------

export function SearchChip() {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 9, width: 280, padding: "9px 13px",
      borderRadius: 10, background: C.panelAlt, border: `1px solid ${C.divider}`, color: C.muted3, fontSize: 14,
    }}>
      <Icon name="search" size={15} stroke={1.8} />
      <span style={{ flex: 1 }}>Search calls, members…</span>
      <span style={{ fontFamily: FONT.mono, fontSize: 11, border: `1px solid ${C.borderFaint}`, borderRadius: 5, padding: "1px 5px" }}>⌘K</span>
    </div>
  );
}

export function BellButton() {
  return (
    <div style={{
      width: 40, height: 40, borderRadius: 10, background: C.panelAlt, border: `1px solid ${C.divider}`,
      display: "flex", alignItems: "center", justifyContent: "center", position: "relative",
    }}>
      <Icon name="bell" size={17} color="#9aa89e" />
      <span style={{ position: "absolute", top: 9, right: 10, width: 6, height: 6, borderRadius: "50%", background: C.gold }} />
    </div>
  );
}

export function PageHeader({
  title, subtitle, dateLabel, hoursLabel, livePill,
}: { title: string; subtitle: React.ReactNode; dateLabel?: string; hoursLabel?: string; livePill?: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 24 }}>
      <div>
        {dateLabel && (
          <div style={{ display: "flex", alignItems: "center", gap: 11, fontSize: 12, letterSpacing: 2, color: C.muted3 }}>
            <span>{dateLabel}</span>
            <span style={{ width: 4, height: 4, borderRadius: "50%", background: C.green, display: "inline-block" }} />
            <span>{hoursLabel}</span>
          </div>
        )}
        <h1 style={{ fontFamily: FONT.serif, fontWeight: 500, fontSize: 54, color: C.heading, margin: dateLabel ? "12px 0 0" : 0, lineHeight: 1 }}>
          {title}
        </h1>
        <div style={{ fontSize: 15, color: C.muted, marginTop: 13 }}>{subtitle}</div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 14, paddingTop: 4 }}>
        {livePill}
        <SearchChip />
        <BellButton />
      </div>
    </div>
  );
}

export function LivePill({ text }: { text: string }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 8, padding: "8px 14px", borderRadius: 999,
      border: "1px solid rgba(62,207,142,0.3)", background: "rgba(62,207,142,0.06)",
      fontSize: 12, letterSpacing: 1, color: C.greenSoft,
    }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", background: C.green, boxShadow: `0 0 8px ${C.green}`, animation: "pulsedot 1.6s infinite" }} />
      {text}
    </div>
  );
}

export function Footer() {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 34,
      fontSize: 11, letterSpacing: 1.5, color: C.faint2, fontFamily: FONT.mono,
    }}>
      <span>MELLO.AI · CONSOLE V2.6</span>
      <span style={{ fontFamily: FONT.sans, letterSpacing: 0 }}>हर कॉल एक मौका है</span>
    </div>
  );
}

export function EmptyState({ icon, title, body }: { icon?: IconName; title: string; body?: string }) {
  return (
    <div style={{ padding: "56px 24px", textAlign: "center", color: C.muted2 }}>
      {icon && (
        <div style={{ display: "flex", justifyContent: "center", marginBottom: 16, color: C.faint }}>
          <Icon name={icon} size={30} stroke={1.5} />
        </div>
      )}
      <div style={{ fontSize: 16, color: C.body }}>{title}</div>
      {body && <div style={{ fontSize: 13.5, color: C.muted2, marginTop: 8, maxWidth: 420, marginInline: "auto", lineHeight: 1.5 }}>{body}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sparkline (220×50 viewBox polyline from a number series)
// ---------------------------------------------------------------------------

export function Sparkline({ values, color = C.gold }: { values: number[]; color?: string }) {
  const max = Math.max(1, ...values);
  const min = Math.min(...values);
  const span = Math.max(1, max - min);
  const stepX = values.length > 1 ? 220 / (values.length - 1) : 220;
  const points = values
    .map((v, i) => `${(i * stepX).toFixed(0)},${(44 - ((v - min) / span) * 38).toFixed(0)}`)
    .join(" ");
  return (
    <svg viewBox="0 0 220 50" preserveAspectRatio="none" style={{ width: "100%", height: 40, marginTop: 14, display: "block" }}>
      <polyline points={points} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function StatCard({
  label, value, trend, sub, spark, sparkColor,
}: { label: string; value: string; trend?: string; sub: string; spark?: number[]; sparkColor?: string }) {
  return (
    <div style={{ padding: "22px 22px 16px", borderRadius: 16, background: C.panelAlt, border: `1px solid ${C.border}` }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: 11, letterSpacing: 1.6, color: C.muted3 }}>{label}</span>
        {trend && (
          <span style={{ fontSize: 11, color: C.greenSoft, background: "rgba(62,207,142,0.08)", border: "1px solid rgba(62,207,142,0.22)", padding: "3px 8px", borderRadius: 7 }}>
            ↗ {trend}
          </span>
        )}
      </div>
      <div style={{ fontFamily: FONT.serif, fontSize: 52, fontWeight: 500, color: C.heading, margin: "14px 0 0", lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: 13, color: C.muted2, marginTop: 11 }}>{sub}</div>
      {spark && <Sparkline values={spark} color={sparkColor} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Occupancy grid
// ---------------------------------------------------------------------------

const CELL_STYLE: Record<OccupancyStatus, { bg: string; bd: string; glyph: string; co: string }> = {
  available: { bg: "#15231b", bd: "#1a2620", glyph: "·", co: "#46524a" },
  booked: { bg: "rgba(62,207,142,0.13)", bd: "rgba(62,207,142,0.32)", glyph: "✓", co: "#5fd39a" },
  peak: { bg: "rgba(217,162,115,0.15)", bd: "rgba(217,162,115,0.34)", glyph: "★", co: "#e3a977" },
  blocked: { bg: "#0f1a14", bd: "#171f1a", glyph: "–", co: "#3a443c" },
};

function LegendDot({ color, label, outline }: { color?: string; label: string; outline?: boolean }) {
  return (
    <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span style={{ width: 9, height: 9, borderRadius: 3, background: outline ? "transparent" : color, border: outline ? `1px solid ${C.divider}` : "none" }} />
      {label}
    </span>
  );
}

export function OccupancyWidget({ grid }: { grid: OccupancyGrid | null }) {
  return (
    <Panel
      eyebrow="TODAY"
      title="Court occupancy"
      right={
        <div style={{ display: "flex", gap: 16, fontSize: 12, color: C.muted, paddingTop: 6 }}>
          <LegendDot outline label="Available" />
          <LegendDot color={C.green} label="Booked" />
          <LegendDot color={C.gold} label="Peak" />
          <LegendDot color={C.divider} label="Blocked" />
        </div>
      }
    >
      <div style={{ marginTop: 22 }}>
        {grid && (
          <>
            <div style={{ display: "flex", gap: 8, alignItems: "center", paddingLeft: 96 }}>
              {grid.times.map((t) => (
                <div key={t} style={{ flex: 1, textAlign: "center", fontSize: 11, letterSpacing: 1, color: C.faint }}>{formatHour(t)}</div>
              ))}
            </div>
            <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 9 }}>
              {grid.rows.map((row) => (
                <div key={row.court_id} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <div style={{ width: 88, fontSize: 13.5, color: C.body, flexShrink: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{row.court_name}</div>
                  {row.cells.map((cell, i) => {
                    const s = CELL_STYLE[cell.status];
                    return (
                      <div key={i} style={{
                        flex: 1, height: 40, display: "flex", alignItems: "center", justifyContent: "center",
                        borderRadius: 8, fontSize: 13, fontFamily: FONT.mono, background: s.bg, border: `1px solid ${s.bd}`, color: s.co,
                      }}>{s.glyph}</div>
                    );
                  })}
                </div>
              ))}
            </div>
          </>
        )}
        {!grid && <div style={{ height: 200, display: "flex", alignItems: "center", justifyContent: "center", color: C.faint }}>Loading…</div>}
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Weekly bars (bookings + revenue) — the "last 7 days" chart
// ---------------------------------------------------------------------------

export function WeekBars({ series }: { series: { label: string; bookings: number; revenue: number }[] }) {
  const maxB = Math.max(1, ...series.map((d) => d.bookings));
  const maxR = Math.max(1, ...series.map((d) => d.revenue));
  return (
    <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-around", height: 210, marginTop: 24, padding: "0 6px" }}>
      {series.map((d) => (
        <div key={d.label} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 6, height: 180 }}>
            <div title={`${d.bookings} bookings`} style={{ width: 26, height: Math.max(4, (d.bookings / maxB) * 170), borderRadius: "5px 5px 0 0", background: "linear-gradient(#3ecf8e,#2aa873)" }} />
            <div title={`₹${d.revenue}`} style={{ width: 26, height: Math.max(4, (d.revenue / maxR) * 170), borderRadius: "5px 5px 0 0", background: "linear-gradient(#e3b485,#cf935f)" }} />
          </div>
          <span style={{ fontSize: 12, color: C.muted3 }}>{d.label}</span>
        </div>
      ))}
    </div>
  );
}
