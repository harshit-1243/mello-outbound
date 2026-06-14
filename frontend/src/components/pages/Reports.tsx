"use client";

import React from "react";
import { C, FONT } from "@/lib/theme";
import { PageHeader, Panel, Footer } from "@/components/ui";
import { DaySeries, formatINR } from "@/lib/api";
import { Ctx } from "./types";

function MetricCard({ label, value, sub, subColor = C.muted2 }: { label: string; value: React.ReactNode; sub: string; subColor?: string }) {
  return (
    <div style={{ padding: "26px 28px", borderRadius: 16, background: C.panelAlt, border: `1px solid ${C.border}` }}>
      <div style={{ fontSize: 11, letterSpacing: 1.6, color: C.muted3 }}>{label}</div>
      <div style={{ fontFamily: FONT.serif, fontSize: 50, fontWeight: 500, color: C.heading, marginTop: 14, lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: 13, color: subColor, marginTop: 14 }}>{sub}</div>
    </div>
  );
}

function RevenueChart({ series }: { series: DaySeries[] }) {
  const W = 920, H = 400, x0 = 60, x1 = 900, yTop = 20, yBot = 360;
  const revenues = series.map((d) => d.revenue);
  const max = Math.max(1000, ...revenues);
  const n = Math.max(1, series.length - 1);
  const xAt = (i: number) => x0 + (i * (x1 - x0)) / n;
  const yAt = (v: number) => yBot - (v / max) * (yBot - yTop);

  const linePts = series.map((d, i) => `${xAt(i).toFixed(0)},${yAt(d.revenue).toFixed(0)}`).join(" ");
  const areaPts = `${linePts} ${x1},${yBot} ${x0},${yBot}`;
  const gridYs = [0, 0.25, 0.5, 0.75, 1].map((f) => ({ y: yBot - f * (yBot - yTop), val: Math.round((max * f) / 100) * 100 }));

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", marginTop: 18, display: "block" }}>
      <defs>
        <linearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={C.gold} stopOpacity={0.28} />
          <stop offset="100%" stopColor={C.gold} stopOpacity={0} />
        </linearGradient>
      </defs>
      {gridYs.map((g, i) => (
        <g key={i}>
          <line x1={x0} y1={g.y} x2={x1} y2={g.y} stroke={i === 0 ? C.borderFaint : C.borderSoft} strokeWidth={1} />
          <text x={x0 - 16} y={g.y + 4} textAnchor="end" fontSize={12} fill={C.faint} fontFamily={FONT.sans}>{g.val}</text>
        </g>
      ))}
      <polygon points={areaPts} fill="url(#areaFill)" />
      <polyline points={linePts} fill="none" stroke={C.gold} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" />
      {series.map((d, i) => (
        <text key={d.label} x={xAt(i)} y={yBot + 28} textAnchor="middle" fontSize={13} fill={C.muted3} fontFamily={FONT.sans}>{d.label}</text>
      ))}
    </svg>
  );
}

export function Reports({ ctx }: { ctx: Ctx }) {
  const { stats } = ctx;
  const series = stats?.series ?? [];
  const weekRevenue = series.reduce((s, d) => s + d.revenue, 0);
  const weekBookings = series.reduce((s, d) => s + d.bookings, 0);
  const totalBookings = stats?.total_bookings ?? 0;
  // Each call the agent fields instead of a staff member ≈ 4 minutes saved.
  const savedMinutes = totalBookings * 4;
  const savedHours = Math.round((savedMinutes / 60) * 10) / 10;
  const labour = Math.round((savedMinutes / 60) * 250); // ~₹250/hr floor staff

  return (
    <div>
      <PageHeader title="Reports" subtitle="What Mello booked for you this week." />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 18, marginTop: 30 }}>
        <MetricCard label="REVENUE CAPTURED" value={formatINR(weekRevenue)} sub={`${formatINR(stats?.total_revenue ?? 0)} booked all-time`} subColor={C.greenSoft} />
        <MetricCard label="BOOKINGS MADE" value={String(weekBookings)} sub={`${totalBookings} all-time · avg ${(weekBookings / Math.max(1, series.length)).toFixed(1)}/day`} />
        <MetricCard label="SAVED STAFF TIME" value={<>{savedHours}<span style={{ fontSize: 26, color: C.muted }}> hrs</span></>} sub={`≈ ${formatINR(labour)} in labour · est. 4 min/booking`} subColor={C.gold2} />
      </div>

      <Panel eyebrow="WEEKLY REVENUE" title="Booked through Mello" padding="26px 30px" style={{ marginTop: 18 }}>
        <RevenueChart series={series} />
      </Panel>

      <Footer />
    </div>
  );
}
