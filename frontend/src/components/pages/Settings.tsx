"use client";

import React from "react";
import { C, FONT } from "@/lib/theme";
import { PageHeader, Footer } from "@/components/ui";
import { ClientInfo, hoursLabel as fmtHours } from "@/lib/api";
import { Ctx } from "./types";

function langLabel(pref: string): string {
  const map: Record<string, string> = {
    "hi-en": "Hindi + English (Hinglish)",
    "hi": "Hindi",
    "en": "English",
  };
  return map[pref] ?? pref;
}

function Field({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "160px 1fr", alignItems: "center" }}>
      <span style={{ fontSize: 14, color: C.muted }}>{label}</span>
      <div style={{ padding: "14px 16px", borderRadius: 11, background: C.inset, border: `1px solid ${C.divider}`, color: C.display, fontSize: 15, fontFamily: mono ? FONT.mono : FONT.sans }}>
        {value}
      </div>
    </div>
  );
}

export function Settings({ ctx }: { ctx: Ctx }) {
  const { client, dateLabel, hoursLabel } = ctx;
  const c: Partial<ClientInfo> = client ?? {};

  return (
    <div>
      <PageHeader title="Settings" subtitle="Workspace · agent · plan" dateLabel={dateLabel} hoursLabel={hoursLabel} />

      <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr", gap: 18, marginTop: 30, alignItems: "start" }}>
        <div style={{ padding: "30px 32px", borderRadius: 16, background: C.panel, border: `1px solid ${C.border}` }}>
          <div style={{ fontSize: 11, letterSpacing: 2, color: C.faint }}>WORKSPACE</div>
          <div style={{ marginTop: 22, display: "flex", flexDirection: "column", gap: 18 }}>
            <Field label="Venue name" value={c.business_name ?? "—"} />
            <Field label="Legal entity" value={c.name ?? "—"} />
            <Field label="Location" value={c.address ?? "—"} />
            <Field label="Operating hours" value={fmtHours(c.opening_time ?? null, c.closing_time ?? null) || "—"} />
            <Field label="Languages" value={langLabel(c.language_preference ?? "")} />
            <Field label="Timezone" value={c.timezone ?? "—"} mono />
            <Field label="Sports" value={(c.sports ?? []).join(", ") || "—"} />
          </div>
        </div>

        <div style={{ padding: "30px 32px", borderRadius: 16, background: C.panel, border: `1px solid ${C.border}` }}>
          <div style={{ fontSize: 11, letterSpacing: 2, color: C.faint }}>PLAN</div>
          <div style={{ fontFamily: FONT.serif, fontSize: 46, fontWeight: 500, color: C.heading, marginTop: 14, lineHeight: 1 }}>Pro</div>
          <div style={{ fontSize: 14, color: C.muted, marginTop: 12 }}>Unlimited bookings · {c.court_count ?? 0} courts</div>
          <div style={{ marginTop: 26, paddingTop: 22, borderTop: `1px solid ${C.borderSoft}` }}>
            <div style={{ fontSize: 11, letterSpacing: 1.5, color: C.faint }}>RENEWS</div>
            <div style={{ fontSize: 15, color: C.display, marginTop: 10, fontFamily: FONT.mono }}>10 Feb 2026 · ₹14,999/mo</div>
          </div>
          <div style={{ marginTop: 24, padding: 14, borderRadius: 11, border: "1px solid rgba(217,162,115,0.4)", background: "rgba(217,162,115,0.06)", textAlign: "center", color: C.goldText, fontSize: 14.5, fontWeight: 500, cursor: "pointer" }}>
            Manage billing
          </div>
        </div>
      </div>

      <Footer />
    </div>
  );
}
