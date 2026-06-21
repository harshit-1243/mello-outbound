"use client";

import React from "react";
import { C, FONT } from "@/lib/theme";
import { Icon } from "@/components/ui";
import { ClientInfo, initials } from "@/lib/api";

export type PageId = "overview" | "liveCalls" | "outbound" | "bookings" | "members" | "reports" | "settings";

const NAV: { id: PageId; label: string; icon: Parameters<typeof Icon>[0]["name"] }[] = [
  { id: "overview", label: "Overview", icon: "grid" },
  { id: "liveCalls", label: "Live Calls", icon: "phone" },
  { id: "outbound", label: "Outbound", icon: "volume" },
  { id: "bookings", label: "Bookings", icon: "calendar" },
  { id: "members", label: "Members", icon: "users" },
  { id: "reports", label: "Reports", icon: "bar" },
  { id: "settings", label: "Settings", icon: "settings" },
];

function shortLocation(address: string | null): string {
  if (!address) return "—";
  const parts = address.split(",").map((p) => p.trim()).filter(Boolean);
  return parts.slice(-2).join(" · ");
}

export function Sidebar({
  page, onNavigate, client,
}: { page: PageId; onNavigate: (p: PageId) => void; client: ClientInfo | null }) {
  const venue = client?.business_name ?? "Smash Arena";
  const location = shortLocation(client?.address ?? null);

  return (
    <aside style={{
      width: 272, flexShrink: 0, background: C.sidebarBg, borderRight: `1px solid ${C.sidebarBorder}`,
      display: "flex", flexDirection: "column", padding: "24px 18px 20px", position: "sticky", top: 0, height: "100vh",
    }}>
      {/* Brand */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "0 6px" }}>
        <div style={{
          width: 34, height: 34, borderRadius: "50%",
          background: "radial-gradient(circle at 35% 30%, #8fffcf, #1fae6e 58%, #0c5a3a)",
          boxShadow: "0 0 20px rgba(45,200,140,0.55)",
        }} />
        <div>
          <div style={{ fontSize: 21, fontWeight: 600, color: C.heading, lineHeight: 1, letterSpacing: -0.3 }}>
            mello<span style={{ color: "#8fa89a", fontWeight: 400 }}>.ai</span>
          </div>
          <div style={{ fontSize: 9, letterSpacing: 2.4, color: C.faint3, marginTop: 4 }}>AI BOOKING SYSTEM</div>
        </div>
      </div>

      {/* Workspace */}
      <div style={{ fontSize: 10, letterSpacing: 2.2, color: "#586259", margin: "30px 6px 9px" }}>WORKSPACE</div>
      <div style={{
        padding: "14px 15px", borderRadius: 13, background: "#172620", border: "1px solid #2a3c31",
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: "#ece7dd" }}>{venue}</div>
          <div style={{ fontSize: 12.5, color: C.muted3, marginTop: 3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{location}</div>
        </div>
        <span style={{ fontSize: 9.5, letterSpacing: 1, color: C.gold, border: "1px solid rgba(217,162,115,0.4)", padding: "3px 7px", borderRadius: 6, fontWeight: 600, flexShrink: 0, marginLeft: 8 }}>PRO</span>
      </div>

      {/* Nav */}
      <nav style={{ marginTop: 22, display: "flex", flexDirection: "column", gap: 3 }}>
        {NAV.map((item) => {
          const active = page === item.id;
          return (
            <div key={item.id} onClick={() => onNavigate(item.id)} style={{
              position: "relative", display: "flex", alignItems: "center", gap: 13, padding: "10px 13px",
              borderRadius: 9, cursor: "pointer", fontSize: 15, fontWeight: 500,
              borderLeft: `2px solid ${active ? C.gold : "transparent"}`,
              background: active ? "#1a2a20" : "transparent",
              color: active ? "#ece7dd" : "#7e8c81",
              transition: "background .15s ease, color .15s ease",
            }}>
              <Icon name={item.icon} size={19} color={active ? C.green : "currentColor"} />
              <span>{item.label}</span>
            </div>
          );
        })}
      </nav>

      {/* Operator */}
      <div style={{ marginTop: "auto", paddingTop: 18, borderTop: "1px solid #1d2b23", display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{
          width: 38, height: 38, borderRadius: "50%", flexShrink: 0,
          background: "radial-gradient(circle at 35% 30%, #7fffc4, #1fae6e 60%, #0c5a3a)",
          display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 600, color: "#06321f",
        }}>{initials(venue)}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, color: C.display, fontWeight: 500 }}>{venue}</div>
          <div style={{ fontSize: 11.5, color: C.faint3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {client?.name ?? "Operator console"}
          </div>
        </div>
        <Icon name="logout" size={17} color="#5e6f64" />
      </div>
    </aside>
  );
}
