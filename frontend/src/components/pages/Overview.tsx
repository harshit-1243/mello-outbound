"use client";

import React from "react";
import { C, FONT } from "@/lib/theme";
import {
  Panel, PageHeader, LivePill, StatCard, WeekBars, OccupancyWidget, Footer, Avatar, Icon, EmptyState,
} from "@/components/ui";
import { Booking, UsageMeter, formatTime, formatINR, relativeDay, sportEmoji } from "@/lib/api";
import { Ctx } from "./types";

function SourceBadge({ source }: { source: string }) {
  const map: Record<string, { label: string; color: string; bg: string; bd: string }> = {
    voice: { label: "Mello", color: C.greenSoft, bg: "rgba(62,207,142,0.07)", bd: "rgba(62,207,142,0.3)" },
    whatsapp: { label: "WhatsApp", color: "#9aa89e", bg: "transparent", bd: C.divider },
    manual: { label: "Manual", color: "#9aa89e", bg: "transparent", bd: C.divider },
  };
  const s = map[source] ?? map.manual;
  return (
    <span style={{ fontSize: 11.5, padding: "5px 11px", borderRadius: 999, fontFamily: FONT.mono, whiteSpace: "nowrap", color: s.color, background: s.bg, border: `1px solid ${s.bd}` }}>
      {s.label}
    </span>
  );
}

function RecentRow({ b, today }: { b: Booking; today: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "14px 0", borderTop: `1px solid ${C.borderSoft}` }}>
      <Avatar>{sportEmoji(b.sport)}</Avatar>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 15, color: C.display, fontWeight: 500 }}>{b.customer_name}</span>
          <span style={{ fontSize: 12, color: C.muted3, fontFamily: FONT.mono }}>{b.customer_phone}</span>
        </div>
        <div style={{ fontSize: 13, color: C.muted2, marginTop: 5 }}>
          {b.option_name} · {relativeDay(b.slot_date, today)} {formatTime(b.start_time)} · {b.court_name}
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 5 }}>
        <div style={{ fontSize: 13, color: C.display, fontFamily: FONT.mono }}>{formatINR(b.amount)}</div>
      </div>
      <SourceBadge source={b.source} />
    </div>
  );
}

function UpcomingRow({ b, today }: { b: Booking; today: string }) {
  const isMember = b.amount === 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "14px 0", borderTop: `1px solid ${C.borderSoft}` }}>
      <div style={{ width: 92, flexShrink: 0 }}>
        <div style={{ fontFamily: FONT.mono, fontSize: 13.5, color: C.display }}>{formatTime(b.start_time)}</div>
        <div style={{ fontSize: 11.5, color: C.muted3, marginTop: 4 }}>{relativeDay(b.slot_date, today)}</div>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 14.5, color: C.display }}>{b.customer_name}</div>
        <div style={{ fontSize: 12.5, color: C.muted2, marginTop: 4 }}>
          {b.sport} · {isMember ? "member" : formatINR(b.amount)}
        </div>
      </div>
      <span style={{ fontSize: 11, fontFamily: FONT.mono, letterSpacing: 0.5, padding: "5px 10px", borderRadius: 7, color: "#9aa89e", border: `1px solid ${C.divider}`, whiteSpace: "nowrap" }}>
        {b.court_name}
      </span>
    </div>
  );
}

function HealthRow({ label, value, pct, color = C.green }: { label: string; value: string; pct: number; color?: string }) {
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: 14, color: C.body }}>{label}</span>
        <span style={{ fontFamily: FONT.mono, fontSize: 14, color: C.display }}>{value}</span>
      </div>
      <div style={{ height: 6, borderRadius: 4, background: "#1a2a20", marginTop: 10, overflow: "hidden" }}>
        <div style={{ height: 6, borderRadius: 4, background: `linear-gradient(90deg, ${C.greenDeep}, ${color})`, width: `${Math.max(4, Math.min(100, pct))}%` }} />
      </div>
    </div>
  );
}

function UsageRow({ meter }: { meter: UsageMeter }) {
  const color =
    meter.status === "over" ? "#e08b80" : meter.status === "warn" ? C.gold : meter.status === "unknown" ? C.muted2 : C.green;
  const value =
    meter.status === "unknown"
      ? `${meter.used.toLocaleString()} ${meter.unit}`
      : `${meter.pct}% · ${meter.used.toLocaleString()}/${meter.limit.toLocaleString()}`;
  // Unknown limit → a thin baseline bar; otherwise scale to pct.
  const pct = meter.pct ?? 3;
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: 14, color: C.body }}>{meter.label}</span>
        <span style={{ fontFamily: FONT.mono, fontSize: 12.5, color: meter.status === "over" ? "#e08b80" : C.display }}>{value}</span>
      </div>
      <div style={{ height: 6, borderRadius: 4, background: "#1a2a20", marginTop: 10, overflow: "hidden" }}>
        <div style={{ height: 6, borderRadius: 4, background: color, width: `${Math.max(3, Math.min(100, pct))}%` }} />
      </div>
    </div>
  );
}

export function Overview({ ctx }: { ctx: Ctx }) {
  const { stats, bookings, members, occupancy, usage, today, dateLabel, hoursLabel, goTo } = ctx;
  const series = stats?.series ?? [];
  const bookingSpark = series.map((d) => d.bookings);
  const revenueSpark = series.map((d) => d.revenue);

  const upcoming = bookings
    .filter((b) => b.status === "confirmed" && b.slot_date >= today)
    .sort((a, b) => `${a.slot_date}${a.start_time}`.localeCompare(`${b.slot_date}${b.start_time}`));
  const recent = [...bookings]
    .sort((a, b) => `${b.slot_date}${b.start_time}`.localeCompare(`${a.slot_date}${a.start_time}`))
    .slice(0, 7);
  const totalMembers = members.length || 1;

  return (
    <div>
      <PageHeader
        title="Overview"
        subtitle="Your AI receptionist · booking engine live"
        dateLabel={dateLabel}
        hoursLabel={hoursLabel}
        livePill={<LivePill text="ENGINE LIVE" />}
      />

      {/* Stat cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 18, marginTop: 30 }}>
        <StatCard label="BOOKINGS TODAY" value={String(stats?.bookings_today ?? 0)} sub={`${stats?.upcoming ?? 0} upcoming this week`} spark={bookingSpark} sparkColor={C.green} />
        <StatCard label="REVENUE TODAY" value={formatINR(stats?.revenue_today ?? 0)} sub={`${formatINR(stats?.total_revenue ?? 0)} booked overall`} spark={revenueSpark} />
        <StatCard label="UPCOMING" value={String(stats?.upcoming ?? 0)} sub="confirmed reservations" spark={bookingSpark} sparkColor={C.green} />
        <StatCard label="ACTIVE MEMBERS" value={String(stats?.active_members ?? 0)} sub={`${stats?.via_voice ?? 0} bookings via Mello`} spark={revenueSpark} />
      </div>

      {/* Recent activity + Upcoming */}
      <div style={{ display: "grid", gridTemplateColumns: "1.55fr 1fr", gap: 18, marginTop: 18 }}>
        <Panel eyebrow="ACTIVITY" title="Recent bookings" right={<div onClick={() => goTo("bookings")} style={{ fontSize: 13, color: C.muted, cursor: "pointer" }}>View all →</div>}>
          <div style={{ marginTop: 8 }}>
            {recent.length === 0
              ? <EmptyState title="No bookings yet" body="Bookings made by phone or on the floor will appear here automatically." />
              : recent.map((b) => <RecentRow key={b.booking_id} b={b} today={today} />)}
          </div>
        </Panel>

        <Panel eyebrow="UP NEXT" title="Upcoming bookings" right={<div onClick={() => goTo("bookings")} style={{ fontSize: 13, color: C.muted, cursor: "pointer" }}>Calendar →</div>}>
          <div style={{ marginTop: 8 }}>
            {upcoming.length === 0
              ? <EmptyState title="Nothing booked yet" />
              : upcoming.slice(0, 6).map((b) => <UpcomingRow key={b.booking_id} b={b} today={today} />)}
          </div>
        </Panel>
      </div>

      {/* Weekly bars + System health */}
      <div style={{ display: "grid", gridTemplateColumns: "1.55fr 1fr", gap: 18, marginTop: 18 }}>
        <Panel
          eyebrow="THIS WEEK"
          title="Bookings & revenue"
          right={
            <div style={{ display: "flex", gap: 16, fontSize: 12.5, color: C.muted, paddingTop: 6 }}>
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 8, height: 8, borderRadius: "50%", background: C.green }} />Bookings</span>
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 8, height: 8, borderRadius: "50%", background: C.gold }} />Revenue</span>
            </div>
          }
        >
          <WeekBars series={series} />
        </Panel>

        <Panel eyebrow="FREE CREDITS" title="Provider usage">
          <div style={{ marginTop: 24, display: "flex", flexDirection: "column", gap: 22 }}>
            <HealthRow label="Booking engine" value="Live" pct={100} />
            {(usage?.meters ?? []).map((m) => <UsageRow key={m.key} meter={m} />)}
            {!usage && (
              <HealthRow label="Active members" value={String(stats?.active_members ?? 0)} pct={((stats?.active_members ?? 0) / totalMembers) * 100} />
            )}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 26, paddingTop: 18, borderTop: `1px solid ${C.borderSoft}`, fontSize: 12.5 }}>
            <span style={{ color: C.muted2 }}>{usage?.exhausted ? "Credits exhausted" : "Within free limits"}</span>
            <span style={{ color: usage?.exhausted ? "#e08b80" : C.greenSoft, fontFamily: FONT.mono }}>
              {usage?.exhausted ? "● action needed" : "● operational"}
            </span>
          </div>
        </Panel>
      </div>

      <div style={{ marginTop: 18 }}>
        <OccupancyWidget grid={occupancy} />
      </div>

      <Footer />
    </div>
  );
}
