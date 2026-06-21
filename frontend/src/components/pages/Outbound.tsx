"use client";

import React, { useCallback, useEffect, useState } from "react";
import { C, FONT } from "@/lib/theme";
import { Badge, EmptyState, Panel, PageHeader, StatCard } from "@/components/ui";
import { Ctx } from "@/components/pages/types";
import * as api from "@/lib/api";

const POLL_MS = 6000;

type BadgeKind = "booked" | "missed" | "handled" | "neutral" | "gold" | "active" | "expired";

// Map a contact's last disposition (or its state if never dialed) to a label + pill colour.
function dispoBadge(disposition: string | null, state: string): { label: string; kind: BadgeKind } {
  switch (disposition) {
    case "confirmed": return { label: "CONFIRMED", kind: "booked" };
    case "rescheduled": return { label: "RESCHEDULED", kind: "booked" };
    case "callback_requested": return { label: "CALLBACK", kind: "gold" };
    case "refused": return { label: "REFUSED", kind: "missed" };
    case "opt_out": return { label: "OPT-OUT", kind: "missed" };
    case "wrong_number": return { label: "WRONG #", kind: "neutral" };
    case "no_answer": return { label: "NO ANSWER", kind: "neutral" };
    case "busy": return { label: "BUSY", kind: "neutral" };
    case "voicemail": return { label: "VOICEMAIL", kind: "neutral" };
    case "failed": return { label: "FAILED", kind: "neutral" };
  }
  // Never dialed yet — show progress state.
  const map: Record<string, { label: string; kind: BadgeKind }> = {
    pending: { label: "PENDING", kind: "handled" },
    in_flight: { label: "CALLING…", kind: "active" },
    exhausted: { label: "EXHAUSTED", kind: "missed" },
    skipped: { label: "SKIPPED", kind: "neutral" },
    done: { label: "DONE", kind: "handled" },
  };
  return map[state] ?? { label: state.toUpperCase(), kind: "neutral" };
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ flex: 1, minWidth: 140, padding: "14px 16px", borderRadius: 12, background: C.inset, border: `1px solid ${C.borderSoft}` }}>
      <div style={{ fontSize: 11, letterSpacing: 1.4, color: C.muted3 }}>{label}</div>
      <div style={{ fontFamily: FONT.serif, fontSize: 24, color: C.heading, marginTop: 6 }}>{value}</div>
    </div>
  );
}

export function Outbound({ ctx }: { ctx: Ctx }) {
  const [campaigns, setCampaigns] = useState<api.CampaignSummary[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [metrics, setMetrics] = useState<api.CampaignMetrics | null>(null);
  const [contacts, setContacts] = useState<api.OutboundContactRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  // Campaign list (poll so a live campaign's numbers move on their own).
  const refreshList = useCallback(async () => {
    try {
      const list = await api.listCampaigns();
      setCampaigns(list);
      setSelected((prev) => prev ?? (list[0]?.id ?? null));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load campaigns.");
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    refreshList();
    const id = setInterval(refreshList, POLL_MS);
    return () => clearInterval(id);
  }, [refreshList]);

  // Selected campaign detail (metrics + leads), also polled.
  useEffect(() => {
    if (selected == null) return;
    let live = true;
    const load = async () => {
      try {
        const [m, cs] = await Promise.all([api.getCampaignMetrics(selected), api.getCampaignContacts(selected)]);
        if (live) { setMetrics(m); setContacts(cs); }
      } catch {
        /* selection may have gone away; list refresh will correct it */
      }
    };
    load();
    const id = setInterval(load, POLL_MS);
    return () => { live = false; clearInterval(id); };
  }, [selected]);

  const live = metrics?.status === "active";

  return (
    <>
      <PageHeader
        title="Outbound"
        subtitle="Mello calls your contacts toward one goal — confirmations, follow-ups, and more."
        dateLabel={ctx.dateLabel}
        hoursLabel={ctx.hoursLabel}
        livePill={live ? <span style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 14px", borderRadius: 999, border: "1px solid rgba(62,207,142,0.3)", background: "rgba(62,207,142,0.06)", fontSize: 12, letterSpacing: 1, color: C.greenSoft }}>● LIVE</span> : undefined}
      />

      {error && (
        <div style={{ marginTop: 22, borderRadius: 12, border: "1px solid rgba(217,162,115,0.35)", background: "rgba(217,162,115,0.08)", padding: "12px 16px", fontSize: 13.5, color: C.gold2 }}>{error}</div>
      )}

      {loaded && campaigns.length === 0 && !error && (
        <div style={{ marginTop: 24 }}>
          <Panel><EmptyState icon="volume" title="No campaigns yet" body="Outbound campaigns will appear here once created. Each campaign dials a contact list toward one objective, respecting the calling window, consent, and do-not-call rules." /></Panel>
        </div>
      )}

      {campaigns.length > 0 && (
        <>
          {/* Campaign selector */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 26 }}>
            {campaigns.map((c) => {
              const on = c.id === selected;
              return (
                <div key={c.id} onClick={() => setSelected(c.id)} style={{
                  cursor: "pointer", padding: "10px 16px", borderRadius: 11,
                  background: on ? "#1a2a20" : C.panelAlt, border: `1px solid ${on ? C.green : C.border}`,
                  color: on ? C.heading : C.muted, transition: "all .15s ease",
                }}>
                  <div style={{ fontSize: 14.5, fontWeight: 500 }}>{c.name}</div>
                  <div style={{ fontSize: 11.5, color: C.muted3, marginTop: 3 }}>{c.objective_type.replace(/_/g, " ")} · {c.status} · {c.contacts_total} contacts</div>
                </div>
              );
            })}
          </div>

          {/* Headline tiles (the "Active Campaign" view) */}
          {metrics && (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginTop: 20 }}>
                <StatCard label="CALLS MADE" value={String(metrics.calls_made)} sub={`${metrics.contacts_total} contacts in list`} />
                <StatCard label="ANSWER RATE" value={`${metrics.answer_rate_pct}%`} sub={`${metrics.answered} answered`} />
                <StatCard label="QUALIFIED" value={String(metrics.qualified)} sub="reached a person" />
                <StatCard label="BOOKED" value={String(metrics.booked)} sub={`${metrics.goal_completion_rate_pct}% goal completion`} />
              </div>

              {/* Secondary metrics */}
              <Panel eyebrow="CAMPAIGN" title={metrics.name} style={{ marginTop: 18 }}
                right={<Badge kind={metrics.status === "active" ? "active" : "neutral"}>{metrics.status.toUpperCase()}</Badge>}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginTop: 20 }}>
                  <MiniStat label="AVG HANDLE" value={api.durationLabel(metrics.avg_handle_seconds)} />
                  <MiniStat label="VOICEMAIL" value={String(metrics.amd_voicemail)} />
                  <MiniStat label="COST / SUCCESS" value={metrics.cost_per_success_inr != null ? api.formatINR(metrics.cost_per_success_inr) : "—"} />
                  <MiniStat label="SPENT" value={`${api.formatINR(metrics.spent_inr)}${metrics.budget_cap_inr ? " / " + api.formatINR(metrics.budget_cap_inr) : ""}`} />
                  <MiniStat label="OPT-OUTS" value={`${metrics.opt_outs} (${metrics.opt_out_rate_pct}%)`} />
                </div>
              </Panel>

              {/* Leads table */}
              <Panel eyebrow="CONTACTS" title="Lead list" style={{ marginTop: 18 }}>
                <div style={{ marginTop: 18, display: "flex", flexDirection: "column" }}>
                  {contacts.length === 0 && <div style={{ color: C.muted2, fontSize: 14, padding: "12px 0" }}>No contacts in this campaign.</div>}
                  {contacts.map((row) => {
                    const b = dispoBadge(row.last_disposition, row.state);
                    return (
                      <div key={row.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, padding: "13px 4px", borderBottom: `1px solid ${C.borderSoft}` }}>
                        <div style={{ minWidth: 0 }}>
                          <span style={{ fontSize: 14.5, color: C.text, fontWeight: 500 }}>{row.name ?? "—"}</span>
                          <span style={{ fontSize: 13, color: C.muted3, marginLeft: 12, fontFamily: FONT.mono }}>{row.phone}</span>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 14, flexShrink: 0 }}>
                          {row.attempt_count > 0 && <span style={{ fontSize: 12, color: C.muted3 }}>{row.attempt_count} {row.attempt_count === 1 ? "try" : "tries"}</span>}
                          <Badge kind={b.kind}>{b.label}</Badge>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </Panel>
            </>
          )}
        </>
      )}
    </>
  );
}
