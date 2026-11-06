"use client";

// Комментарии к пину: список с ответами (один уровень вложенности, как
// у Пинтереста), лайки комментариев, форма для вошедших, удаление своего
// (любого — если пин ваш).

import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  apiAddComment,
  apiComments,
  apiDeleteComment,
  apiLikeComment,
  apiUnlikeComment,
  type Comment,
} from "@/lib/api/social";
import { useUser } from "@/lib/state/session";
import { countLabel } from "@/lib/plural";
import { timeAgo } from "@/lib/time";
import { Avatar } from "@/components/ui/Avatar";
import { IconHeart, IconTrash } from "@/components/ui/Icons";

function CommentStats({ comment }: { comment: Comment }) {
  return (
    <>
      <span className="ml-2 text-xs text-muted">{timeAgo(comment.createdAt)}</span>
      {comment.likes > 0 && (
        <span className="ml-2 text-xs text-muted">
          {countLabel(comment.likes, "лайк", "лайка", "лайков")}
        </span>
      )}
    </>
  );
}

function CommentActions({
  comment,
  canDelete,
  busy,
  onReply,
  onToggleLike,
  onRemove,
}: {
  comment: Comment;
  canDelete: boolean;
  busy: boolean;
  onReply: () => void;
  onToggleLike: () => void;
  onRemove: () => void;
}) {
  const { user } = useUser();
  const liked = comment.likedByMe;
  return (
    <div className="mt-1 flex items-center gap-1 text-xs">
      <button
        type="button"
        onClick={onReply}
        className="rounded-full px-2 py-1 font-semibold text-muted hover:bg-surface-hover hover:text-foreground"
      >
        Ответить
      </button>
      {user ? (
        <button
          type="button"
          onClick={onToggleLike}
          disabled={busy}
          aria-pressed={liked}
          aria-label={liked ? "Убрать лайк" : "Поставить лайк"}
          className={`flex min-h-8 items-center gap-1 rounded-full px-2 py-1 transition-colors ${
            liked ? "text-accent-strong" : "text-muted hover:bg-surface-hover"
          }`}
        >
          <IconHeart size={12} filled={liked} />
          {comment.likes > 0 && <span>{comment.likes}</span>}
        </button>
      ) : (
        <Link
          href="/login"
          aria-label="Войдите, чтобы поставить лайк"
          className="flex min-h-8 items-center gap-1 rounded-full px-2 py-1 text-muted hover:bg-surface-hover"
        >
          <IconHeart size={12} />
          {comment.likes > 0 && <span>{comment.likes}</span>}
        </Link>
      )}
      {canDelete && (
        <button
          type="button"
          onClick={onRemove}
          disabled={busy}
          aria-label="Удалить комментарий"
          className="grid h-8 w-8 place-items-center rounded-full text-muted hover:bg-surface-hover hover:text-danger disabled:opacity-50"
        >
          <IconTrash size={12} />
        </button>
      )}
    </div>
  );
}

function CommentItem({
  comment,
  pinOwnerId,
  busy,
  onReply,
  onRemove,
  onToggleLike,
}: {
  comment: Comment;
  pinOwnerId?: string;
  busy: boolean;
  onReply: (comment: Comment) => void;
  onRemove: (commentId: string) => void;
  onToggleLike: (comment: Comment) => void;
}) {
  const { user } = useUser();
  const canDelete = (c: Comment) =>
    !!user && (c.author.id === user.id || user.id === pinOwnerId);

  return (
    <li className="flex gap-3">
      <Avatar name={comment.author.name} url={comment.author.avatarUrl} size={36} />
      <div className="min-w-0 flex-1">
        <p className="text-sm">
          <Link
            href={`/profile/${comment.author.id}`}
            className="font-semibold hover:text-accent-strong"
          >
            {comment.author.name}
          </Link>
          <CommentStats comment={comment} />
        </p>
        <p className="mt-1 text-sm break-words">{comment.text}</p>
        <CommentActions
          comment={comment}
          canDelete={canDelete(comment)}
          busy={busy}
          onReply={() => onReply(comment)}
          onToggleLike={() => onToggleLike(comment)}
          onRemove={() => onRemove(comment.id)}
        />
        {comment.replies.length > 0 && (
          <ul className="mt-3 space-y-3 border-l-2 border-border-soft pl-3">
            {comment.replies.map((reply) => (
              <li key={reply.id} className="flex gap-2">
                <Avatar name={reply.author.name} url={reply.author.avatarUrl} size={28} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm">
                    <Link
                      href={`/profile/${reply.author.id}`}
                      className="font-semibold hover:text-accent-strong"
                    >
                      {reply.author.name}
                    </Link>
                    <CommentStats comment={reply} />
                  </p>
                  <p className="mt-1 text-sm break-words">{reply.text}</p>
                  <CommentActions
                    comment={reply}
                    canDelete={canDelete(reply)}
                    busy={busy}
                    onReply={() => onReply(comment)}
                    onToggleLike={() => onToggleLike(reply)}
                    onRemove={() => onRemove(reply.id)}
                  />
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}

export function Comments({ pinId, pinOwnerId }: { pinId: string; pinOwnerId?: string }) {
  const { user, enabled } = useUser();
  const [items, setItems] = useState<Comment[]>([]);
  const [text, setText] = useState("");
  const [replyTo, setReplyTo] = useState<{ id: string; name: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const reload = useCallback(async () => {
    try {
      setItems(await apiComments(pinId));
    } catch {
      // бэкенд аккаунтов недоступен — комментариев не показываем
    }
  }, [pinId]);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    apiComments(pinId, controller.signal)
      .then((list) => {
        if (!cancelled) setItems(list);
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [pinId]);

  if (!enabled || !loaded) return null;

  const post = async () => {
    const clean = text.trim();
    if (!clean || busy) return;
    setBusy(true);
    setError(null);
    try {
      await apiAddComment(pinId, clean, replyTo?.id);
      setText("");
      setReplyTo(null);
      await reload();
    } catch {
      setError("Не удалось отправить комментарий.");
    } finally {
      setBusy(false);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    post();
  };

  const remove = async (commentId: string) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await apiDeleteComment(commentId);
      await reload();
    } catch {
      setError("Не удалось удалить комментарий.");
    } finally {
      setBusy(false);
    }
  };

  // Оптимистичный тоггл: счётчик и флаг меняются сразу, ответ сервера
  // (актуальный счётчик) подтверждает или исправляет состояние.
  const toggleLike = async (comment: Comment) => {
    if (busy) return;
    const apply = (list: Comment[]): Comment[] =>
      list.map((c) => {
        const patch = (item: Comment): Comment =>
          item.id === comment.id
            ? {
                ...item,
                likedByMe: !item.likedByMe,
                likes: Math.max(0, item.likes + (item.likedByMe ? -1 : 1)),
              }
            : { ...item, replies: item.replies.map(patch) };
        return patch(c);
      });
    setItems(apply);
    try {
      const likes = comment.likedByMe
        ? await apiUnlikeComment(comment.id)
        : await apiLikeComment(comment.id);
      setItems((list) =>
        list.map((c) => {
          const sync = (item: Comment): Comment =>
            item.id === comment.id
              ? { ...item, likes }
              : { ...item, replies: item.replies.map(sync) };
          return sync(c);
        }),
      );
    } catch {
      setItems(apply); // откат оптимистичного обновления
      setError("Не удалось поставить лайк.");
    }
  };

  const startReply = (comment: Comment) => {
    setReplyTo({ id: comment.id, name: comment.author.name });
  };

  const countAll = items.reduce((sum, c) => sum + 1 + c.replies.length, 0);
  const viewerName = user?.displayName ?? "Я";

  return (
    <section className="mt-8">
      <h2 className="text-lg font-bold">
        {countAll > 0
          ? countLabel(countAll, "комментарий", "комментария", "комментариев")
          : "Комментарии"}
      </h2>

      <ul className="mt-4 space-y-4">
        {items.map((comment) => (
          <CommentItem
            key={comment.id}
            comment={comment}
            pinOwnerId={pinOwnerId}
            busy={busy}
            onReply={startReply}
            onRemove={remove}
            onToggleLike={toggleLike}
          />
        ))}
      </ul>

      {user ? (
        <form onSubmit={submit} className="mt-5 flex gap-3">
          <Avatar name={viewerName} url={user.avatarUrl} size={36} />
          <div className="min-w-0 flex-1">
            {replyTo && (
              <p className="mb-1 text-xs text-muted">
                Ответ{" "}
                <Link href={`/profile/${replyTo.id}`} className="font-semibold">
                  {replyTo.name}
                </Link>{" "}
                <button
                  type="button"
                  onClick={() => setReplyTo(null)}
                  className="ml-1 text-muted underline hover:text-foreground"
                >
                  отменить
                </button>
              </p>
            )}
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) post();
              }}
              placeholder={replyTo ? `Ответить ${replyTo.name}…` : "Добавьте комментарий…"}
              rows={2}
              maxLength={1000}
              className="w-full resize-none rounded-2xl bg-surface px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-accent/40"
            />
            <div className="mt-2 flex items-center gap-3">
              <button
                type="submit"
                disabled={busy || !text.trim()}
                className="rounded-full bg-foreground px-5 py-2 text-sm font-semibold text-background hover:opacity-90 disabled:opacity-40"
              >
                Отправить
              </button>
              <span className="text-xs text-muted">Ctrl+Enter — отправить</span>
              {error && <span role="alert" className="text-sm text-danger">{error}</span>}
            </div>
          </div>
        </form>
      ) : (
        <p className="mt-5 text-sm text-muted">
          <Link href="/login" className="font-semibold text-accent-strong hover:underline">
            Войдите
          </Link>
          , чтобы оставить комментарий.
        </p>
      )}
    </section>
  );
}
