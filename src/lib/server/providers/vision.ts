// Подпись картинки через vision-модель RouterAI.
//
// Зачем это здесь, а не эмбеддинг картинки напрямую: шлюз RouterAI принимает в
// /v1/embeddings только строки. Data-URL он не декодирует, а токенизирует как
// текст — проверено на cohere/embed-5-fast, voyage-multimodal-3.5 и
// titan-embed-image-v1: косинус «картинка ↔ та же строка текстом» равен 1.0.
// То есть картинка не попадает в модель как картинка ни в одном формате.
//
// Рабочий обход: vision-модель описывает картинку словами, а описание уходит в
// текстовые эмбеддинги. Теряется часть визуального (композиция, фактура), но
// поиск получается смысловой, а не по имени файла в base64.
//
// Настройки из env:
//   VISION_MODEL   — по умолчанию google/gemini-2.5-flash
//   EMBED_API_KEY  — тот же ключ, что у эмбеддингов

const BASE_URL = process.env.EMBED_BASE_URL ?? "https://routerai.ru/api/v1";
const MODEL = process.env.VISION_MODEL ?? "google/gemini-2.5-flash";
const API_KEY = process.env.EMBED_API_KEY ?? process.env.VOYAGE_API_KEY;
const TIMEOUT_MS = 45_000;

// Промт держим в одном месте: подпись, сделанная для запроса-фото, и подпись
// при индексации должны описывать картинку одинаково, иначе их векторы
// разъезжаются по стилю и поиск теряет точность.
const PROMPT =
  "Опиши изображение для поиска по картинкам: 1–2 предложения. Назови главные " +
  "объекты, цвета, материал, стиль и обстановку. Без вступлений и оценок — " +
  "только описание.";

export function visionEnabled(): boolean {
  return Boolean(API_KEY);
}

export function visionModel(): string {
  return MODEL;
}

/** Описание картинки по data-URL. Бросает при отказе провайдера. */
export async function captionImage(dataUrl: string): Promise<string> {
  if (!API_KEY) throw new Error("EMBED_API_KEY не задан");

  const res = await fetch(`${BASE_URL}/chat/completions`, {
    method: "POST",
    headers: { Authorization: `Bearer ${API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: 160,
      messages: [
        {
          role: "user",
          content: [
            { type: "text", text: PROMPT },
            { type: "image_url", image_url: { url: dataUrl } },
          ],
        },
      ],
    }),
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });

  if (!res.ok) {
    const detail = (await res.text().catch(() => "")).slice(0, 200);
    throw new Error(`vision ${res.status}: ${detail}`);
  }

  const payload = (await res.json()) as {
    choices?: Array<{ message?: { content?: string } }>;
  };
  const text = payload.choices?.[0]?.message?.content?.trim();
  if (!text) throw new Error("vision: пустой ответ");
  return text;
}
