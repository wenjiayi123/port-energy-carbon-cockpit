import type { DashboardSnapshot } from '../types/dashboard';

export interface DashboardRequest {
  scenario_id?: string;
  green_preference: number;
  carbon_price_cny_per_ton: number;
}

export async function fetchDashboardSnapshot(request: DashboardRequest): Promise<DashboardSnapshot> {
  const search = new URLSearchParams({
    green_preference: String(request.green_preference),
    carbon_price_cny_per_ton: String(request.carbon_price_cny_per_ton),
  });
  const response = await fetch(`/api/dashboard/snapshot?${search.toString()}`);
  if (!response.ok) {
    throw new Error('Failed to fetch dashboard snapshot');
  }
  return response.json();
}

export async function recomputeDashboard(request: DashboardRequest): Promise<DashboardSnapshot> {
  const response = await fetch('/api/optimization/recompute', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      scenario_id: request.scenario_id ?? 'port_la_2025_public_benchmark',
      green_preference: request.green_preference,
      carbon_price_cny_per_ton: request.carbon_price_cny_per_ton,
    }),
  });
  if (!response.ok) {
    throw new Error('Failed to recompute dashboard');
  }
  return response.json();
}
