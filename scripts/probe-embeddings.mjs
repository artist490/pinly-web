// Диагностика векторного поиска. Показывает то, чего нет в документации
// RouterAI:
//
//   1. принимает ли провайдер параметр dimensions;
//   2. какой из форматов запроса с картинкой работает (cohere-native /
//      openai-parts / data-url) — для картинок формат не описан;
//   3. лежит ли текст и картинка в одном пространстве (косинус «текст своего
//      пина vs картинка своего пина» должен быть выше, чем «текст своего пина
//      vs картинка чужого»);
//   4. совместим ли текущий .cache/vectors.json с настроенной моделью.
//
// Запуск: npm run probe:embeddings   (нужен EMBED_API_KEY в web/.env.local)
// Для пункта 3 нужен запущенный сайт (npm start) — картинки идут через /api/img.

import { readFile } from "node:fs/promises";
import { TASK_QUERY } from "../src/lib/server/providers/embeddings-wire.mjs";
import { STORE_PATH, cosine, embedClient, siteBase } from "./embed-client.mjs";
import { collectFeedPins, pinDataUrl, pinText } from "./pins-source.mjs";

// 1×1 PNG: годится проверить формат запроса, но не смысл косинуса.
const FALLBACK_PNG =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

function line(text) {
  console.log(`\n── ${text}`);
}

async function indexInfo(config) {
  try {
    const store = JSON.parse(await readFile(STORE_PATH, "utf8"));
    const kinds = new Map();
    for (const item of store.items ?? []) kinds.set(item.kind, (kinds.get(item.kind) ?? 0) + 1);
    const compatible = store.version === 3 && store.model === config.model && store.dim === config.dimensions;
    console.log(
      `vectors.json: v${store.version} ${store.model} dim ${store.dim}, векторов: ${
        [...kinds].map(([k, n]) => `${k} ${n}`).join(", ") || "нет"
      }`,
    );
    console.log(
      compatible
        ? "совместим с текущей моделью — сайт его использует"
        : "НЕ совместим с EMBED_MODEL/EMBED_DIMENSIONS: сайт считает такой индекс пустым → npm run index",
    );
    if (!(kinds.get("image") > 0)) {
      console.log("картинок в индексе нет → поиск по фото ищет только по текстам пинов: npm run index -- --images");
    }
  } catch {
    console.log("vectors.json нет — индекс пуст, поиск по фото ответит 503 → npm run index");
  }
}

async function main() {
  const client = await embedClient();
  const { config } = client;
  console.log(`base: ${config.baseUrl}\nmodel: ${config.model}\ndim: ${config.dimensions}`);
  if (!config.key) {
    console.error("\nНет EMBED_API_KEY в env или web/.env.local — дальше проверять нечего.");
    process.exit(1);
  }
  console.log(`ключ: …${config.key.slice(-4)} (${config.key.length} символов)`);

  line("текст");
  try {
    const [vector] = await client.texts(["кошка на подоконнике"]);
    console.log(`OK: вектор длины ${vector.length} (нужно ${config.dimensions})`);
  } catch (err) {
    console.log(`FAIL: ${err.message}`);
    process.exitCode = 1;
  }

  line("картинки: сырые форматы у шлюза");
  const pins = (await collectFeedPins(siteBase())).slice(0, 2);
  const images = [];
  for (const pin of pins) {
    try {
      images.push({ pin, dataUrl: await pinDataUrl(siteBase(), pin) });
    } catch (err) {
      console.log(`картинку пина ${pin.id} получить не удалось: ${err.message}`);
    }
  }
  if (images.length === 0) {
    console.log(
      `через сайт (${siteBase()}) картинки не пришли — проверяю на служебном PNG; сайт запускают так: npm start`,
    );
    images.push({ pin: null, dataUrl: FALLBACK_PNG });
  }

  // Сырые форматы показываем, но вердикт по ним не выносим: шлюз принимает
  // data-URL строкой и возвращает текстовый вектор. Именно поэтому поиск по
  // фото идёт через описание, а не через эмбеддинг картинки.
  const rawFormats = await client.probeImage(images[0].dataUrl);
  const anyRawAccepted = rawFormats.some((r) => r.ok);
  for (const result of rawFormats) {
    console.log(
      result.ok
        ? `OK   ${result.format} ${result.path} → dim ${result.dim}`
        : `FAIL ${result.format} ${result.path} → ${result.error}`,
    );
  }
  if (anyRawAccepted) {
    console.log(
      "внимание: формат принят, но это может быть текстовый вектор от data-URL — проверка ниже это покажет",
    );
  }

  line("картинка → описание → вектор");
  let captionsOk = false;
  try {
    const first = images[0].dataUrl;
    const c0 = await client.caption(first);
    console.log(`описание: ${c0.slice(0, 140)}…`);
    const asText = await client.texts([first], TASK_QUERY);
    const [cVec] = await client.texts([c0], TASK_QUERY);
    const viaImage = await client.image(first, TASK_QUERY);
    // Ключевая проверка: описание не должно совпадать с base64-строкой.
    // Если совпало — картинка не декодируется, и весь поиск идёт по мусору.
    const same = cosine(cVec, asText[0]) > 0.999;
    console.log(
      same
        ? "ПРОВАЛ: описание совпало с текстом data-URL — картинка не декодируется"
        : "OK: описание отличается от data-URL, vision действительно видит картинку",
    );
    captionsOk = !same;
    if (captionsOk) {
      const [queryVec] = await client.texts(["фотография с похожим содержанием"], TASK_QUERY);
      console.log(
        `санити: косинус описания и вектора через image() = ${cosine(cVec, viaImage).toFixed(3)}`,
      );
      console.log(
        `санити: косинус с посторонним запросом              = ${cosine(queryVec, viaImage).toFixed(3)}`,
      );
    }
  } catch (err) {
    console.log(`FAIL: ${err.message}`);
    process.exitCode = 1;
  }

  line("общее пространство текст/картинка");
  if (!captionsOk || images.length < 2 || !images.every((i) => i.pin)) {
    console.log("нужны два настоящих пина и рабочие описания — пропущено");
  } else {
    try {
      // тексты берём в роли запроса — так же, как картинки ниже: сравнивать
      // passage-текст с query-картинкой значит мерить несовпадение ролей
      const [t0] = await client.texts(images.map(({ pin }) => pinText(pin)), TASK_QUERY);
      const v0 = await client.image(images[0].dataUrl, TASK_QUERY);
      const v1 = await client.image(images[1].dataUrl, TASK_QUERY);
      const own = cosine(t0, v0);
      const other = cosine(t0, v1);
      console.log(`свой пин:  ${own.toFixed(3)}   чужой пин: ${other.toFixed(3)}`);
      console.log(
        own > other
          ? "OK: описание своей картинки ближе к своему тексту — поиск по фото ищет по смыслу"
          : "ПОДОЗРИТЕЛЬНО: своей пары не хватает — описания слишком общие",
      );
    } catch (err) {
      console.log(`FAIL: ${err.message}`);
      process.exitCode = 1;
    }
  }

  line("индекс");
  await indexInfo(config);
}

main().catch((e) => {
  console.error("probe failed:", e.message);
  process.exit(1);
});
