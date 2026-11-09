// Поиск по фото: картинка запроса → описание словами (vision-модель) →
// эмбеддинг cohere/embed-5-fast → ближайшие пины в том же пространстве.
//
// Почему через описание, а не эмбеддингом картинки напрямую: шлюз RouterAI
// принимает в /v1/embeddings только строки и data-URL токенизирует как текст.
// Проверено на cohere/embed-5-fast, voyage-multimodal-3.5 и titan-embed-image-v1:
// косинус «картинка ↔ та же строка текстом» равен 1.0, то есть пиксели в модель
// не попадают ни в одном формате. Поэтому картинка сначала переводится в слова
// (см. providers/vision.ts), и уже описание ищется в текстовом индексе.

import type { Pin } from "@/lib/pin";
import {
  embedTexts,
  embeddingsEnabled,
  imageBytesToDataUrl,
} from "@/lib/server/providers/embeddings";
import { captionImage, visionEnabled } from "@/lib/server/providers/vision";
import { loadStore, searchVectors } from "@/lib/server/vector-store";
import { sniffImageType } from "@/lib/server/img-proxy";

// Разумный потолок для фотографии с телефона: больше — уже не «найти похожее»,
// а загрузка альбома.
export const MAX_PHOTO_BYTES = 5 * 1024 * 1024;

export type PhotoSearchOutcome =
  | { status: "ok"; pins: Pin[]; indexed: number; caption: string }
  | { status: "no-key" }
  | { status: "empty-index" }
  | { status: "bad-image" }
  | { status: "too-large" }
  | { status: "upstream-failed"; message: string };

/** Тип по сигнатуре байтов, а не по заголовку запроса: браузер шлёт что угодно. */
function detectMime(bytes: Uint8Array): string | null {
  return sniffImageType(bytes);
}

export async function searchByPhoto(bytes: Uint8Array, limit = 24): Promise<PhotoSearchOutcome> {
  // Сначала сам файл: «это не картинка» — ошибка клиента при любой
  // конфигурации сервера. Иначе без ключа любой мусор давал бы 503, и
  // человек никогда не узнал бы, что дело в файле.
  if (bytes.length === 0) return { status: "bad-image" };
  if (bytes.length > MAX_PHOTO_BYTES) return { status: "too-large" };

  const mime = detectMime(bytes);
  if (!mime) return { status: "bad-image" };

  if (!embeddingsEnabled() || !visionEnabled()) return { status: "no-key" };

  const store = await loadStore();
  if (store.items.length === 0) return { status: "empty-index" };

  // Два платных вызова подряд: описание картинки, затем вектор описания.
  // Поэтому всё, что можно проверить без сети, проверено выше.
  let caption: string;
  let vector: number[] | null;
  try {
    caption = await captionImage(imageBytesToDataUrl(bytes, mime));
    const vectors = await embedTexts([caption]);
    vector = vectors?.[0] ?? null;
  } catch (err) {
    return { status: "upstream-failed", message: String(err).slice(0, 200) };
  }
  if (!vector) return { status: "no-key" };

  const hits = await searchVectors(vector, limit);
  // Порог близости: без него «похожие» выдают мусор с хвоста распределения,
  // когда в индексе нет ничего годного.
  const MIN_SCORE = 0.2;
  return {
    status: "ok",
    pins: hits.filter((h) => h.score >= MIN_SCORE).map((h) => h.pin),
    // Пинов, а не векторов: один пин лежит в индексе и текстом, и описанием
    // его картинки.
    indexed: new Set(store.items.map((it) => it.pin.id)).size,
    caption,
  };
}
