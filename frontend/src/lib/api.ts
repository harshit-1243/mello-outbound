// Thin client over the Mello FastAPI booking engine.

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
const CLIENT_ID = process.env.NEXT_PUBLIC_CLIENT_ID ?? "1";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? "";

function headers(extra?: Record<string, string>): Record<string, string> {
  const h: Record<string, string> = { ...extra };
  // Only sent when the backend has an API key configured; harmless otherwise.
  if (API_KEY) h["X-API-Key"] = API_KEY;
  return h;
}

function clientUrl(path: string): string {
  return `${API_BASE}/clients/${CLIENT_ID}${path}`;
}

async function asError(res: Response): Promise<never> {
  let detail = `${res.status} ${res.statusText}`;
  try {
    const body = await res.json();
    detail = body.detail ?? body.message ?? detail;
  } catch {
    /* keep default */
  }
  throw new Error(detail);
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(clientUrl(path), { cache: "no-store", headers: headers() });
  if (!res.ok) return asError(res);
  return res.json();
}

// ---- types ----

export type Booking = {
  booking_id: number;
  booking_group_id: string | null;
  option_name: string;
  sport: string;
  court_name: string;
  customer_name: string;
  customer_phone: string;
  slot_date: string; // YYYY-MM-DD
  start_time: string; // HH:MM:SS
  end_time: string; // HH:MM:SS
  sections: string[];
  amount: number;
  status: string;
  source: string;
};

export type ClientInfo = {
  client_id: number;
  name: string;
  business_name: string;
  timezone: string;
  language_preference: string;
  facility_name: string | null;
  address: string | null;
  opening_time: string | null;
  closing_time: string | null;
  slot_duration_minutes: number | null;
  court_count: number;
  sports: string[];
};

export type MemberSummary = {
  member_id: number;
  name: string;
  phone: string;
  membership_type: string;
  status: string; // "active" | "expired"
  since: string;
  end_date: string;
  visits: number;
  spend: number;
  top_sport: string | null;
  group_names: string[];
};

export type OccupancyStatus = "available" | "booked" | "peak" | "blocked";
export type OccupancyCell = { start_time: string; status: OccupancyStatus };
export type OccupancyRow = { court_id: number; court_name: string; cells: OccupancyCell[] };
export type OccupancyGrid = { date: string; times: string[]; rows: OccupancyRow[] };

export type DaySeries = { date: string; label: string; bookings: number; revenue: number };
export type DashboardStats = {
  today: string;
  bookings_today: number;
  revenue_today: number;
  upcoming: number;
  active_members: number;
  total_bookings: number;
  total_revenue: number;
  via_voice: number;
  court_count: number;
  series: DaySeries[];
};

export type CallSummary = {
  call_id: number;
  caller_name: string | null;
  caller_phone: string;
  started_at: string;
  duration_seconds: number;
  outcome: string;
  language: string | null;
  summary: string | null;
};

export type CallTurnInfo = { role: string; text: string; ts: string };
export type CallDetail = CallSummary & { ended_at: string | null; turns: CallTurnInfo[] };

export type UsageMeter = {
  key: string;
  label: string;
  unit: string;
  used: number;
  limit: number;
  pct: number | null;
  status: "ok" | "warn" | "over" | "unknown";
};
export type UsageAlert = { provider: string; message: string; ts: string };
export type Usage = {
  date: string;
  meters: UsageMeter[];
  alerts: UsageAlert[];
  exhausted: boolean;
};

// ---- reads ----

export const getClient = () => getJSON<ClientInfo>("");
export const listBookings = (includeCancelled = false) =>
  getJSON<Booking[]>(`/bookings?include_cancelled=${includeCancelled}`);
export const listMembers = () => getJSON<MemberSummary[]>("/members");
export const getOccupancy = (date: string) => getJSON<OccupancyGrid>(`/occupancy?date=${date}`);
export const getStats = () => getJSON<DashboardStats>("/stats");
export const listCalls = () => getJSON<CallSummary[]>("/calls");
export const getCall = (callId: number) => getJSON<CallDetail>(`/calls/${callId}`);

// Account-wide (not tenant-scoped) — credit/usage monitor.
export async function getUsage(): Promise<Usage> {
  const res = await fetch(`${API_BASE}/usage`, { cache: "no-store", headers: headers() });
  if (!res.ok) return asError(res);
  return res.json();
}

// ---- writes ----

export async function cancelBooking(bookingId: number): Promise<void> {
  const res = await fetch(clientUrl(`/bookings/${bookingId}/cancel`), {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) return asError(res);
}

export async function rescheduleBooking(
  bookingId: number,
  date: string,
  time: string,
): Promise<void> {
  const res = await fetch(clientUrl(`/bookings/${bookingId}/reschedule`), {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify({ date, time }),
  });
  if (!res.ok) return asError(res);
}

// ---- display helpers ----

export function formatTime(t: string): string {
  // "18:00:00" -> "6:00 PM"
  const [h, m] = t.split(":").map(Number);
  const period = h >= 12 ? "PM" : "AM";
  const hour12 = h % 12 === 0 ? 12 : h % 12;
  return `${hour12}:${String(m).padStart(2, "0")} ${period}`;
}

export function formatHour(t: string): string {
  // "18:00:00" -> "6 PM" (compact, for occupancy axis)
  const h = Number(t.split(":")[0]);
  const period = h >= 12 ? "PM" : "AM";
  const hour12 = h % 12 === 0 ? 12 : h % 12;
  return `${hour12} ${period}`;
}

export function formatDate(d: string): string {
  // "2026-06-10" -> "Wed, 10 Jun"
  const date = new Date(`${d}T00:00:00`);
  return date.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
}

export function relativeDay(d: string, today: string): string {
  // "Today", "Tomorrow", or "Wed, 10 Jun"
  const a = new Date(`${d}T00:00:00`);
  const b = new Date(`${today}T00:00:00`);
  const days = Math.round((a.getTime() - b.getTime()) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Tomorrow";
  if (days === -1) return "Yesterday";
  return formatDate(d);
}

export function formatAmount(amount: number): string {
  return amount > 0 ? `₹${amount.toLocaleString("en-IN")}` : "Free";
}

export function formatINR(amount: number): string {
  return `₹${Math.round(amount).toLocaleString("en-IN")}`;
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

const SPORT_EMOJI: Record<string, string> = {
  Football: "⚽",
  Cricket: "🏏",
  Tennis: "🎾",
  Badminton: "🏸",
  Basketball: "🏀",
  Pickleball: "🏓",
};

export function sportEmoji(sport: string): string {
  return SPORT_EMOJI[sport] ?? "🏟️";
}

export function longDate(d: string): string {
  // "2026-06-14" -> "SUNDAY, 14 JUNE"
  const date = new Date(`${d}T00:00:00`);
  return date
    .toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })
    .toUpperCase();
}

export function hoursLabel(open: string | null, close: string | null): string {
  if (!open || !close) return "";
  return `${formatTime(open)} – ${formatTime(close)}`;
}

export function todayISO(): string {
  // Best-effort "today" in IST for the first paint before stats arrive.
  return new Date(Date.now() + 5.5 * 3600_000).toISOString().slice(0, 10);
}

export function durationLabel(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function clockTime(iso: string): string {
  // "2026-06-14T18:04:09" -> "6:04 PM"
  const d = new Date(iso);
  return d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
}
