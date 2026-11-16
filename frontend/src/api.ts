// Клиент API. Сессия — HttpOnly cookie; CSRF-токен хранится только в памяти.
let csrf: string | null = null;

export function setCsrf(token: string | null) {
  csrf = token;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type Listener = () => void;
const unauthListeners: Listener[] = [];
export function onUnauthorized(fn: Listener) {
  unauthListeners.push(fn);
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
  const method = opts.method ?? (opts.body !== undefined || opts.form ? "POST" : "GET");
  const headers: Record<string, string> = {};
  if (method !== "GET" && csrf) headers["x-csrf-token"] = csrf;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["content-type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, { method, headers, body, credentials: "same-origin" });
  if (res.status === 401 && !path.startsWith("/api/auth/")) unauthListeners.forEach((f) => f());
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail = data && typeof data === "object" ? data.detail : data;
    throw new ApiError(res.status, typeof detail === "string" ? detail : `Ошибка ${res.status}`);
  }
  return data as T;
}

export interface Project {
  id: number;
  slug: string;
  name: string;
  kind: string;
  template: string;
  repo_full_name: string | null;
  default_branch: string;
  description: string;
  automation_enabled: boolean;
  auto_merge_enabled: boolean;
  auto_publish_releases: boolean;
  prod_deploy_allowed: boolean;
  required_checks: string[];
  release_workflow: string;
  release_artifact: string;
  archived: boolean;
  created_at: string;
}

export interface Task {
  id: string;
  title: string;
  stage: string;
  lane: string;
  goal: string;
  context: string;
  gdd_refs: string[];
  file_scope: string[];
  depends_on: string[];
  done_when: string[];
  branch: string;
  status: "planned" | "ready" | "in_progress" | "blocked" | "done";
  pr_number: number | null;
  ci_state: string;
  blocked_reason: string;
}

export interface Plan {
  project: string;
  stages: { id: string; title: string }[];
  tasks: Task[];
}

export const KIND_LABELS: Record<string, string> = {
  game: "Игра",
  android: "Android",
  web: "Сайт",
  server: "Сервер",
  other: "Другое",
};

export const STATUS_LABELS: Record<string, string> = {
  planned: "Запланирована",
  ready: "Готова",
  in_progress: "В работе",
  blocked: "Заблокирована",
  done: "Выполнена",
};

export const CI_LABELS: Record<string, string> = {
  success: "CI зелёный",
  failure: "CI упал",
  pending: "CI идёт",
  no_required_checks: "Нет обязательных проверок",
  "": "—",
};
