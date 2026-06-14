"use client";

import React, { useState } from "react";
import { C, FONT } from "@/lib/theme";
import { OccupancyWidget, Footer, Icon, EmptyState, PageHeader } from "@/components/ui";
import {
  Booking, cancelBooking, rescheduleBooking, formatTime, formatINR, relativeDay, sportEmoji,
} from "@/lib/api";
import { Ctx } from "./types";

function BookingCard({ b, today, onReschedule, onCancel, busy }: {
  b: Booking; today: string; onReschedule: () => void; onCancel: () => void; busy: boolean;
}) {
  const fullCourt = b.sections.length > 1;
  const isMember = b.amount === 0;
  return (
    <div style={{ padding: "24px 26px", borderRadius: 16, background: C.panel, border: `1px solid ${C.border}`, display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <span style={{ fontSize: 22 }}>{sportEmoji(b.sport)}</span>
        <span style={{ fontSize: 11, letterSpacing: 1.5, color: fullCourt ? C.gold2 : C.muted2, fontFamily: FONT.mono }}>
          {fullCourt ? "FULL COURT" : b.court_name.toUpperCase()}
        </span>
      </div>
      <div style={{ fontFamily: FONT.serif, fontSize: 38, fontWeight: 500, color: C.heading, marginTop: 22, lineHeight: 1 }}>
        {formatTime(b.start_time)}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 13.5, color: C.muted, marginTop: 12 }}>
        <Icon name="clock" size={13} stroke={2} />
        {b.sport} · {relativeDay(b.slot_date, today)}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginTop: 24, paddingTop: 18, borderTop: `1px solid ${C.borderSoft}` }}>
        <div>
          <div style={{ fontSize: 15, color: C.display }}>{b.customer_name}</div>
          <div style={{ fontSize: 12.5, color: C.muted2, marginTop: 4 }}>
            {isMember ? "member" : "non-member"} · {formatINR(b.amount)}
          </div>
        </div>
        {isMember && <Icon name="check" size={20} color={C.green} stroke={1.8} />}
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <button onClick={onReschedule} disabled={busy} style={btnStyle(false, busy)}>Reschedule</button>
        <button onClick={onCancel} disabled={busy} style={btnStyle(true, busy)}>Cancel</button>
      </div>
    </div>
  );
}

function btnStyle(danger: boolean, busy: boolean): React.CSSProperties {
  return {
    flex: 1, padding: "8px 0", borderRadius: 9, fontSize: 12.5, fontWeight: 500, cursor: busy ? "default" : "pointer",
    background: "transparent", border: `1px solid ${danger ? "rgba(217,120,110,0.35)" : C.divider}`,
    color: danger ? "#e08b80" : C.body, opacity: busy ? 0.5 : 1,
  };
}

function bookingSortKey(b: Booking): string {
  return `${b.slot_date}${b.start_time}`;
}

function hourOptions(open: string | null, close: string | null): number[] {
  const openH = open ? Number(open.split(":")[0]) : 6;
  const closeH = close ? Number(close.split(":")[0]) : 22;
  const end = Math.max(openH + 1, closeH);
  return Array.from({ length: end - openH }, (_, i) => openH + i);
}

function RescheduleModal({ booking, openTime, closeTime, onClose, onDone }: {
  booking: Booking; openTime: string | null; closeTime: string | null; onClose: () => void; onDone: () => void;
}) {
  const [date, setDate] = useState(booking.slot_date);
  const [time, setTime] = useState(booking.start_time.slice(0, 5));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setSaving(true); setErr(null);
    try { await rescheduleBooking(booking.booking_id, date, time); onDone(); }
    catch (e) { setErr(e instanceof Error ? e.message : "Reschedule failed."); }
    finally { setSaving(false); }
  }

  const field: React.CSSProperties = {
    marginTop: 6, width: "100%", borderRadius: 10, border: `1px solid ${C.divider}`,
    background: C.inset, color: C.display, padding: "11px 13px", fontSize: 14, fontFamily: FONT.sans,
  };

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 20, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(6,12,9,0.6)", padding: 16 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ width: "100%", maxWidth: 380, borderRadius: 16, background: C.panel, border: `1px solid ${C.border}`, padding: 26 }}>
        <div style={{ fontFamily: FONT.serif, fontSize: 24, color: C.heading, fontWeight: 500 }}>Reschedule booking</div>
        <div style={{ fontSize: 13.5, color: C.muted, marginTop: 6 }}>{booking.customer_name} · {booking.option_name}</div>

        <label style={{ display: "block", fontSize: 13, color: C.muted, marginTop: 20 }}>Date</label>
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} style={field} />

        <label style={{ display: "block", fontSize: 13, color: C.muted, marginTop: 16 }}>Start time</label>
        <select value={time} onChange={(e) => setTime(e.target.value)} style={field}>
          {hourOptions(openTime, closeTime).map((h) => {
            const v = `${String(h).padStart(2, "0")}:00`;
            return <option key={v} value={v} style={{ background: C.inset }}>{formatTime(`${v}:00`)}</option>;
          })}
        </select>

        {err && <div style={{ marginTop: 14, borderRadius: 9, background: "rgba(217,120,110,0.1)", border: "1px solid rgba(217,120,110,0.3)", padding: "9px 12px", fontSize: 13, color: "#e08b80" }}>{err}</div>}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 24 }}>
          <button onClick={onClose} style={{ borderRadius: 9, border: `1px solid ${C.divider}`, background: "transparent", color: C.body, padding: "9px 16px", fontSize: 13.5, cursor: "pointer" }}>Cancel</button>
          <button onClick={submit} disabled={saving} style={{ borderRadius: 9, border: "none", background: C.gold, color: "#0b1610", padding: "9px 18px", fontSize: 13.5, fontWeight: 600, cursor: saving ? "default" : "pointer", opacity: saving ? 0.6 : 1 }}>
            {saving ? "Saving…" : "Confirm"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function Bookings({ ctx }: { ctx: Ctx }) {
  const { bookings, occupancy, today, client, refresh } = ctx;
  const [busyId, setBusyId] = useState<number | null>(null);
  const [rescheduling, setRescheduling] = useState<Booking | null>(null);

  const upcoming = [...bookings]
    .filter((b) => b.status === "confirmed" && b.slot_date >= today)
    .sort((a, b) => bookingSortKey(a).localeCompare(bookingSortKey(b)));

  async function onCancel(b: Booking) {
    if (!confirm(`Cancel ${b.customer_name}'s ${b.option_name} booking?`)) return;
    setBusyId(b.booking_id);
    try { await cancelBooking(b.booking_id); refresh(); }
    catch (e) { alert(e instanceof Error ? e.message : "Cancel failed."); }
    finally { setBusyId(null); }
  }

  return (
    <div>
      <PageHeader title="Bookings" subtitle="Today's courts · upcoming reservations" />

      <div style={{ marginTop: 26 }}>
        <OccupancyWidget grid={occupancy} />
      </div>

      <div style={{ marginTop: 18 }}>
        {upcoming.length === 0 ? (
          <div style={{ borderRadius: 16, background: C.panel, border: `1px solid ${C.border}` }}>
            <EmptyState icon="calendar" title="No upcoming bookings" body="Reservations made by phone or on the floor will appear here as cards." />
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 18 }}>
            {upcoming.map((b) => (
              <BookingCard key={b.booking_id} b={b} today={today} busy={busyId === b.booking_id}
                onReschedule={() => setRescheduling(b)} onCancel={() => onCancel(b)} />
            ))}
          </div>
        )}
      </div>

      <Footer />

      {rescheduling && (
        <RescheduleModal
          booking={rescheduling}
          openTime={client?.opening_time ?? null}
          closeTime={client?.closing_time ?? null}
          onClose={() => setRescheduling(null)}
          onDone={() => { setRescheduling(null); refresh(); }}
        />
      )}
    </div>
  );
}
