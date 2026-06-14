"use client";

import React from "react";
import { C, FONT } from "@/lib/theme";
import { PageHeader, Footer, Badge, Avatar, Icon, EmptyState } from "@/components/ui";
import { MemberSummary, formatINR, initials } from "@/lib/api";
import { Ctx } from "./types";

const COLS = "2.2fr 1fr 1.6fr 1.2fr .7fr 1fr 1.2fr";

function sinceLabel(d: string): string {
  return new Date(`${d}T00:00:00`).toLocaleDateString("en-IN", { month: "short", year: "numeric" });
}

function MemberRow({ m }: { m: MemberSummary }) {
  const active = m.status === "active";
  return (
    <div style={{ display: "grid", gridTemplateColumns: COLS, alignItems: "center", padding: "18px 26px", borderTop: `1px solid ${C.borderSoft}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 13 }}>
        <Avatar>{initials(m.name)}</Avatar>
        <div>
          <span style={{ fontSize: 16, color: C.display }}>{m.name}</span>
          {m.group_names.length > 0 && (
            <div style={{ fontSize: 11.5, color: C.muted3, marginTop: 2 }}>{m.group_names.join(" · ")}</div>
          )}
        </div>
      </div>
      <div><Badge kind={active ? "active" : "expired"}>{active ? "Active" : "Expired"}</Badge></div>
      <div style={{ display: "flex", alignItems: "center", gap: 7, fontFamily: FONT.mono, fontSize: 13, color: "#9aa89e" }}>
        <Icon name="phone" size={13} color={C.faint} stroke={1.8} />{m.phone}
      </div>
      <div style={{ color: "#9aa89e", fontSize: 14 }}>{m.top_sport ?? "—"}</div>
      <div style={{ fontFamily: FONT.serif, fontSize: 24, color: C.display }}>{m.visits}</div>
      <div style={{ color: C.muted, fontSize: 14 }}>{sinceLabel(m.since)}</div>
      <div style={{ fontFamily: FONT.serif, fontSize: 24, color: C.display, textAlign: "right" }}>
        {m.spend > 0 ? formatINR(m.spend) : "—"}
      </div>
    </div>
  );
}

export function Members({ ctx }: { ctx: Ctx }) {
  const { members, dateLabel, hoursLabel } = ctx;
  const active = members.filter((m) => m.status === "active").length;
  const totalSpend = members.reduce((s, m) => s + m.spend, 0);

  return (
    <div>
      <PageHeader
        title="Members"
        subtitle={`${active} active · ${formatINR(totalSpend)} booked value`}
        dateLabel={dateLabel}
        hoursLabel={hoursLabel}
      />

      <div style={{ borderRadius: 16, background: C.panel, border: `1px solid ${C.border}`, marginTop: 30, overflow: "hidden" }}>
        <div style={{ display: "grid", gridTemplateColumns: COLS, padding: "16px 26px", fontSize: 11, letterSpacing: 1.5, color: C.faint }}>
          <span>MEMBER</span><span>STATUS</span><span>PHONE</span><span>SPORT</span><span>VISITS</span><span>SINCE</span>
          <span style={{ textAlign: "right" }}>BOOKED ₹</span>
        </div>
        {members.length === 0
          ? <EmptyState icon="users" title="No members yet" body="Add members so the agent can recognise them and apply member pricing and group rules." />
          : members.map((m) => <MemberRow key={m.member_id} m={m} />)}
      </div>

      <Footer />
    </div>
  );
}
