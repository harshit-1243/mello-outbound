"use client";

import { useCallback, useEffect, useState } from "react";
import { Sidebar, PageId } from "@/components/Sidebar";
import { Overview } from "@/components/pages/Overview";
import { LiveCalls } from "@/components/pages/LiveCalls";
import { Outbound } from "@/components/pages/Outbound";
import { Bookings } from "@/components/pages/Bookings";
import { Members } from "@/components/pages/Members";
import { Reports } from "@/components/pages/Reports";
import { Settings } from "@/components/pages/Settings";
import { Ctx } from "@/components/pages/types";
import { C, FONT, MAIN_BG } from "@/lib/theme";
import * as api from "@/lib/api";

const POLL_MS = 6000;
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export default function Dashboard() {
  const [page, setPage] = useState<PageId>("overview");
  const [client, setClient] = useState<api.ClientInfo | null>(null);
  const [stats, setStats] = useState<api.DashboardStats | null>(null);
  const [bookings, setBookings] = useState<api.Booking[]>([]);
  const [members, setMembers] = useState<api.MemberSummary[]>([]);
  const [occupancy, setOccupancy] = useState<api.OccupancyGrid | null>(null);
  const [calls, setCalls] = useState<api.CallSummary[]>([]);
  const [usage, setUsage] = useState<api.Usage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [c, s, b, m, ca] = await Promise.all([
        api.getClient(),
        api.getStats(),
        api.listBookings(),
        api.listMembers(),
        api.listCalls(),
      ]);
      setClient(c);
      setStats(s);
      setBookings(b);
      setMembers(m);
      setCalls(ca);
      try {
        setOccupancy(await api.getOccupancy(s.today));
      } catch {
        /* occupancy is non-critical */
      }
      try {
        setUsage(await api.getUsage());
      } catch {
        /* usage monitor is non-critical */
      }
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to reach the booking engine.");
    } finally {
      setLoaded(true);
    }
  }, []);

  // Initial load + polling so bookings made by phone appear on their own.
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  const today = stats?.today ?? api.todayISO();
  const ctx: Ctx = {
    client, stats, bookings, members, occupancy, calls, usage, today,
    dateLabel: api.longDate(today),
    hoursLabel: api.hoursLabel(client?.opening_time ?? "06:00:00", client?.closing_time ?? "23:00:00"),
    refresh,
    goTo: setPage,
  };

  const creditAlert = usage?.exhausted
    ? usage.alerts.at(-1)?.message ?? "A provider's free credits look exhausted."
    : null;

  return (
    <div style={{ display: "flex", minHeight: "100vh", width: "100%", background: C.pageBg, fontFamily: FONT.sans, color: C.body }}>
      <Sidebar page={page} onNavigate={setPage} client={client} />
      <main style={{ flex: 1, minWidth: 0, padding: "34px 44px 56px", background: MAIN_BG }}>
        {creditAlert && (
          <div style={{ marginBottom: 18, borderRadius: 12, border: "1px solid rgba(224,139,128,0.5)", background: "rgba(224,139,128,0.12)", padding: "12px 16px", fontSize: 13.5, color: "#e08b80", display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontWeight: 600 }}>⚠ Free credits alert:</span>
            <span style={{ fontFamily: FONT.mono, fontSize: 12.5 }}>{creditAlert}</span>
          </div>
        )}
        {error && (
          <div style={{ marginBottom: 18, borderRadius: 12, border: "1px solid rgba(217,162,115,0.35)", background: "rgba(217,162,115,0.08)", padding: "12px 16px", fontSize: 13.5, color: C.gold2 }}>
            {error} — is the booking engine running at <span style={{ fontFamily: FONT.mono }}>{API_BASE}</span>?
          </div>
        )}

        {!loaded && !error ? (
          <div style={{ height: "60vh", display: "flex", alignItems: "center", justifyContent: "center", gap: 12, color: C.muted2 }}>
            <span style={{ width: 16, height: 16, borderRadius: "50%", border: `2px solid ${C.divider}`, borderTopColor: C.green, animation: "spin 0.8s linear infinite", display: "inline-block" }} />
            Connecting to the booking engine…
          </div>
        ) : (
          <>
            {page === "overview" && <Overview ctx={ctx} />}
            {page === "liveCalls" && <LiveCalls ctx={ctx} />}
            {page === "outbound" && <Outbound ctx={ctx} />}
            {page === "bookings" && <Bookings ctx={ctx} />}
            {page === "members" && <Members ctx={ctx} />}
            {page === "reports" && <Reports ctx={ctx} />}
            {page === "settings" && <Settings ctx={ctx} />}
          </>
        )}
      </main>
    </div>
  );
}
