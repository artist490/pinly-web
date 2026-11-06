// Серверные данные тегов: точная выдача для страницы /tag/[slug] и тренды.
// Бэкенд — опциональная зависимость: молчит — теги просто не отрисовываются,
// как и остальные серверные блоки.

import { backendJson } from "@/lib/server/backend";
import type { Pin } from "@/lib/pin";

export type TagStat = { tag: string; count: number };

// Тренды меняются медленно, а считаются группировкой по всем пинам:
// десять минут кэша — тот же компромисс, что у sitemap.
const POPULAR_TTL_MS = 10 * 60 * 1000;
let popular: { at: number; tags: TagStat[] } | null = null;

export async function popularTags(limit = 12): Promise<TagStat[]> {
  if (popular && popular.at + POPULAR_TTL_MS > Date.now()) return popular.tags;
  const data = await backendJson<{ tags: TagStat[] }>(
    `/api/tags/popular?limit=${limit}`,
    { timeoutMs: 2500 },
  );
  const tags = data?.tags ?? [];
  // пустой ответ не кэшируем: упавший бэкенд не должен вычёркивать блок
  if (tags.length > 0) popular = { at: Date.now(), tags };
  return tags;
}

/** Пины с точным тегом; null — бэкенд не ответил (страница тогда честно 404). */
export async function tagPins(tag: string, limit = 60): Promise<Pin[] | null> {
  const data = await backendJson<{ pins: Pin[] }>(
    `/api/tags/${encodeURIComponent(tag)}/pins?limit=${limit}`,
    { timeoutMs: 2500 },
  );
  return data ? (data.pins ?? []) : null;
}
