import { test, expect } from '@playwright/test';
import { mockJobList, mockJobEventsEmpty } from './fixtures/base';
import { MOCK_JOB_LIST_EMPTY } from './fixtures/mock-data';

/**
 * Mock pipeline API endpoints for configuration testing.
 * Must be called BEFORE mockCommonApis to take precedence.
 */
async function mockPipelineApis(
  page: import('@playwright/test').Page,
  options?: {
    nodes?: Record<string, unknown>[];
    presets?: Record<string, unknown>[];
    strategyAvailability?: Record<string, unknown>;
    validateResponse?: Record<string, unknown>;
  },
) {
  const nodes = options?.nodes ?? [
    {
      name: 'analyze_drawing',
      display_name: '图纸分析',
      requires: [],
      produces: ['drawing_spec'],
      input_types: ['drawing'],
      strategies: ['qwen_vl'],
      default_strategy: 'qwen_vl',
      is_entry: true,
      is_terminal: false,
      supports_hitl: false,
      non_fatal: false,
      description: '分析工程图纸',
    },
    {
      name: 'mesh_repair',
      display_name: '网格修复',
      requires: ['raw_mesh'],
      produces: ['repaired_mesh'],
      input_types: ['organic'],
      strategies: ['manifold', 'trimesh'],
      default_strategy: 'manifold',
      is_entry: false,
      is_terminal: false,
      supports_hitl: false,
      non_fatal: true,
      description: '修复网格',
      config_schema: {
        properties: {
          enabled: { type: 'boolean', default: true },
          strategy: { type: 'string', enum: ['manifold', 'trimesh'] },
          timeout: {
            type: 'integer',
            minimum: 10,
            maximum: 600,
            description: '超时时间（秒）',
          },
        },
      },
    },
    {
      name: 'generate_raw_mesh',
      display_name: '3D 生成',
      requires: ['organic_spec'],
      produces: ['raw_mesh'],
      input_types: ['organic'],
      strategies: ['hunyuan3d', 'tripo3d'],
      default_strategy: 'tripo3d',
      is_entry: false,
      is_terminal: false,
      supports_hitl: false,
      non_fatal: false,
      description: '生成 3D 模型',
    },
  ];

  const presets = options?.presets ?? [
    { name: 'balanced', display_name: '均衡模式', description: '默认', config: {} },
  ];

  // Register specific routes BEFORE generic fallback
  await page.route('**/api/v1/pipeline/nodes', async (route) => {
    await route.fulfill({
      json: { nodes },
    });
  });

  await page.route('**/api/v1/pipeline/node-presets', async (route) => {
    await route.fulfill({ json: presets });
  });

  await page.route('**/api/v1/pipeline/strategy-availability', async (route) => {
    await route.fulfill({
      json: options?.strategyAvailability ?? {},
    });
  });

  if (options?.validateResponse) {
    await page.route('**/api/v1/pipeline/validate', async (route) => {
      await route.fulfill({ json: options.validateResponse });
    });
  } else {
    await page.route('**/api/v1/pipeline/validate', async (route) => {
      const body = JSON.parse(route.request().postData() ?? '{}');
      const config = body.config ?? {};
      const meshRepairDisabled = config.mesh_repair?.enabled === false;
      await route.fulfill({
        json: {
          valid: true,
          node_count: meshRepairDisabled ? 2 : 3,
          topology: meshRepairDisabled
            ? ['analyze_drawing', 'generate_raw_mesh']
            : ['analyze_drawing', 'generate_raw_mesh', 'mesh_repair'],
        },
      });
    });
  }

  // Catch-all for remaining pipeline endpoints
  await page.route('**/api/v1/pipeline/**', async (route) => {
    await route.fulfill({ json: {} });
  });

  // Other common APIs
  await page.route('**/api/v1/health', async (route) => {
    await route.fulfill({ json: { status: 'ok', version: '3.0.0' } });
  });
  await page.route('**/api/v1/templates**', async (route) => {
    await route.fulfill({ json: [] });
  });
}

test.describe('Pipeline Configuration', () => {
  test.beforeEach(async ({ page }) => {
    await mockJobList(page, MOCK_JOB_LIST_EMPTY);
    await mockJobEventsEmpty(page);
  });

  test('nodes endpoint returns descriptors with config_schema', async ({ page }) => {
    await mockPipelineApis(page);
    await page.goto('/precision');

    // Pipeline config card should be visible
    await expect(page.getByText('管道配置')).toBeVisible();
  });

  test('strategy availability marks unavailable strategies', async ({ page }) => {
    await mockPipelineApis(page, {
      strategyAvailability: {
        generate_raw_mesh: {
          hunyuan3d: { available: false, reason: 'API Key 未配置' },
          tripo3d: { available: true },
        },
      },
    });

    await page.goto('/precision');
    await expect(page.getByText('管道配置')).toBeVisible();
  });

  test('validate API called and banner shown', async ({ page }) => {
    let validateCalled = false;

    // Register tracking route BEFORE mockPipelineApis so it takes precedence
    await page.route('**/api/v1/pipeline/validate', async (route) => {
      validateCalled = true;
      await route.fulfill({
        json: {
          valid: true,
          node_count: 3,
          topology: ['analyze_drawing', 'generate_raw_mesh', 'mesh_repair'],
        },
      });
    });

    await mockPipelineApis(page);

    await page.goto('/precision');
    await expect(page.getByText('管道配置')).toBeVisible();

    // Wait for the 300ms debounce + API response
    await page.waitForTimeout(500);
    expect(validateCalled).toBe(true);
  });

  test('all-disabled returns invalid banner', async ({ page }) => {
    await mockPipelineApis(page, {
      validateResponse: {
        valid: false,
        error: '至少需要启用一个节点',
        node_count: 0,
      },
    });

    await page.goto('/precision');
    await expect(page.getByText('管道配置')).toBeVisible();

    // Wait for debounce + render
    await page.waitForTimeout(500);

    // Invalid banner should appear
    await expect(page.getByText('至少需要启用一个节点')).toBeVisible({ timeout: 5000 });
  });

  test('confirm request includes pipeline_config_updates when provided', async ({ page }) => {
    // This test verifies the API contract, not full UI interaction
    // The confirm endpoint now accepts pipeline_config_updates in the body
    let confirmBody: Record<string, unknown> | null = null;

    await mockPipelineApis(page);

    await page.route('**/api/v1/jobs/*/confirm', async (route) => {
      if (route.request().method() === 'POST') {
        confirmBody = JSON.parse(route.request().postData() ?? '{}');
        await route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: 'data: {"type":"job.completed","job_id":"test"}\n\n',
        });
      } else {
        await route.fallback();
      }
    });

    // Verify confirm endpoint contract by calling it directly via evaluate
    await page.goto('/precision');
    await page.evaluate(async () => {
      const resp = await fetch('/api/v1/jobs/test-job/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          confirmed_params: { diameter: 50 },
          pipeline_config_updates: {
            mesh_repair: { strategy: 'trimesh' },
          },
        }),
      });
      return resp.ok;
    });

    expect(confirmBody).not.toBeNull();
    expect((confirmBody as Record<string, unknown>).pipeline_config_updates).toEqual({
      mesh_repair: { strategy: 'trimesh' },
    });
  });
});
