# Хранилище Pinly: один SQLite-файл, одна схема, один упорядоченный список
# миграций. Больше нигде соединения не открываются и таблицы не создаются.
#
# Файл живёт в web/.data/accounts.db (переопределяется PINLY_DATA_DIR — этот
# путь подменяют тесты, чтобы не трогать боевую базу). Колонки и таблицы
# переименовывать нельзя: база реальных пользователей уже лежит на диске.

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("PINLY_DATA_DIR") or WEB_ROOT / ".data")
DB_PATH = DATA_DIR / "accounts.db"

# Порядок создания = порядок зависимостей: ссылки users(id) должны существовать
# до таблиц, которые на них ссылаются.
SCHEMA = """
create table if not exists users (
  id            text primary key,
  email         text not null unique,
  password_hash text not null,
  display_name  text not null default '',
  avatar_url    text,
  is_blocked    integer not null default 0,
  created_at    real not null
);
create table if not exists consent_log (
  id          integer primary key autoincrement,
  user_id     text not null,
  email       text not null,
  kind        text not null,
  doc_version text not null,
  user_agent  text,
  created_at  real not null
);
create table if not exists boards (
  id         text primary key,
  user_id    text not null references users(id) on delete cascade,
  title      text not null,
  created_at real not null,
  is_secret  integer not null default 0
);
create table if not exists board_pins (
  board_id text not null references boards(id) on delete cascade,
  pin_id   text not null,
  pin_data text not null,
  added_at real not null,
  primary key (board_id, pin_id)
);
create table if not exists likes (
  user_id    text not null references users(id) on delete cascade,
  pin_id     text not null,
  created_at real not null,
  primary key (user_id, pin_id)
);
create table if not exists pins (
  id          text primary key,
  user_id     text not null references users(id) on delete cascade,
  title       text not null default 'Без названия',
  description text not null default '',
  category    text not null default '',
  tags        text not null default '[]',
  width       integer not null default 800,
  height      integer not null default 1200,
  file        text not null,
  is_hidden   integer not null default 0,
  created_at  real not null
);
create index if not exists pins_user_idx on pins (user_id, created_at desc);
create index if not exists pins_category_idx on pins (category, created_at desc);
create table if not exists pin_slides (
  id          text primary key,
  pin_id      text not null references pins(id) on delete cascade,
  position    integer not null,
  kind        text not null,
  file        text not null default '',
  width       integer not null default 0,
  height      integer not null default 0,
  duration_ms integer not null default 0,
  poster      text not null default '',
  unique (pin_id, position)
);
create index if not exists pin_slides_pin_idx on pin_slides (pin_id, position);
create table if not exists media (
  id         text primary key,
  user_id    text not null references users(id) on delete cascade,
  title      text not null default '',
  width      integer not null default 0,
  height     integer not null default 0,
  file       text not null,
  created_at real not null
);
create index if not exists media_user_idx on media (user_id, created_at desc);
create table if not exists follows (
  follower_id text not null references users(id) on delete cascade,
  followee_id text not null references users(id) on delete cascade,
  created_at  real not null,
  primary key (follower_id, followee_id)
);
create table if not exists comments (
  id         text primary key,
  pin_id     text not null,
  user_id    text not null references users(id) on delete cascade,
  parent_id  text,
  text       text not null,
  created_at real not null
);
create index if not exists comments_pin_idx on comments (pin_id, created_at asc);
create table if not exists comment_likes (
  user_id    text not null references users(id) on delete cascade,
  comment_id text not null,
  created_at real not null,
  primary key (user_id, comment_id)
);
create index if not exists follows_followee_idx on follows (followee_id);
create table if not exists notifications (
  id         text primary key,
  user_id    text not null references users(id) on delete cascade,
  actor_id   text not null references users(id) on delete cascade,
  type       text not null,
  pin_id     text,
  created_at real not null,
  read       integer not null default 0
);
create index if not exists notifications_user_idx on notifications (user_id, created_at desc);
create table if not exists chats (
  id              text primary key,
  created_at      real not null,
  last_message_at real
);
create table if not exists chat_members (
  chat_id      text not null references chats(id) on delete cascade,
  user_id      text not null references users(id) on delete cascade,
  last_read_at real not null default 0,
  primary key (chat_id, user_id)
);
create table if not exists messages (
  id         text primary key,
  chat_id    text not null references chats(id) on delete cascade,
  sender_id  text not null references users(id) on delete cascade,
  kind       text not null,
  text       text,
  pin_id     text,
  pin_data   text,
  created_at real not null
);
create index if not exists messages_chat_idx on messages (chat_id, created_at);
create index if not exists chat_members_user_idx on chat_members (user_id);
create table if not exists communities (
  id          text primary key,
  owner_id    text not null references users(id) on delete cascade,
  title       text not null,
  description text not null default '',
  category    text not null default '',
  is_hidden   integer not null default 0,
  created_at  real not null
);
create index if not exists communities_owner_idx on communities (owner_id, created_at desc);
create index if not exists communities_category_idx on communities (category, created_at desc);
create table if not exists group_members (
  group_id  text not null references communities(id) on delete cascade,
  user_id   text not null references users(id) on delete cascade,
  role      text not null default 'member',
  joined_at real not null,
  primary key (group_id, user_id)
);
create index if not exists group_members_user_idx on group_members (user_id);
create table if not exists group_pins (
  group_id text not null references communities(id) on delete cascade,
  pin_id   text not null,
  pin_data text not null,
  added_by text not null references users(id) on delete cascade,
  added_at real not null,
  primary key (group_id, pin_id)
);
create table if not exists events (
  id       integer primary key autoincrement,
  ts       real not null,
  day      text not null,
  name     text not null,
  visitor  text not null,
  user_id  text,
  board_id text,
  pin_id   text,
  category text,
  ref_host text,
  source   text
);
create index if not exists events_day_name_idx on events (day, name);
create index if not exists events_board_idx on events (board_id, day);
create table if not exists reports (
  id           text primary key,
  reporter_id  text references users(id) on delete cascade,
  target_type  text not null,
  target_id    text not null,
  reason       text not null,
  status       text not null default 'open',
  created_at   real not null,
  auto_review  integer not null default 0,
  detail       text
);
create index if not exists reports_status_idx on reports (status, created_at desc);
"""

# Колонки, появившиеся после первой версии базы. Порядок = порядок применения:
# старый файл .data обновляется шаг за шагом, а «колонка уже есть» — норма.
MIGRATIONS = (
    "alter table users add column avatar_url text",
    "alter table boards add column is_secret integer not null default 0",
    "alter table pins add column source_url text",
    "alter table media add column external_url text",
    "alter table events add column source text",
    "alter table comments add column parent_id text",
    "alter table pins add column is_hidden integer not null default 0",
    "alter table users add column is_blocked integer not null default 0",
    # номер поколения сессий: растёт при выходе и бане, старые токены перестают
    # совпадать с ним и больше не открывают ничего (deps.session_revoked)
    "alter table users add column session_version integer not null default 0",
    # авто-модерация пинов: жалоба от системы (reporter_id=NULL) помечается
    # флагом auto_review, пояснение вердикта уходит в detail
    "alter table reports add column auto_review integer not null default 0",
    "alter table reports add column detail text",
)

# Индексы по свежедобавленным колонкам: в SCHEMA их ставить нельзя — на старой
# базе таблица уже существует, «create table if not exists» её пропустит, и
# индекс по отсутствующей колонке уронит запуск до применения миграций.
POST_MIGRATIONS = (
    "create index if not exists comments_parent_idx on comments (parent_id)",
)


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    """Одно соединение на запрос: с коммитом по успеху, откатом по ошибке
    и — обязательно — закрытием. Вариант без finally коммитил, но соединение не
    закрывал, и файловые дескрипторы текли на каждый запрос.

    WAL + busy_timeout: читатель не ждёт писателя, а параллельная запись
    получает retry вместо «database is locked».
    """
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    conn.execute("pragma journal_mode = wal")
    conn.execute("pragma busy_timeout = 5000")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Создать каталог, таблицы и доснять недостающие колонки.
    Вызывается один раз при сборке приложения."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connection() as conn:
        conn.executescript(SCHEMA)
        for ddl in MIGRATIONS:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass  # колонка уже есть
        for ddl in POST_MIGRATIONS:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass  # индекс уже есть
