import { get } from 'svelte/store';
import { token, clearSession } from './auth';

export async function api<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  };
  const t = get(token);
  if (t) headers.Authorization = `Bearer ${t}`;

  const res = await fetch(`/api${path}`, {
    ...options,
    headers,
  });

  if (res.status === 401) {
    clearSession();
    throw new Error('未登录或登录已过期');
  }

  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!res.ok) {
    const body = data as { message?: string; error?: string } | null;
    const msg =
      body?.message ||
      body?.error ||
      `请求失败 (${res.status})`;
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }

  return data as T;
}

/**
 * 下载二进制(如服务端生成的 CSV)。携带同样的 JWT。
 * 服务端的错误响应是 JSON，这里读取 blob 文本后按 JSON 解出 message。
 */
export async function apiBlob(path: string): Promise<Blob> {
  const headers: Record<string, string> = {};
  const t = get(token);
  if (t) headers.Authorization = `Bearer ${t}`;

  const res = await fetch(`/api${path}`, { headers });

  if (res.status === 401) {
    clearSession();
    throw new Error('未登录或登录已过期');
  }

  if (!res.ok) {
    const text = await res.text();
    let msg = `请求失败 (${res.status})`;
    try {
      const body = JSON.parse(text) as { message?: string; error?: string };
      msg = body.message || body.error || msg;
    } catch {
      /* 非 JSON 错误体，沿用默认文案 */
    }
    throw new Error(msg);
  }

  return res.blob();
}
