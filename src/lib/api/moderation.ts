// Модерация (backend/moderation.py): жалобы вошедших и очередь для панели.

import { isStatus, requestJson } from "@/lib/api/http";

export type ReportTargetType = "pin" | "board" | "user";
export type ReportReason = "spam" | "copyright" | "offensive";

export type AdminReport = {
  id: string;
  targetType: ReportTargetType;
  targetId: string;
  reason: ReportReason;
  createdAt: number;
  target: {
    title: string | null;
    exists: boolean;
    hidden: boolean;
  };
};

/** Жалоба от вошедшего пользователя. 409 — эту цель он уже отметил. */
export async function apiReport(
  targetType: ReportTargetType,
  targetId: string,
  reason: ReportReason,
): Promise<{ duplicate: boolean }> {
  try {
    await requestJson("/api/reports", {
      method: "POST",
      body: JSON.stringify({ target_type: targetType, target_id: targetId, reason }),
    });
    return { duplicate: false };
  } catch (err) {
    if (isStatus(err, 409)) return { duplicate: true };
    throw err;
  }
}

export async function apiAdminReports(signal?: AbortSignal): Promise<AdminReport[]> {
  const data = await requestJson<{ reports: AdminReport[] }>("/api/admin/reports", { signal });
  return data.reports;
}

export type ResolveAction = "hide_pin" | "ban_user" | "dismiss";

export async function apiResolveReport(reportId: string, action: ResolveAction): Promise<void> {
  await requestJson(`/api/admin/reports/${reportId}/resolve`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });
}
