import {
  Booking,
  CallSummary,
  ClientInfo,
  DashboardStats,
  MemberSummary,
  OccupancyGrid,
  Usage,
} from "@/lib/api";
import { PageId } from "@/components/Sidebar";

// Everything the dashboard shell fetches, passed down to each page. The shell owns the
// single polling loop so a booking made by phone shows up on every page at once.
export type Ctx = {
  client: ClientInfo | null;
  stats: DashboardStats | null;
  bookings: Booking[];
  members: MemberSummary[];
  occupancy: OccupancyGrid | null;
  calls: CallSummary[];
  usage: Usage | null;
  today: string;
  dateLabel: string;
  hoursLabel: string;
  refresh: () => void;
  goTo: (p: PageId) => void;
};
