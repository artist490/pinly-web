"use client";

// Группы по тематикам: свои группы + публичный каталог, создание инлайном.
// Паттерн — страница /boards: вошедшему свои карточки, гостю вход.

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  apiCreateGroup,
  apiDeleteGroup,
  apiGroups,
  apiMyGroups,
  type Group,
  type MyGroup,
} from "@/lib/api/groups";
import { CATEGORY_PAGES } from "@/lib/categories";
import { countLabel } from "@/lib/plural";
import { useUser } from "@/lib/state/session";
import { useToast } from "@/components/ui/Toast";
import { ConfirmDialog } from "@/components/ui/Confirm";
import { SignInGate } from "@/components/ui/SignInGate";
import { IconCompass } from "@/components/ui/Icons";

function membersLabel(n: number) {
  return countLabel(n, "участник", "участника", "участников");
}

function pinsLabel(n: number) {
  return countLabel(n, "пин", "пина", "пинов");
}

function GroupCard({ group, onDelete }: { group: Group; onDelete?: (g: Group) => void }) {
  return (
    <div className="group relative">
      <Link
        href={`/group/${group.id}`}
        className="flex h-full flex-col rounded-2xl bg-surface-card p-4 transition-colors hover:bg-surface"
      >
        <p className="font-semibold">{group.title}</p>
        {group.description && (
          <p className="mt-1 line-clamp-2 text-sm text-muted">{group.description}</p>
        )}
        <p className="mt-auto pt-3 text-xs text-muted">
          {membersLabel(group.membersCount)} · {pinsLabel(group.pinsCount)}
          {group.category && <span className="ml-2 rounded-full bg-surface px-2 py-0.5">{group.category}</span>}
        </p>
      </Link>
      {onDelete && (
        <button
          type="button"
          onClick={() => onDelete(group)}
          className="absolute right-2 top-2 hidden rounded-full bg-background/90 px-3 py-2 text-xs font-semibold text-foreground shadow hover:bg-background group-hover:block group-focus-within:block"
        >
          Удалить
        </button>
      )}
    </div>
  );
}

export default function GroupsPage() {
  const { user, ready, enabled } = useUser();
  const { show } = useToast();
  const [mine, setMine] = useState<MyGroup[]>([]);
  const [catalog, setCatalog] = useState<Group[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [category, setCategory] = useState<string>("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<Group | null>(null);

  const reload = useCallback(async () => {
    const [catalogGroups, myGroups] = await Promise.all([
      apiGroups().catch(() => []),
      user ? apiMyGroups().catch(() => []) : Promise.resolve([]),
    ]);
    setCatalog(catalogGroups);
    setMine(myGroups);
    setLoaded(true);
  }, [user]);

  useEffect(() => {
    if (!ready || !enabled || !user) return;
    const controller = new AbortController();
    let cancelled = false;
    (async () => {
      const [catalogGroups, myGroups] = await Promise.all([
        apiGroups(undefined, controller.signal).catch(() => []),
        apiMyGroups(controller.signal).catch(() => []),
      ]);
      if (cancelled) return;
      setCatalog(catalogGroups);
      setMine(myGroups);
      setLoaded(true);
    })();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [ready, enabled, user]);

  if (!ready || !enabled) return null;
  if (!user)
    return (
      <SignInGate
        title="Группы по тематикам"
        hint="Войдите, чтобы создавать группы и публиковать в них пины."
      />
    );

  const create = async () => {
    const clean = title.trim();
    if (!clean || creating) return;
    setCreating(true);
    try {
      await apiCreateGroup(clean, { description, category });
      setTitle("");
      setDescription("");
      await reload();
    } catch {
      show("Не удалось создать группу.");
    } finally {
      setCreating(false);
    }
  };

  const remove = async (group: Group) => {
    setConfirmDelete(null);
    try {
      await apiDeleteGroup(group.id);
      setMine((prev) => prev.filter((g) => g.id !== group.id));
    } catch {
      show("Не удалось удалить группу.");
    }
  };

  const catalogFiltered = category ? catalog.filter((g) => g.category === category) : catalog;
  // свои группы в каталоге повторно не показываем
  const mineIds = new Set(mine.map((g) => g.id));
  const foreignCatalog = catalogFiltered.filter((g) => !mineIds.has(g.id));

  return (
    <div className="mx-auto w-full max-w-shell px-4 py-6">
      <h1 className="text-2xl font-extrabold sm:text-3xl">Группы по тематикам</h1>

      {/* Создание: название, тематика, описание — без отдельного экрана */}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && create()}
          placeholder="Название новой группы…"
          maxLength={80}
          className="w-56 rounded-full bg-surface px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-accent/40"
        />
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
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
        <button
          type="button"
          onClick={create}
          disabled={!title.trim() || creating}
          className="rounded-full bg-foreground px-5 py-2.5 text-sm font-semibold text-background hover:opacity-90 disabled:opacity-40"
        >
          Создать
        </button>
      </div>
      <input
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="О чём группа (необязательно)…"
        maxLength={500}
        className="mt-3 w-full max-w-xl rounded-2xl bg-surface px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-accent/40"
      />

      {!loaded && <p className="py-10 text-center text-sm text-muted">Загрузка…</p>}

      {loaded && (
        <>
          <section className="mt-8">
            <h2 className="text-lg font-bold">Мои группы</h2>
            {mine.length === 0 ? (
              <p className="mt-3 text-sm text-muted">
                Вы пока ни в одной группе. Создайте свою или вступите в чужую по тематике.
              </p>
            ) : (
              <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {mine.map((group) => (
                  <GroupCard
                    key={group.id}
                    group={group}
                    onDelete={group.myRole === "owner" ? setConfirmDelete : undefined}
                  />
                ))}
              </div>
            )}
          </section>

          {foreignCatalog.length > 0 && (
            <section className="mt-10">
              <h2 className="text-lg font-bold">Найти по тематике</h2>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setCategory("")}
                  aria-pressed={category === ""}
                  className={`min-h-9 rounded-full px-4 text-sm font-semibold ${
                    category === "" ? "bg-foreground text-background" : "bg-surface text-muted hover:bg-surface-hover"
                  }`}
                >
                  Все
                </button>
                {CATEGORY_PAGES.map((page) => (
                  <button
                    key={page.slug}
                    type="button"
                    onClick={() => setCategory(page.name)}
                    aria-pressed={category === page.name}
                    className={`min-h-9 rounded-full px-4 text-sm font-semibold ${
                      category === page.name
                        ? "bg-foreground text-background"
                        : "bg-surface text-muted hover:bg-surface-hover"
                    }`}
                  >
                    {page.name}
                  </button>
                ))}
              </div>
              <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {foreignCatalog.map((group) => (
                  <GroupCard key={group.id} group={group} />
                ))}
              </div>
            </section>
          )}

          {loaded && mine.length === 0 && foreignCatalog.length === 0 && (
            <div className="py-16 text-center">
              <p className="grid place-items-center text-muted">
                <IconCompass size={40} />
              </p>
              <p className="mt-3 text-muted">Групп пока нет — создайте первую.</p>
            </div>
          )}
        </>
      )}

      <ConfirmDialog
        open={confirmDelete !== null}
        title={confirmDelete ? `Удалить группу «${confirmDelete.title}»?` : ""}
        body="Лента группы и список участников исчезнут. Пины сами по себе останутся."
        onCancel={() => setConfirmDelete(null)}
        onConfirm={() => confirmDelete && remove(confirmDelete)}
      />
    </div>
  );
}
