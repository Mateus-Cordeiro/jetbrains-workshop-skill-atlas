import { test as base, expect } from '@playwright/test';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';

class AtlasServer {
  private child = spawn('uv', ['run', '--locked', 'python', '-m', 'tests.browser.visual.server'], {
    stdio: ['pipe', 'pipe', 'pipe'],
    env: { ...process.env, GH_TOKEN: '', GITHUB_TOKEN: '' },
  });
  private lines = createInterface({ input: this.child.stdout })[Symbol.asyncIterator]();
  private logs = '';
  private exited = new Promise<number | null>((resolve, reject) => {
    this.child.once('exit', resolve);
    this.child.once('error', reject);
  });
  baseURL = '';

  constructor() {
    this.child.stderr.on('data', data => { this.logs += String(data); });
  }

  private async response(): Promise<Record<string, unknown>> {
    let timer: NodeJS.Timeout | undefined;
    try {
      return await Promise.race([
        this.lines.next().then(line => {
          if (line.done) throw new Error(`Fixture server closed stdout: ${this.logs}`);
          return JSON.parse(line.value) as Record<string, unknown>;
        }),
        this.exited.then(code => { throw new Error(`Fixture server exited (${code}): ${this.logs}`); }),
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new Error(`Fixture server timed out: ${this.logs}`)), 15_000);
        }),
      ]);
    } finally {
      clearTimeout(timer);
    }
  }

  async start() {
    const ready = await this.response();
    expect(ready.baseURL).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/);
    this.baseURL = String(ready.baseURL);
  }

  async scan(status: number, blocked: boolean) {
    this.child.stdin.write(JSON.stringify({ command: 'scan', status, blocked }) + '\n');
    expect(await this.response()).toEqual({ ok: true });
  }

  async requests() {
    this.child.stdin.write(JSON.stringify({ command: 'requests' }) + '\n');
    const response = await this.response();
    return response.paths as string[];
  }

  async stop() {
    if (this.child.exitCode !== null) {
      expect(this.child.exitCode, this.logs).toBe(0);
      return;
    }
    this.child.stdin.end(JSON.stringify({ command: 'stop' }) + '\n');
    const timer = setTimeout(() => this.child.kill('SIGKILL'), 12_000);
    try {
      expect(await this.exited, this.logs).toBe(0);
    } finally {
      clearTimeout(timer);
    }
  }
}

export const test = base.extend<{
  atlas: AtlasServer;
  checkpoint: (name: string) => Promise<void>;
}>({
  atlas: async ({}, use) => {
    const server = new AtlasServer();
    try {
      await server.start();
      await use(server);
    } finally {
      await server.stop();
    }
  },
  baseURL: async ({ atlas }, use) => { await use(atlas.baseURL); },
  page: async ({ page, baseURL }, use) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.context().route('**/*', async route => {
      if (new URL(route.request().url()).origin === baseURL) await route.continue();
      else {
        errors.push(`External request: ${route.request().url()}`);
        await route.abort();
      }
    });
    await page.context().routeWebSocket('**/*', socket => {
      errors.push(`Unexpected WebSocket: ${socket.url()}`);
      socket.close();
    });
    await use(page);
    expect(errors, 'No page errors or external requests').toEqual([]);
    if (process.env.ATLAS_DEMO === '1') {
      // Keep the final interaction visible before the context finalizes the video.
      await new Promise(resolve => setTimeout(resolve, 1500));
    }
  },
  checkpoint: async ({ page }, use, testInfo) => {
    await use(async name => {
      await test.step(`Visual checkpoint: ${name}`, async () => {
        await page.evaluate(() => document.fonts.ready);
        // Remove incidental pointer hover; retain keyboard focus as part of the image.
        await page.mouse.move(1350, 990);
        await expect(page).toHaveScreenshot(`${name}.png`);
        const path = testInfo.outputPath(`${name}.png`);
        await page.screenshot({ path, animations: 'disabled', caret: 'hide', scale: 'css' });
        await testInfo.attach(name, { path, contentType: 'image/png' });
        // Recording-only pacing, never used to synchronize application state.
        if (process.env.ATLAS_DEMO === '1') {
          await new Promise(resolve => setTimeout(resolve, 2000));
        }
      });
    });
  },
});

export { expect } from '@playwright/test';
