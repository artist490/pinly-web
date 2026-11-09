// Эмбеддинги через RouterAI (https://routerai.ru). Модель по умолчанию —
// cohere/embed-5-fast: мультимодальная, то есть текст и картинка ложатся в одно
// пространство, поэтому поиск по фото ищет среди пинов, проиндексированных по
// тексту, и наоборот. Провайдер OpenAI-совместим, база — /api/v1.
//
// Настройки из env:
//   EMBED_API_KEY       — ключ routerai.ru (fallback: VOYAGE_API_KEY)
//   EMBED_MODEL         — по умолчанию cohere/embed-5-fast
//   EMBED_DIMENSIONS    — по умолчанию 1024 (у модели 256…2048 на выбор)
//   EMBED_BASE_URL      — по умолчанию https://routerai.ru/api/v1
// Без ключа весь векторный поиск мягко выключается.
//
// ВАЖНО: векторы разных моделей несовместимы для косинуса. Хранилище помнит
// имя модели (см. vector-store.ts), при смене нужна переиндексация
// `npm run index`.
//
// Формат запроса с картинкой страница модели не показывает: заявлен
// OpenAI-совместимый /embeddings с текстовым примером. Поэтому сюда идут
// варианты по очереди (родной формат Cohere — первым), победитель запоминается
// на процесс, а `npm run probe:embeddings` показывает, какой именно сработал.

import { cached } from "@/lib/server/providers/cache";
import {
  imageRequests,
  parseVectors,
  TASK_QUERY,
  textBody,
  toDataUrl,
} from "@/lib/server/providers/embeddings-wire.mjs";

const BASE_URL =
  process.env.EMBED_BASE_URL ?? process.env.VOYAGE_BASE_URL ?? "https://routerai.ru/api/v1";
const MODEL = process.env.EMBED_MODEL ?? "cohere/embed-5-fast";
const DIMENSIONS = Number(process.env.EMBED_DIMENSIONS ?? 1024);
const API_KEY = process.env.EMBED_API_KEY ?? process.env.VOYAGE_API_KEY;
const TIMEOUT_MS = 30_000;

export type EmbeddingModel = { name: string; dim: number };

/** Что сейчас проиндексировано — нужно хранилищу, чтобы не смешивать векторы. */
export const EMBEDDING_MODEL: EmbeddingModel = { name: MODEL, dim: DIMENSIONS };

export function embeddingsEnabled(): boolean {
  return Boolean(API_KEY);
}

/** Ответ провайдера с кодом статуса: по 400 выбирают другой формат запроса. */
class EmbeddingsError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

function headers(): Record<string, string> {
  return { Authorization: `Bearer ${API_KEY}`, "Content-Type": "application/json" };
}

async function post(path: string, body: unknown): Promise<unknown> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (!res.ok) {
    const detail = (await res.text().catch(() => "")).slice(0, 200);
    throw new EmbeddingsError(res.status, `${path} ${res.status}: ${detail}`);
  }
  return res.json();
}

// ── текст ────────────────────────────────────────────────────────────────

// Роль запроса разделяет запрос и документ: одна и та же строка в разных ролях
// даёт разные векторы, и без этого косинус «запрос ↔ пин» теряет точность.
// Индексатор передаёт search_document (см. embedTexts), а живой поиск по слову —
// search_query.
async function callText(
  input: string[],
  withDimensions: boolean,
  task?: string,
): Promise<number[][]> {
  const payload = await post(
    "/embeddings",
    textBody(MODEL, input, DIMENSIONS, withDimensions, task),
  );
  return parseVectors(payload, input.length, DIMENSIONS) as number[][];
}

async function embedTextInput(input: string[], task?: string): Promise<number[][]> {
  try {
    return await callText(input, true, task);
  } catch (err) {
    // часть провайдеров не знает dimensions или input_type — режем вектор сами
    if (!(err instanceof EmbeddingsError) || err.status !== 400) throw err;
    return callText(input, false);
  }
}

// ── картинки: форматы перебирает проводка, победитель запоминается ───────

let workingFormat: string | null = null;
/** Принят ли хоть один формат, где картинка кодируется как картинка. */
let imageFormatWorks = false;

/** Отличить «картинка кодируется» от «data-URL ушёл текстом». */
export function imageEmbeddingsWork(): boolean {
  return imageFormatWorks;
}

/**
 * Эмбеддинги картинок по data-URL. Формат запроса подбирается: первый
 * успешный запоминается, остальные не дёргаются. task по умолчанию — запрос:
 * основной сценарий картинки — «найди похожее».
 *
 * Формат `data-url` помечен textOnly: провайдер, который картинок не понимает,
 * принимает строку и возвращает её текстовый вектор — векторы есть, поиск
 * «работает», но ищет по base64. Такой ответ считаем неудачей и не кэшируем
 * как рабочий формат.
 */
export async function embedImageDataUrls(
  urls: string[],
  task: string = TASK_QUERY,
): Promise<number[][]> {
  if (!embeddingsEnabled()) throw new Error("EMBED_API_KEY не задан");
  const requests = imageRequests(MODEL, urls, DIMENSIONS, task);
  const winner = requests.find((r) => r.format === workingFormat);
  const order = winner ? [winner, ...requests.filter((r) => r !== winner)] : requests;
  let lastError: unknown = null;

  for (const request of order) {
    try {
      const payload = await post(request.path, request.body);
      const vectors = parseVectors(payload, urls.length, DIMENSIONS) as number[][];
      if (request.textOnly) {
        lastError = new Error(
          `${request.format} принят, но это текстовый вектор от data-URL — картинка не кодируется`,
        );
        continue;
      }
      if (workingFormat !== request.format) {
        console.info(`[embeddings] формат картинок: ${request.format}`);
        workingFormat = request.format;
        imageFormatWorks = true;
      }
      return vectors;
    } catch (err) {
      lastError = err;
    }
  }
  throw new Error(`ни один формат запроса с картинкой не принят: ${String(lastError)}`);
}

export function imageBytesToDataUrl(bytes: Uint8Array, mime: string): string {
  return toDataUrl(mime, bytes) as string;
}


/** Одна картинка по data-URL — то, что нужно для запроса «найди похожее». */
export async function embedImage(dataUrl: string): Promise<number[] | null> {
  if (!embeddingsEnabled()) return null;
  const [vector] = await embedImageDataUrls([dataUrl]);
  return vector ?? null;
}

// ── кэш батчей ───────────────────────────────────────────────────────────

function hashText(text: string): string {
  // FNV-1a: короткий стабильный ключ кэша
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(36);
}

// Эмбеддинги текстов с кэшем: повторный запуск индексатора не платит за
// тот же состав батча. В ключе — модель, размерность и задача: векторы
// query и passage одной строки разные, и общий ключ подменил бы один другим.
export async function embedTexts(
  texts: string[],
  task: string = TASK_QUERY,
): Promise<number[][] | null> {
  if (!embeddingsEnabled()) return null;
  const results: number[][] = new Array(texts.length);

  for (let i = 0; i < texts.length; i += 32) {
    const batch = texts.slice(i, i + 32);
    const batchKey = `emb-batch:${MODEL}:${DIMENSIONS}:${task}:${hashText(batch.join("\u0000"))}`;
    const vectors = await cached(batchKey, () => embedTextInput(batch, task));
    batch.forEach((_, j) => {
      results[i + j] = vectors[j];
    });
  }
  return results;
}

/** Что именно сейчас настроено — показывают диагностика и probe-скрипт. */
export function embeddingConfig(): EmbeddingModel & { baseUrl: string; enabled: boolean } {
  return { ...EMBEDDING_MODEL, baseUrl: BASE_URL, enabled: embeddingsEnabled() };
}
