// Офлайн-заглушка: сервис-worker отдаёт её вместо навигации, когда сеть
// недоступна и страницы нет в кэше. Статичная, без данных и запросов.
import Link from "next/link";

export const metadata = { title: "Нет сети" };

export default function OfflinePage() {
  return (
    <main className="mx-auto w-full max-w-shell-text px-4 py-16 text-center">
      <p className="text-4xl" aria-hidden>
        📡
      </p>
      <h1 className="mt-3 text-2xl font-extrabold sm:text-3xl">Нет сети</h1>
      <p className="mt-2 text-sm text-muted">
        Эта страница не сохранилась в кэше, а интернет недоступен. Проверьте
        соединение и попробуйте снова.
      </p>
      <Link
        href="/"
        className="mt-5 inline-flex min-h-11 items-center rounded-full bg-foreground px-5 text-sm font-semibold text-background hover:opacity-90"
      >
        Попробовать снова
      </Link>
    </main>
  );
}
