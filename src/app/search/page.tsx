// Страница поиска. Клиентская часть (поле, режимы, выдача) живёт в
// SearchClient.tsx, а сама страница — серверная: под поиском встаёт блок
// популярных тегов, который бэкенд считает по всем пинам.

import { PopularTags } from "@/components/ui/PopularTags";
import { SearchClient } from "./SearchClient";

export default function SearchPage() {
  return (
    <>
      <SearchClient />
      <PopularTags />
    </>
  );
}
