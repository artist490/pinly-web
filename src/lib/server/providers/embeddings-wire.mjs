// Проводка запросов к провайдеру эмбеддингов: один источник правды для сайта
// (TS) и индексатора (node-скрипт). Держится в .mjs без типов и алиасов, чтобы
// его можно было импортировать с обеих сторон без сборки.
//
// Провайдер по умолчанию — RouterAI (https://routerai.ru), модель
// cohere/embed-5-fast: мультимодальная (текст и картинки в одном пространстве),
// 128K контекста, размерность 256…2048 на выбор. Страница модели обещает
// картинки, но формат тела с картинкой не показывает, поэтому варианты
// перебираются, а победитель запоминается — `npm run probe:embeddings` печатает,
// какой сработал.

/**
 * Роли запроса у Cohere: документ при индексации и запрос при поиске — разные.
 * Подмена одной на другую тихо роняет качество, поэтому роль есть и в ключе
 * кэша батчей.
 */
export const TASK_QUERY = "search_query";
export const TASK_PASSAGE = "search_document";

/**
 * Тело текстового запроса. dimensions и input_type принимают не все
 * провайдеры, поэтому оба поля опциональны, а вызывающий код умеет повторить
 * запрос без них.
 */
export function textBody(model, input, dimensions, withDimensions, task) {
  return {
    model,
    input,
    encoding_format: "float",
    ...(withDimensions ? { dimensions } : {}),
    ...(task ? { input_type: task } : {}),
  };
}

/**
 * Запросы с картинками в порядке правдоподобия:
 *  1. родной формат Cohere: /embeddings с inputs = [{content: [image_url]}] и
 *     input_type — так модель обучена видеть картинки;
 *  2. OpenAI-совместимый /embeddings, где картинка — часть содержимого input;
 *  3. /embeddings, куда data-URL передают обычной строкой input (так умеет
 *     PlusVibe — но там картинка превращается в текст, см. docs/embeddings.md).
 *
 * Провайдер, который поля не знает, ответит 400, и его заменит следующий формат.
 */
export function imageRequests(model, urls, dimensions, task) {
  const content = urls.map((url) => [{ type: "image_url", image_url: { url } }]);
  return [
    {
      format: "cohere-native",
      path: "/embeddings",
      body: {
        model,
        inputs: content.map((parts) => ({ content: parts })),
        input_type: task ?? TASK_PASSAGE,
        embedding_types: ["float"],
        ...(dimensions ? { output_dimension: dimensions } : {}),
      },
    },
    {
      format: "openai-parts",
      path: "/embeddings",
      body: textBody(model, content, dimensions, true, task),
    },
    {
      format: "voyage-native",
      path: "/multimodalembeddings",
      body: {
        model,
        inputs: content.map((parts) => ({ content: parts })),
        input_type: task ?? TASK_PASSAGE,
        ...(dimensions ? { output_dimension: dimensions } : {}),
      },
    },
    {
      // Последним — потому что этот формат опаснее всех: провайдер, который
      // картинок не понимает, примет строку и вернёт её текстовый вектор.
      // Векторы будут, поиск будет работать, но искать он будет по имени
      // файла в base64. Помечено textOnly, чтобы вызывающий код не принял
      // такой «успех» за мультимодальность.
      format: "data-url",
      textOnly: true,
      path: "/embeddings",
      body: textBody(model, urls, dimensions, true, task),
    },
  ];
}

/** Ответ OpenAI-совместимого или voyage-совместимого эндпоинта. */
export function parseVectors(payload, expected, dimensions) {
  // Cohere-native кладёт векторы в embeddings.float, OpenAI — в data[].embedding
  const flat = payload?.embeddings?.float;
  if (Array.isArray(flat)) return flat.slice(0, expected);
  const data = payload?.data;
  if (!Array.isArray(data) || data.length === 0) throw new Error("embeddings: пустой ответ");
  return data.slice(0, expected).map((item) => {
    if (!Array.isArray(item?.embedding)) throw new Error("embeddings: нет поля embedding");
    // Matryoshka: лишние измерения отрезаются, смысл остаётся в первых
    return item.embedding.slice(0, dimensions);
  });
}

/** data: URL для запроса с картинкой. */
export function toDataUrl(mime, bytes) {
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return `data:${mime};base64,${Buffer.from(binary, "binary").toString("base64")}`;
}
