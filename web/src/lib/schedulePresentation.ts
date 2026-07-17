import type { RunSchedule } from "./types";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function scheduleRule(schedule: Pick<RunSchedule, "cadence" | "weekday" | "local_time" | "timezone">): string {
  const day = schedule.cadence === "weekly" ? ` · ${DAYS[schedule.weekday ?? 0]}` : "";
  return `${schedule.cadence}${day} · ${schedule.local_time} ${schedule.timezone}`;
}

export function nextScheduleLabel(schedule: Pick<RunSchedule, "enabled" | "next_due_at" | "last_outcome">, locale = "en-US"): string {
  const next = schedule.enabled && schedule.next_due_at
    ? `Next ${new Date(schedule.next_due_at).toLocaleString(locale)}`
    : "No next run";
  return schedule.last_outcome ? `${next} · last ${schedule.last_outcome}` : next;
}

