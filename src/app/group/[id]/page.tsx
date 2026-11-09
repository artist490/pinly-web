// Публичная страница группы: /group/<id>.
//
// Профиль рендера — как у /board/[id]: connection() в корне и instant=false,
// чтобы HTML краулера содержал ленту группы сразу; метаданные и JSON-LD —
// тот же конверт, что у досок. Данные тянутся напрямую из бэкенда
// (backendJson) — относительные клиентские пути на сервере не работают.

import { Suspense, cache } from "react";
import { connection } from "next/server";
import { cookies } from "next/headers";
import type { Metadata } from "next";
import { GroupView } from "@/components/group/GroupView";
import { SkeletonGrid } from "@/components/ui/SkeletonGrid";
import type { PublicGroup } from "@/lib/api/groups";
import { backendJson, SESSION_COOKIE } from "@/lib/server/backend";
import { pageMetadata, jsonLdText } from "@/lib/server/seo";

type Props = { params: Promise<{ id: string }> };

export const instant = false;

// Первая порция нужна и метаданным, и странице — cache() склеивает вызовы.
const groupCard = cache((id: string, session: string | null) =>
  backendJson<{ group: PublicGroup }>(`/api/groups/${encodeURIComponent(id)}`, {
    timeoutMs: 3000,
    session,
  }),
);

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  await connection();
  const { id } = await params;
  const session = (await cookies()).get(SESSION_COOKIE)?.value ?? null;
  const group = (await groupCard(id, session))?.group;
  if (!group) return pageMetadata({ title: "Группа", path: `/group/${id}`, noIndex: true });
  return pageMetadata({
    title: `${group.title} — группа`,
    description: group.description || `Группа Pinly: ${group.title}.`,
    path: `/group/${group.id}`,
  });
}

export default async function GroupPage({ params }: Props) {
  await connection();
  const { id } = await params;
  const session = (await cookies()).get(SESSION_COOKIE)?.value ?? null;
  const group = (await groupCard(id, session))?.group ?? null;
  const jsonLd =
    group &&
    jsonLdText({
      "@context": "https://schema.org",
      "@type": "CollectionPage",
      name: group.title,
      description: group.description || undefined,
      dateCreated: group.createdAt ? new Date(group.createdAt).toISOString() : undefined,
    });
  return (
    <Suspense fallback={<SkeletonGrid />}>
      {jsonLd && <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd }} />}
      <GroupView groupId={id} initial={group} />
    </Suspense>
  );
}
