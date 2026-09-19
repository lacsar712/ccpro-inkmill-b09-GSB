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

/** 带鉴权头下载文件（导出接口需要 JWT，不能直接用 <a href>）。 */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const headers: Record<string, string> = {};
  const t = get(token);
  if (t) headers.Authorization = `Bearer ${t}`;

  const res = await fetch(`/api${path}`, { headers });

  if (res.status === 401) {
    clearSession();
    throw new Error('未登录或登录已过期');
  }

  if (!res.ok) {
    let msg = `请求失败 (${res.status})`;
    try {
      const body = await res.json();
      if (body?.message) msg = body.message;
    } catch {
      // 非 JSON 错误体时沿用默认文案
    }
    throw new Error(msg);
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
