"use client";

// Публичная страница группы: шапка с названием и тематикой, лента пинов,
// участники и роли. Своя группа — с переименованием и удалением; чужая —
// с кнопкой вступления. Гость видит ленту, но не участников-действий.
//
// Профиль рендера — как у /board/[id]: серверная порция (initial) приходит с
// страницы, поэтому HTML краулера содержит ленту сразу, а клиент повторно
// бэкенд не спрашивает. Дальше состояние обновляется ответом API после
// действий — единый объект PublicGroup, без отдельного кэша.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import type { Pin } from "@/lib/pin";
import {
  apiDeleteGroup,
  apiGroup,
  apiGroupMembers,
  apiJoinGroup,
  apiLeaveGroup,
  apiSetMemberRole,
  apiUpdateGroup,
  type GroupMember,
  type GroupRole,
  type PublicGroup,
} from "@/lib/api/groups";
import { CATEGORY_PAGES } from "@/lib/categories";
import { countLabel } from "@/lib/plural";
import { useUser } from "@/lib/state/session";
import { Avatar } from "@/components/ui/Avatar";
import { ConfirmDialog } from "@/components/ui/Confirm";
import { MasonryGrid } from "@/components/ui/MasonryGrid";
import { useToast } from "@/components/ui/Toast";
import {
  IconCheck,
  IconCompass,
  IconInbox,
  IconPencil,
  IconTrash,
  IconUserPlus,
} from "@/components/ui/Icons";

const ROLE_LABEL: Record<GroupRole, string> = {
  owner: "владелец",
  poster: "может публиковать",
  member: "участник",
};

function membersLabel(n: number) {
  return countLabel(n, "участник", "участника", "участников");
}

function pinsLabel(n: number) {
  return countLabel(n, "пин", "пина", "пинов");
}

function NotFound() {
  return (
    <div className="py-20 text-center">
      <p className="grid place-items-center text-muted">
        <IconCompass size={40} />
      </p>
      <p className="mt-3 text-muted">Такой группы нет.</p>
      <Link
        href="/groups"
        className="mt-5 inline-block rounded-full bg-foreground px-5 py-2.5 text-sm font-semibold text-background hover:opacity-90"
      >
        К списку групп
      </Link>
    </div>
  );
}

export function GroupView({
  groupId,
  initial,
}: {
  groupId: string;
  /** Срез, приехавший с сервера: без него краулер видел «Загрузка…». */
  initial: PublicGroup | null;
}) {
  const { user } = useUser();
  const { show } = useToast();
  const router = useRouter();
  // Храним вместе с id: при переходе между группами ответ предыдущей
  // показан быть не может.
  const [state, setState] = useState<{ id: string; group: PublicGroup | null }>({
    id: groupId,
    group: initial,
  });
  const [members, setMembers] = useState<GroupMember[]>([]);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [draft, setDraft] = useState({ title: "", description: "", category: "" });

  const group = state.id === groupId ? state.group : null;
  const myRole = group?.myRole ?? null;
  const isOwner = myRole === "owner";
  const canPost = myRole === "owner" || myRole === "poster";

  const refresh = useCallback(async () => {
    const fresh = await apiGroup(groupId).catch(() => undefined);
    if (fresh !== undefined) setState({ id: groupId, group: fresh });
    return fresh;
  }, [groupId]);

  // Участники видны только вошедшему: список профилей — не публичные данные.
  // Состояние не чистим синхронно в эффекте (это каскадный рендер): список
  // просто не рисуется, когда зритель вышел.
  useEffect(() => {
    if (!user) return;
    const controller = new AbortController();
    let cancelled = false;
    apiGroupMembers(groupId, controller.signal)
      .then((list) => {
        if (!cancelled) setMembers(list);
      })
      .catch(() => {
        if (!cancelled) setMembers([]);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [groupId, user, group?.membersCount]);

  const join = async () => {
    if (!user) return;
    setBusy(true);
    try {
      await apiJoinGroup(groupId);
      await refresh();
    } catch {
      show("Не удалось вступить в группу.");
    } finally {
      setBusy(false);
    }
  };

  const leave = async () => {
    setBusy(true);
    try {
      await apiLeaveGroup(groupId);
      await refresh();
    } catch {
      show("Не удалось выйти из группы.");
    } finally {
      setBusy(false);
    }
  };

  const startEdit = () => {
    if (!group) return;
    setDraft({
      title: group.title,
      description: group.description,
      category: group.category,
    });
    setEditing(true);
  };

  const saveEdit = async () => {
    if (!group) return;
    const title = draft.title.trim();
    if (!title) return;
    setBusy(true);
    try {
      await apiUpdateGroup(group.id, {
        title,
        description: draft.description.trim(),
        category: draft.category,
      });
      await refresh();
      setEditing(false);
    } catch {
      show("Не удалось сохранить изменения.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!group) return;
    setConfirmDelete(false);
    try {
      await apiDeleteGroup(group.id);
      router.push("/groups");
    } catch {
      show("Не удалось удалить группу.");
    }
  };

  const setRole = async (member: GroupMember) => {
    const next = member.role === "poster" ? "member" : "poster";
    try {
      await apiSetMemberRole(groupId, member.id, next);
      setMembers((prev) =>
        prev.map((m) => (m.id === member.id ? { ...m, role: next } : m)),
      );
    } catch {
      show("Не удалось изменить роль.");
    }
  };

  if (!group) return <NotFound />;

  const pins: Pin[] = group.pins;

  return (
    <div className="mx-auto w-full max-w-shell px-4 py-6">
      <div className="text-center">
        {editing ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              saveEdit();
            }}
            className="mx-auto max-w-xl space-y-3"
          >
            <input
              autoFocus
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              maxLength={80}
              aria-label="Название группы"
              className="w-full rounded-full bg-surface px-4 py-2 text-center text-xl font-extrabold outline-none focus:ring-2 focus:ring-accent/40"
            />
            <input
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              maxLength={500}
              placeholder="О чём группа"
              aria-label="Описание группы"
              className="w-full rounded-2xl bg-surface px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-accent/40"
            />
            <select
              value={draft.category}
              onChange={(e) => setDraft({ ...draft, category: e.target.value })}
              aria-label="Тематика группы"
              className="rounded-full bg-surface px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-accent/40"
            >
              <option value="">Без тематики</option>
              {CATEGORY_PAGES.map((page) => (
                <option key={page.slug} value={page.name}>
                  {page.name}
                </option>
              ))}
            </select>
            <div className="flex justify-center gap-2">
              <button
                type="submit"
                disabled={!draft.title.trim() || busy}
                className="min-h-11 rounded-full bg-foreground px-5 text-sm font-semibold text-background hover:opacity-90 disabled:opacity-40"
              >
                Сохранить
              </button>
              <button
                type="button"
                onClick={() => setEditing(false)}
                className="min-h-11 rounded-full px-5 text-sm font-semibold text-muted hover:bg-surface-hover"
              >
                Отмена
              </button>
            </div>
          </form>
        ) : (
          <>
            <div className="flex items-center justify-center gap-2">
              <h1 className="text-2xl font-extrabold sm:text-3xl">{group.title}</h1>
              {isOwner && (
                <button
                  type="button"
                  aria-label="Изменить группу"
                  onClick={startEdit}
                  className="grid h-11 w-11 place-items-center rounded-full text-muted hover:bg-surface-hover sm:h-8 sm:w-8"
                >
                  <IconPencil size={15} />
                </button>
              )}
            </div>
            {group.description && (
              <p className="mx-auto mt-2 max-w-shell-text text-sm text-muted">
                {group.description}
              </p>
            )}
            <p className="mt-1 text-sm text-muted">
              {membersLabel(group.membersCount)} · {pinsLabel(group.pinsCount)}
              {group.category && (
                <span className="ml-2 rounded-full bg-surface px-2 py-0.5 text-xs">
                  {group.category}
                </span>
              )}
            </p>
            <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
              {!myRole && user && (
                <button
                  type="button"
                  onClick={join}
                  disabled={busy}
                  className="flex min-h-11 items-center gap-2 rounded-full bg-foreground px-4 text-sm font-semibold text-background hover:opacity-90 disabled:opacity-40"
                >
                  <IconUserPlus size={14} />
                  Вступить
                </button>
              )}
              {myRole && (
                <span className="flex min-h-11 items-center gap-2 rounded-full bg-surface px-4 text-sm font-semibold text-muted">
                  <IconCheck size={14} />
                  Вы {ROLE_LABEL[myRole]}
                </span>
              )}
              {myRole && !isOwner && (
                <button
                  type="button"
                  onClick={leave}
                  disabled={busy}
                  className="min-h-11 rounded-full px-4 text-sm font-semibold text-muted hover:bg-surface-hover disabled:opacity-40"
                >
                  Выйти
                </button>
              )}
              {!user && (
                <Link
                  href="/login"
                  className="flex min-h-11 items-center gap-2 rounded-full bg-foreground px-4 text-sm font-semibold text-background hover:opacity-90"
                >
                  <IconUserPlus size={14} />
                  Войти, чтобы вступить
                </Link>
              )}
              {isOwner && (
                <button
                  type="button"
                  onClick={() => setConfirmDelete(true)}
                  className="flex min-h-11 items-center gap-2 rounded-full px-4 text-sm font-semibold text-muted hover:bg-surface-hover"
                >
                  <IconTrash size={14} />
                  Удалить группу
                </button>
              )}
            </div>
            {canPost && (
              <p className="mt-2 text-xs text-muted">
                Сохраняйте пины в группу из меню пина — лента соберётся здесь.
              </p>
            )}
          </>
        )}
      </div>

      <ConfirmDialog
        open={confirmDelete}
        title={`Удалить группу «${group.title}»?`}
        body="Лента группы и список участников исчезнут. Пины сами по себе останутся."
        onCancel={() => setConfirmDelete(false)}
        onConfirm={remove}
      />

      {pins.length === 0 ? (
        <div className="py-16 text-center">
          <p className="grid place-items-center text-muted">
            <IconInbox size={40} />
          </p>
          <p className="mt-3 text-muted">В группе пока нет пинов.</p>
          <Link
            href="/"
            className="mt-5 inline-block rounded-full bg-foreground px-5 py-2.5 text-sm font-semibold text-background hover:opacity-90"
          >
            В ленту
          </Link>
        </div>
      ) : (
        <div className="mt-6">
          <MasonryGrid pins={pins} />
        </div>
      )}

      {user && members.length > 0 && (
        <section className="mt-10">
          <h2 className="text-lg font-bold">Участники</h2>
          <ul className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {members.map((member) => (
              <li
                key={member.id}
                className="flex items-center gap-3 rounded-2xl bg-surface-card px-3 py-2"
              >
                <Avatar url={member.avatarUrl} size={36} />
                <div className="min-w-0 flex-1">
                  <Link
                    href={`/profile/${member.id}`}
                    className="block truncate text-sm font-semibold hover:underline"
                  >
                    {member.name}
                  </Link>
                  <p className="text-xs text-muted">{ROLE_LABEL[member.role]}</p>
                </div>
                {member.canManage && member.role !== "owner" && (
                  <button
                    type="button"
                    onClick={() => setRole(member)}
                    className="shrink-0 rounded-full bg-surface px-3 py-1.5 text-xs font-semibold hover:bg-surface-hover"
                  >
                    {member.role === "poster" ? "Забрать право" : "Разрешить публикацию"}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
