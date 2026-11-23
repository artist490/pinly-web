"use client";

// Панель модерации: очередь жалоб и вердикты. Доступ определяет бэкенд
// (PINLY_OWNER_EMAIL): не владелец получит 403 уже на запросе, поэтому
// фронтовский гейт — только экономия клика, а не защита.

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  apiAdminReports,
  apiResolveReport,
  type AdminReport,
  type ResolveAction,
} from "@/lib/api/moderation";
import { useUser } from "@/lib/state/session";
import { timeAgo } from "@/lib/time";
import { SignInGate } from "@/components/ui/SignInGate";

const REASON_LABELS: Record<string, string> = {
  spam: "спам или реклама",
  copyright: "авторские права",
  offensive: "неуместный контент",
};

const TARGET_HREFS: Record<AdminReport["targetType"], (id: string) => string> = {
  pin: (id) => `/pin/${id}`,
  board: (id) => `/board/${id}`,
  user: (id) => `/profile/${id}`,
};

// Основное действие по типу цели: пин скрываем, живого человека — баним.
// Для внешнего пина (ov-…) ban_user всё равно не сработает — бэкенд вернёт
// 404, поэтому для внешних целей остаётся только скрытие/отклонение.
function primaryAction(report: AdminReport): ResolveAction | null {
  if (report.targetType === "pin") return "hide_pin";
  if (report.targetType === "board" || report.targetType === "user") return "ban_user";
  return null;
}

const PRIMARY_LABELS: Record<ResolveAction, string> = {
  hide_pin: "Скрыть пин",
  ban_user: "Заблокировать аккаунт",
  dismiss: "Отклонить",
};

function ReportRow({
  report,
  onResolve,
  busy,
}: {
  report: AdminReport;
  onResolve: (id: string, action: ResolveAction) => void;
  busy: boolean;
}) {
  const href = TARGET_HREFS[report.targetType](report.targetId);
  const primary = primaryAction(report);
  const targetLabel =
    report.targetType === "pin" ? "Пин" : report.targetType === "board" ? "Доска" : "Профиль";
  return (
    <li className="flex flex-wrap items-center gap-3 rounded-2xl bg-surface-card px-4 py-3">
      <div className="min-w-0 flex-1">
        <p className="text-sm">
          <span className="font-semibold">{targetLabel}: </span>
          {report.target.exists ? (
            <Link href={href} className="hover:text-accent-strong hover:underline">
              {report.target.title ?? report.targetId}
            </Link>
          ) : (
            <span className="text-muted">{report.targetId} (цель уже удалена)</span>
          )}
          {report.autoReview && (
            <span className="ml-2 rounded-full bg-surface-hover px-2 py-0.5 text-xs font-semibold text-muted">
              авто
            </span>
          )}
        </p>
        <p className="mt-0.5 text-xs text-muted">
          Причина: {REASON_LABELS[report.reason] ?? report.reason} · {timeAgo(report.createdAt)}
          {report.target.hidden && " · цель уже скрыта или заблокирована"}
          {report.autoReview &&
            " · пин скрыт автоматически, «Отклонить» вернёт его в ленту"}
        </p>
        {report.autoReview && report.detail && (
          <p className="mt-0.5 text-xs text-muted">{report.detail}</p>
        )}
      </div>
      <div className="flex shrink-0 gap-2">
        {primary && report.target.exists && (
          <button
            type="button"
            onClick={() => onResolve(report.id, primary)}
            disabled={busy}
            className="min-h-11 rounded-full bg-danger px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-40"
          >
            {PRIMARY_LABELS[primary]}
          </button>
        )}
        <button
          type="button"
          onClick={() => onResolve(report.id, "dismiss")}
          disabled={busy}
          className="min-h-11 rounded-full px-4 py-2 text-sm font-semibold hover:bg-surface-hover disabled:opacity-40"
        >
          Отклонить
        </button>
      </div>
    </li>
  );
}

export default function AdminPage() {
  const { user, ready, enabled } = useUser();
  const [reports, setReports] = useState<AdminReport[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [denied, setDenied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    const controller = new AbortController();
    apiAdminReports(controller.signal)
      .then((list) => {
        setReports(list);
        setDenied(false);
      })
      .catch(() => setDenied(true))
      .finally(() => setLoaded(true));
    return () => controller.abort();
  }, [user]);

  if (!ready || !enabled) return null;
  if (!user)
    return (
      <SignInGate
        title="Модерация"
        hint="Панель жалоб доступна владельцу сайта после входа."
      />
    );
  if (denied && loaded)
    return (
      <main className="mx-auto w-full max-w-shell-text px-4 py-10 text-center">
        <h1 className="text-2xl font-extrabold">Модерация</h1>
        <p className="mt-2 text-sm text-muted">
          Панель доступна только владельцу сайта (email из PINLY_OWNER_EMAIL).
        </p>
        <Link href="/" className="mt-4 inline-block text-sm font-semibold text-accent-strong hover:underline">
          Вернуться в ленту
        </Link>
      </main>
    );
  if (!loaded) return null;

  const resolve = async (id: string, action: ResolveAction) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await apiResolveReport(id, action);
      setReports((prev) => prev.filter((r) => r.id !== id));
    } catch {
      setError("Не удалось применить решение — обновите очередь и попробуйте ещё раз.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto w-full max-w-shell px-4 py-8">
      <h1 className="text-2xl font-extrabold">Модерация</h1>
      <p className="mt-1 text-sm text-muted">
        Открытые жалобы пользователей. Скрытие пина и блокировка аккаунта обратимы:
        данные остаются в базе.
      </p>

      {error && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error}
        </p>
      )}

      {reports.length === 0 ? (
        <p className="mt-8 text-sm text-muted">Открытых жалоб нет — очередь пуста.</p>
      ) : (
        <ul className="mt-6 space-y-3">
          {reports.map((report) => (
            <ReportRow key={report.id} report={report} onResolve={resolve} busy={busy} />
          ))}
        </ul>
      )}
    </main>
  );
}
