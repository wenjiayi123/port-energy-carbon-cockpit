import type { DashboardSnapshot } from '../types/dashboard';

export interface DashboardRequest {
  scenario_id?: string;
  green_preference: number;
  carbon_price_cny_per_ton: number;
}

export interface FetchJsonOptions extends RequestInit {
  timeoutMs?: number;
}

function responseError(data: unknown, fallback: string): string {
  if (!data || typeof data !== 'object') return fallback;
  const detail = (data as { detail?: unknown; error?: unknown }).detail
    ?? (data as { error?: unknown }).error;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      if (item && typeof item === 'object' && 'msg' in item) {
        return String(item.msg);
      }
      return String(item);
    }).join('；') || fallback;
  }
  return detail ? JSON.stringify(detail) : fallback;
}

export async function fetchJson(path: string, options: FetchJsonOptions = {}): Promise<any> {
  const { timeoutMs = 60_000, ...requestOptions } = options;
  const controller = new AbortController();
  const abort = () => controller.abort(requestOptions.signal?.reason);
  if (requestOptions.signal?.aborted) abort();
  else requestOptions.signal?.addEventListener('abort', abort, { once: true });
  let timedOut = false;
  const timeout = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  try {
    const headers = new Headers(requestOptions.headers);
    if (requestOptions.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    const response = await fetch(path, { ...requestOptions, headers, signal: controller.signal });
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new Error(responseError(data, `HTTP ${response.status} ${response.statusText}`));
    if (data === null) throw new Error('接口未返回有效 JSON 数据，请检查服务连接。');
    return data;
  } catch (error) {
    if (timedOut) throw new Error(`接口请求超过 ${(timeoutMs / 1000).toFixed(1)} 秒，已自动释放，可重试或使用演示保底。`);
    throw error;
  } finally {
    window.clearTimeout(timeout);
    requestOptions.signal?.removeEventListener('abort', abort);
  }
}

export async function fetchDashboardSnapshot(request: DashboardRequest): Promise<DashboardSnapshot> {
  const search = new URLSearchParams({
    green_preference: String(request.green_preference),
    carbon_price_cny_per_ton: String(request.carbon_price_cny_per_ton),
  });
  return fetchJson(`/api/dashboard/snapshot?${search.toString()}`);
}

export async function recomputeDashboard(request: DashboardRequest, signal?: AbortSignal): Promise<DashboardSnapshot> {
  return fetchJson('/api/optimization/recompute', {
    method: 'POST',
    signal,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      scenario_id: request.scenario_id ?? 'port_la_2025_public_benchmark',
      green_preference: request.green_preference,
      carbon_price_cny_per_ton: request.carbon_price_cny_per_ton,
    }),
  });
}
