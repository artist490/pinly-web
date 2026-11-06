// Блок трендов: самые частые теги по всем пинам (backend/pins.py popular_tags).
// Серверный компонент: данные приходят до гидрации, бэкенд молчит — блок
// просто не рисуется, как и остальные серверные витрины.

import Link from "next/link";
import { popularTags } from "@/lib/server/tags";

export async function PopularTags({ heading = "Популярные теги" }: { heading?: string }) {
  const tags = await popularTags();
  if (tags.length === 0) return null;
  return (
    <section className="mx-auto w-full max-w-shell-wide px-4 pb-8">
      <h2 className="text-lg font-bold">{heading}</h2>
      <ul className="mt-3 flex flex-wrap gap-2">
        {tags.map(({ tag, count }) => (
          <li key={tag}>
            <Link
              href={`/tag/${encodeURIComponent(tag)}`}
              className="flex min-h-8 items-center rounded-full border border-border-soft bg-background px-3 py-1.5 text-sm text-muted hover:bg-surface"
            >
              #{tag}
              <span className="ml-1.5 text-xs">{count}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
