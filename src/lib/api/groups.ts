// Группы по тематикам (backend/groups.py): каталог, вступление, роли,
// публикация пинов. Пины живут в группе снапшотами — тот же Pin-каркас,
// что у досок.

import type { Pin } from "@/lib/pin";
import { isStatus, requestJson } from "@/lib/api/http";

export type GroupRole = "owner" | "poster" | "member";

export type Group = {
  id: string;
  title: string;
  description: string;
  category: string;
  createdAt: number;
  membersCount: number;
  pinsCount: number;
  owner: { id: string; name: string };
};

export type MyGroup = Group & { myRole: GroupRole };

/** Публичная карточка группы: карточка + лента снапшотов + ваша роль. */
export type PublicGroup = Group & {
  pins: Pin[];
  myRole: GroupRole | null;
};

export type GroupMember = {
  id: string;
  name: string;
  avatarUrl: string | null;
  role: GroupRole;
  joinedAt: number;
  canManage: boolean;
};

export async function apiGroups(
  params: { category?: string; q?: string } = {},
  signal?: AbortSignal,
): Promise<Group[]> {
  const qs = new URLSearchParams();
  if (params.category) qs.set("category", params.category);
  if (params.q) qs.set("q", params.q);
  const suffix = qs.toString() ? `?${qs}` : "";
  const data = await requestJson<{ groups: Group[] }>(`/api/groups${suffix}`, { signal });
  return data.groups;
}

export async function apiMyGroups(signal?: AbortSignal): Promise<MyGroup[]> {
  const data = await requestJson<{ groups: MyGroup[] }>("/api/groups/mine", { signal });
  return data.groups;
}

/** Группы, где вошедший может публиковать (меню «добавить в группу»). */
export async function apiPostableGroups(signal?: AbortSignal): Promise<{ id: string; title: string }[]> {
  const data = await requestJson<{ groups: { id: string; title: string }[] }>(
    "/api/groups/postable",
    { signal },
  );
  return data.groups;
}

export async function apiCreateGroup(
  title: string,
  fields: { description?: string; category?: string } = {},
): Promise<Group> {
  const data = await requestJson<{ group: Group }>("/api/groups", {
    method: "POST",
    body: JSON.stringify({ title, ...fields }),
  });
  return data.group;
}

export async function apiGroup(groupId: string, signal?: AbortSignal): Promise<PublicGroup | null> {
  try {
    const data = await requestJson<{ group: PublicGroup }>(`/api/groups/${groupId}`, { signal });
    return data.group;
  } catch (err) {
    if (isStatus(err, 404)) return null;
    throw err;
  }
}

export async function apiUpdateGroup(
  groupId: string,
  fields: { title: string; description: string; category: string },
): Promise<Group> {
  const data = await requestJson<{ group: Group }>(`/api/groups/${groupId}`, {
    method: "PATCH",
    body: JSON.stringify(fields),
  });
  return data.group;
}

export async function apiDeleteGroup(groupId: string): Promise<void> {
  await requestJson(`/api/groups/${groupId}`, { method: "DELETE" });
}

export async function apiJoinGroup(groupId: string): Promise<void> {
  await requestJson(`/api/groups/${groupId}/join`, { method: "POST", body: "{}" });
}

export async function apiLeaveGroup(groupId: string): Promise<void> {
  await requestJson(`/api/groups/${groupId}/leave`, { method: "POST", body: "{}" });
}

export async function apiGroupMembers(
  groupId: string,
  signal?: AbortSignal,
): Promise<GroupMember[]> {
  const data = await requestJson<{ members: GroupMember[] }>(`/api/groups/${groupId}/members`, {
    signal,
  });
  return data.members;
}

export async function apiSetMemberRole(
  groupId: string,
  userId: string,
  role: "poster" | "member",
): Promise<void> {
  await requestJson(`/api/groups/${groupId}/members/${userId}/role`, {
    method: "POST",
    body: JSON.stringify({ role }),
  });
}

export async function apiAddGroupPin(groupId: string, pin: Pin): Promise<void> {
  // Карточку отправляем целиком, как доска (apiSavePin): в урезанном виде
  // без sourceUrl снапшот приезжает без картинки, и лента группы рисует
  // пустые плитки.
  await requestJson(`/api/groups/${encodeURIComponent(groupId)}/pins/${encodeURIComponent(pin.id)}`, {
    method: "PUT",
    body: JSON.stringify(pin),
  });
}

export async function apiRemoveGroupPin(groupId: string, pinId: string): Promise<void> {
  await requestJson(`/api/groups/${encodeURIComponent(groupId)}/pins/${encodeURIComponent(pinId)}`, { method: "DELETE" });
}
