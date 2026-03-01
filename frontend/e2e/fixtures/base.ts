/**
 * Playwright 共享 fixtures：API mock helpers。
 *
 * 前端使用两种方式调用后端：
 *   1. fetch()   — SSE 流式端点 (POST /api/v1/jobs, POST /api/v1/jobs/:id/confirm)
 *   2. axios     — REST 端点 (GET /api/v1/jobs, GET /api/v1/jobs/:id, ...)
 *
 * 本 fixture 通过 page.route() 统一拦截两类请求。
 */

import { type Page, type Route } from '@playwright/test';
import type { PaginatedJobsResponse } from './mock-data-types';

/** 将 SSE 事件数组编码为 SSE 文本流 */
export function encodeSSE(events: Record<string, unknown>[]): string {
  return events.map((evt) => `data: ${JSON.stringify(evt)}\n\n`).join('');
}

/** 拦截 POST /api/v1/jobs 并返回 SSE 流 */
export async function mockJobCreateSSE(
  page: Page,
  events: Record<string, unknown>[],
) {
  await page.route('**/api/v1/jobs', async (route: Route) => {
    if (route.request().method() !== 'POST') {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: encodeSSE(events),
    });
  });
}

/** 拦截 POST /api/v1/jobs/:id/confirm 并返回 SSE 流 */
export async function mockJobConfirmSSE(
  page: Page,
  events: Record<string, unknown>[],
) {
  await page.route('**/api/v1/jobs/*/confirm', async (route: Route) => {
    if (route.request().method() !== 'POST') {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: encodeSSE(events),
    });
  });
}

/** 拦截 GET /api/v1/jobs (零件库列表) */
export async function mockJobList(
  page: Page,
  response: PaginatedJobsResponse,
) {
  await page.route('**/api/v1/jobs?*', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(response),
    });
  });
  // 无 query string 时也拦截
  await page.route('**/api/v1/jobs', async (route: Route) => {
    if (route.request().method() !== 'GET') {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(response),
    });
  });
}

/** 拦截 GET /api/v1/jobs/:id (零件详情) */
export async function mockJobDetail(
  page: Page,
  jobId: string,
  response: Record<string, unknown>,
) {
  await page.route(`**/api/v1/jobs/${jobId}`, async (route: Route) => {
    if (route.request().method() !== 'GET') {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(response),
    });
  });
}

/** 拦截 GET /api/v1/jobs/:id/events (SSE 订阅) 返回空流 */
export async function mockJobEventsEmpty(page: Page) {
  await page.route('**/api/v1/jobs/*/events', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: '',
    });
  });
}

/** 拦截常见的非关键 API（pipeline 等），防止 console 报错 */
export async function mockCommonApis(page: Page) {
  await page.route('**/api/v1/pipeline/**', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({}),
    });
  });
  await page.route('**/api/v1/health', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'ok', version: '3.0.0' }),
    });
  });
  await page.route('**/api/v1/templates**', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    });
  });
}

// Re-export types for convenience
export type { PaginatedJobsResponse };
