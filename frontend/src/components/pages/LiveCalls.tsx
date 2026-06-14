"use client";

import React, { useEffect, useState } from "react";
import { C, FONT } from "@/lib/theme";
import { PageHeader, Footer, Icon, Badge } from "@/components/ui";
import { CallSummary, CallDetail, getCall, clockTime, durationLabel } from "@/lib/api";
import { Ctx } from "./types";

// A dim, idle waveform — visual texture for the "waiting" state, not a playing call.
const IDLE_WAVE = [10, 16, 22, 14, 26, 30, 20, 12, 28, 18, 24, 32, 16, 22, 28, 14, 20, 26, 30, 18, 12, 24, 16, 22, 28, 20, 14, 18, 24, 12, 16, 22, 28, 18, 14, 24, 20, 16, 12, 22, 18, 14, 20, 16, 12, 18];

const PIPELINE = [
  { step: "Speech-to-text", tech: "Sarvam · Hindi + English code-switching" },
  { step: "Reasoning", tech: "Cerebras zai-glm-4.7 · booking tools" },
  { step: "Text-to-speech", tech: "Sarvam bulbul · natural Hinglish voice" },
  { step: "Telephony", tech: "Exotel inbound number" },
];

function outcomeKind(o: string): "booked" | "missed" | "handled" {
  return o === "booked" ? "booked" : o === "missed" ? "missed" : "handled";
}

export function LiveCalls({ ctx }: { ctx: Ctx }) {
  const { calls } = ctx;
  return (
    <div>
      <PageHeader
        title="Live Calls"
        subtitle={calls.length ? `${calls.length} calls logged · newest first` : "Voice line activates after telephony KYC"}
      />
      {calls.length ? <CallConsole calls={calls} /> : <PendingConsole />}
      <Footer />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Populated: call list (left) + transcript detail (right)
// ---------------------------------------------------------------------------

function CallConsole({ calls }: { calls: CallSummary[] }) {
  const [selectedId, setSelectedId] = useState<number>(calls[0]?.call_id);
  const [detail, setDetail] = useState<CallDetail | null>(null);
  const [loading, setLoading] = useState(false);

  // Keep a valid selection as the call list refreshes.
  useEffect(() => {
    if (!calls.some((c) => c.call_id === selectedId) && calls[0]) setSelectedId(calls[0].call_id);
  }, [calls, selectedId]);

  useEffect(() => {
    if (selectedId == null) return;
    let live = true;
    setLoading(true);
    getCall(selectedId)
      .then((d) => { if (live) setDetail(d); })
      .catch(() => { if (live) setDetail(null); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [selectedId]);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "380px 1fr", gap: 18, marginTop: 26, alignItems: "start" }}>
      {/* List */}
      <div style={{ borderRadius: 16, background: C.panel, border: `1px solid ${C.border}`, overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9, padding: "15px 16px", borderBottom: `1px solid ${C.borderSoft}`, color: C.muted3, fontSize: 13.5 }}>
          <Icon name="search" size={15} stroke={1.8} />Search by phone, name…
        </div>
        <div style={{ padding: 10 }}>
          {calls.map((c) => {
            const active = c.call_id === selectedId;
            return (
              <div key={c.call_id} onClick={() => setSelectedId(c.call_id)} style={{
                display: "flex", alignItems: "center", gap: 13, padding: "13px 13px", borderRadius: 12, marginBottom: 4, cursor: "pointer",
                border: `1px solid ${active ? "rgba(62,207,142,0.28)" : "transparent"}`,
                background: active ? "rgba(62,207,142,0.05)" : "transparent",
              }}>
                <div style={{ width: 38, height: 38, borderRadius: "50%", background: C.card2, border: `1px solid ${C.divider}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 17, flexShrink: 0 }}>📞</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14.5, color: C.display, fontWeight: 500 }}>{c.caller_name ?? c.caller_phone}</div>
                  <div style={{ fontSize: 12, color: C.muted3, fontFamily: FONT.mono, marginTop: 3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.caller_phone}</div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
                  <Badge kind={outcomeKind(c.outcome)}>{c.outcome}</Badge>
                  <span style={{ fontSize: 11.5, color: C.faint }}>{clockTime(c.started_at)}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Detail */}
      <div style={{ padding: "30px 34px", borderRadius: 16, background: C.panel, border: `1px solid ${C.border}` }}>
        {detail ? (
          <>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div style={{ fontSize: 11, letterSpacing: 2, color: C.faint, fontFamily: FONT.mono }}>CALL · {String(detail.call_id).padStart(4, "0")}</div>
              <Badge kind={outcomeKind(detail.outcome)}>{detail.outcome}</Badge>
            </div>
            <h2 style={{ fontFamily: FONT.serif, fontWeight: 500, fontSize: 38, color: C.heading, margin: "14px 0 0", lineHeight: 1.1 }}>
              {detail.caller_name ?? detail.caller_phone}
            </h2>
            <div style={{ fontSize: 13.5, color: C.muted, fontFamily: FONT.mono, marginTop: 12 }}>
              {detail.caller_phone} · {durationLabel(detail.duration_seconds)} · {clockTime(detail.started_at)}
              {detail.language ? ` · ${detail.language}` : ""}
            </div>

            <div style={{ fontSize: 11, letterSpacing: 2, color: C.faint, marginTop: 28 }}>TRANSCRIPT</div>
            <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 13 }}>
              {detail.turns.map((t, i) => {
                const mello = t.role === "assistant";
                return (
                  <div key={i} style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
                    <span style={{ fontFamily: FONT.mono, fontSize: 12, color: C.faint, width: 56, paddingTop: 15, flexShrink: 0 }}>{clockTime(t.ts)}</span>
                    <div style={{ flex: 1, padding: "14px 18px", borderRadius: 14, border: `1px solid ${mello ? "rgba(62,207,142,0.18)" : C.divider}`, background: mello ? "rgba(62,207,142,0.05)" : C.panelAlt }}>
                      <div style={{ fontSize: 11, letterSpacing: 1.5, fontFamily: FONT.mono, color: mello ? C.greenSoft : C.muted }}>{mello ? "MELLO" : "CALLER"}</div>
                      <div style={{ fontSize: 15, color: C.text, marginTop: 7, lineHeight: 1.4 }}>{t.text}</div>
                    </div>
                  </div>
                );
              })}
            </div>

            {detail.summary && (
              <div style={{ marginTop: 24, padding: "16px 20px", borderRadius: 13, background: C.inset, border: `1px solid ${C.border}`, fontSize: 13.5, color: C.muted }}>
                {detail.summary}
              </div>
            )}
          </>
        ) : (
          <div style={{ height: 200, display: "flex", alignItems: "center", justifyContent: "center", color: C.faint }}>
            {loading ? "Loading transcript…" : "Select a call"}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty: voice-line-pending console
// ---------------------------------------------------------------------------

function PendingConsole() {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "380px 1fr", gap: 18, marginTop: 26, alignItems: "start" }}>
      <div style={{ borderRadius: 16, background: C.panel, border: `1px solid ${C.border}`, overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9, padding: "15px 16px", borderBottom: `1px solid ${C.borderSoft}`, color: C.muted3, fontSize: 13.5 }}>
          <Icon name="search" size={15} stroke={1.8} />Search by phone, name…
        </div>
        <div style={{ padding: "48px 24px", textAlign: "center" }}>
          <div style={{ display: "flex", justifyContent: "center", marginBottom: 14, color: C.faint }}><Icon name="phone" size={26} stroke={1.5} /></div>
          <div style={{ fontSize: 15, color: C.body }}>No calls yet</div>
          <div style={{ fontSize: 13, color: C.muted2, marginTop: 8, lineHeight: 1.5 }}>Answered calls appear here in real time, with full transcript.</div>
        </div>
      </div>

      <div style={{ padding: "30px 34px", borderRadius: 16, background: C.panel, border: `1px solid ${C.border}` }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div style={{ fontSize: 11, letterSpacing: 2, color: C.faint, fontFamily: FONT.mono }}>VOICE AGENT · STANDBY</div>
          <Badge kind="gold">Pending Sarvam key + Exotel KYC</Badge>
        </div>
        <h2 style={{ fontFamily: FONT.serif, fontWeight: 500, fontSize: 38, color: C.heading, margin: "14px 0 0", lineHeight: 1.1 }}>Waiting for the first call</h2>
        <div style={{ fontSize: 14.5, color: C.muted, marginTop: 12, lineHeight: 1.5, maxWidth: 520 }}>
          Mello&apos;s voice agent is built and tested end-to-end. Live calls — with transcript, outcome,
          and booking — stream here and are saved automatically.
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 18, marginTop: 26, padding: "18px 22px", borderRadius: 14, background: C.inset, border: `1px solid ${C.border}` }}>
          <div style={{ width: 46, height: 46, borderRadius: "50%", background: C.divider, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
            <Icon name="play" size={16} color={C.muted2} fill={C.muted2} stroke={0} />
          </div>
          <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 2, height: 42 }}>
            {IDLE_WAVE.map((h, i) => <div key={i} style={{ width: 3, height: h, borderRadius: 2, background: C.divider }} />)}
          </div>
          <span style={{ fontFamily: FONT.mono, fontSize: 13, color: C.muted3 }}>idle</span>
        </div>

        <div style={{ fontSize: 11, letterSpacing: 2, color: C.faint, marginTop: 28 }}>PIPELINE</div>
        <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 12 }}>
          {PIPELINE.map((p) => (
            <div key={p.step} style={{ display: "flex", alignItems: "center", gap: 14, padding: "12px 16px", borderRadius: 11, background: C.inset, border: `1px solid ${C.border}` }}>
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: C.green, flexShrink: 0 }} />
              <span style={{ fontSize: 14, color: C.display, width: 120, flexShrink: 0 }}>{p.step}</span>
              <span style={{ fontSize: 13, color: C.muted2, fontFamily: FONT.mono }}>{p.tech}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
