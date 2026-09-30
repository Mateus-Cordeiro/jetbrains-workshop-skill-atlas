import { defineConfig } from '@playwright/test';
import { resolve } from 'node:path';

// Baselines have one canonical OS, architecture, browser, and font environment.
if (process.env.ATLAS_VISUAL_ENV !== 'playwright-1.63.0-noble-amd64'
    || process.platform !== 'linux' || process.arch !== 'x64') {
  throw new Error('Use npm run test:visual:container to run visual tests in the pinned Linux image.');
}
if (process.env.CI && process.argv.some(arg => arg.startsWith('--update-snapshots') || arg === '-u')) {
  throw new Error('Baseline updates must be generated locally and reviewed in Git, never accepted by CI.');
}

const demo = process.env.ATLAS_DEMO === '1';
const output = resolve(__dirname, '../../../test-results/visual');

export default defineConfig({
  testDir: __dirname,
  testMatch: '*.spec.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  timeout: 60_000,
  expect: {
    timeout: 10_000,
    toHaveScreenshot: {
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
      // No changed pixels are accepted; threshold only handles tiny color noise.
      maxDiffPixels: 0,
      threshold: 0.1,
    },
  },
  updateSnapshots: 'none',
  snapshotPathTemplate: '{testDir}/snapshots/{testFilePath}/{arg}{ext}',
  outputDir: resolve(output, 'results'),
  reporter: [
    ['list'],
    ['html', { outputFolder: resolve(output, 'report'), open: 'never' }],
    ['junit', { outputFile: resolve(output, 'junit.xml') }],
  ],
  use: {
    browserName: 'chromium',
    viewport: { width: 1360, height: 1000 },
    deviceScaleFactor: 1,
    locale: 'en-US',
    timezoneId: 'UTC',
    colorScheme: 'light',
    reducedMotion: 'reduce',
    serviceWorkers: 'block',
    headless: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: { mode: demo ? 'on' : 'retain-on-failure', size: { width: 1360, height: 1000 } },
    launchOptions: { slowMo: demo ? 200 : 0 },
  },
});
