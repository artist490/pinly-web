// Посадочная страница тега: /tag/<tag>.
//
// Теги у пинов уже были, но ссылкой вели в поиск по подстроке — у такого
// адреса нет постоянного лица, его не положить в sitemap. Здесь точное
// совпадение тега, свой canonical и свой og:image — по образцу страницы
// категории (/category/[slug]): connection() в корне, чтобы HTML краулера
// содержал пины сразу.

import { Suspense, cache } from "react";
import { connection } from "next/server";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { MasonryGrid } from "@/components/ui/MasonryGrid";
import { SkeletonGrid } from "@/components/ui/SkeletonGrid";
import { pinImageUrl } from "@/lib/pin";
import { tagPins } from "@/lib/server/tags";
import { pageMetadata } from "@/lib/server/seo";

type Props = { params: Promise<{ slug: string }> };

export const instant = false;

// Первая порция нужна и метаданным (og:image), и странице — cache() склеивает
// оба вызова в один запрос к бэкенду.
const tagFeed = cache((tag: string) => tagPins(tag));

function tagFromSlug(slug: string): string | null {
  try {
    const tag = decodeURIComponent(slug).trim().replace(/^#/, "");
    return tag || null;
  } catch {
    return null; // битый процент-энкод — не тег, а мусор в адресе
  }
}

async function TagContent({ params }: Props) {
  const { slug } = await params;
  const tag = tagFromSlug(slug);
  if (!tag) notFound();
  const pins = await tagFeed(tag);
  if (!pins || pins.length === 0) notFound();
  return (
    <section className="mx-auto w-full max-w-shell-wide px-4 pt-4">
      <h1 className="text-2xl font-extrabold sm:text-3xl">#{tag}</h1>
      <p className="mt-1 text-sm text-muted">
        Идеи с этим тегом: {pins.length}
      </p>
      <div className="mt-6">
        <MasonryGrid pins={pins} />
      </div>
      {/* Точных совпадений всегда конечное число; шире — это уже поиск */}
      <p className="py-8 text-center text-sm text-muted">
        Это все пины с тегом «{tag}».{" "}
        <a
          href={`/search?q=${encodeURIComponent(tag)}`}
          className="font-semibold text-accent-strong hover:underline"
        >
          Искать шире
        </a>
      </p>
    </section>
  );
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  await connection();
  const { slug } = await params;
  const tag = tagFromSlug(slug);
  if (!tag) notFound();
  const pins = (await tagFeed(tag)) ?? [];
  return pageMetadata({
    title: `#${tag} — идеи и примеры`,
    description: `Пины пользователей Pinly с тегом «${tag}».`,
    path: `/tag/${encodeURIComponent(tag)}`,
    imageUrl: pins[0] ? pinImageUrl(pins[0]) : undefined,
  });
}

export default async function TagPage({ params }: Props) {
  await connection();
  const { slug } = await params;
  if (!tagFromSlug(slug)) notFound();
  return (
    <Suspense fallback={<SkeletonGrid />}>
      <TagContent params={params} />
    </Suspense>
  );
}
