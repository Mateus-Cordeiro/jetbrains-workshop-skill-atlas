import { test, expect } from './fixtures';

const repository = 'https://github.com/acme/skills';

test('catalog filtering', async ({ page, atlas, checkpoint }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Repositories 2' })).toBeVisible();
  const expand = page.getByRole('button', { name: 'Toggle skills in Acme/skills' });
  await expand.focus();
  await page.keyboard.press('Enter');
  await expect(expand).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('.catalog-skill:visible')).toHaveCount(2);
  await checkpoint('catalog-expanded');

  const search = page.getByRole('searchbox', { name: 'Filter skills across repositories' });
  await search.fill('CODE maintain');
  await expect(page.getByRole('status')).toHaveText('2 matching skills across 2 repositories');
  await expect(page.locator('.catalog-skill:visible')).toHaveCount(2);
  await checkpoint('catalog-filtered');

  await search.fill('missing');
  await expect(page.getByText('No skills match “missing”.')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Repositories 0' })).toBeVisible();
  await checkpoint('catalog-no-matches');

  await search.press('Escape');
  await expect(search).toHaveValue('');
  await expect(search).toBeFocused();
  await expect(expand).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('.catalog-skill:visible')).toHaveCount(2);
  await checkpoint('catalog-cleared');
  expect(await atlas.requests()).toEqual([]);
});

test('descriptions and document views', async ({ page, atlas, checkpoint }) => {
  await page.goto(`/repository?${new URLSearchParams({ repository_url: repository })}`);
  const card = page.locator('.skill-item').first();
  const more = card.getByRole('button', { name: 'Show more description for code-review' });
  await expect(more).toHaveAttribute('aria-expanded', 'false');
  await expect(page.getByText('Select a skill to view its SKILL.md')).toBeVisible();
  await checkpoint('description-collapsed');

  await more.focus();
  await page.keyboard.press('Enter');
  await expect(card.getByRole('button', { name: 'Show less description for code-review' }))
    .toHaveAttribute('aria-expanded', 'true');
  expect(await atlas.requests()).toEqual([]);
  await checkpoint('description-expanded');

  await card.getByRole('link', { name: 'code-review', exact: true }).click();
  await expect(page.locator('.markdown h1')).toHaveText('Review changes');
  await expect(card.locator('.skill-link')).toHaveAttribute('aria-current', 'true');
  await expect(page.getByRole('link', { name: 'View on GitHub', exact: false }))
    .toHaveAttribute('href', `${repository}/blob/${'a'.repeat(40)}/review/SKILL.md`);
  await checkpoint('document-preview');

  await page.getByRole('button', { name: 'Source', exact: true }).click();
  await expect(page.locator('#document-preview')).toBeHidden();
  await expect(page.locator('#document-source')).toContainText('name: code-review');
  await checkpoint('document-source');
  await page.getByRole('button', { name: 'Preview', exact: true }).click();
  await expect(page.locator('.markdown h1')).toBeVisible();
  expect(await atlas.requests()).toEqual(['/repos/Acme/skills/contents/review/SKILL.md']);
});

test('scan progress failure and retry', async ({ page, atlas, checkpoint }) => {
  // Freeze application time between explicit polling ticks, including toast expiry.
  await page.clock.install({ time: new Date('2026-01-01T12:00:00Z') });
  await page.clock.pauseAt(new Date('2026-01-01T12:00:01Z'));
  await page.goto('/');
  await page.getByRole('button', { name: 'Scan GitHub…' }).click();
  await atlas.scan(404, true);
  const input = page.getByRole('textbox', { name: 'GitHub URL' });
  await input.fill('https://github.com/acme');
  await expect(page.getByRole('button', { name: 'Scan organization', exact: true })).toBeVisible();
  await checkpoint('scan-organization-dialog');
  await input.fill(repository);
  await checkpoint('scan-repository-dialog');
  await page.getByRole('button', { name: 'Scan repository', exact: true }).click();
  const tick = async () => { await page.clock.runFor(1000); };
  const settle = async () => {
    // HTMX initializes replacement controls after its settling timer. With a
    // paused clock, visibility alone does not mean those controls are ready.
    await expect.poll(async () => {
      await page.clock.runFor(50);
      return page.locator('.htmx-settling, .htmx-swapping, .htmx-request').count();
    }).toBe(0);
  };
  await expect.poll(async () => {
    await tick();
    return page.locator('.job[data-state="running"]').count();
  }).toBe(1);
  await settle();
  await page.getByRole('button', { name: 'Scan GitHub…' }).click();
  await input.fill('https://github.com/acme/new');
  await page.getByRole('button', { name: 'Scan repository', exact: true }).click();
  await expect(page.locator('.job[data-state="queued"]')).toBeVisible();
  await settle();
  await checkpoint('scan-running-and-queued');

  await atlas.scan(404, false);
  await expect.poll(async () => {
    await tick();
    return page.locator('.job[data-state="failed"]').count();
  }).toBe(2);
  await settle();
  await expect(page.locator('.repository-row')).toHaveCount(2);
  await checkpoint('scan-failed');

  await page.getByRole('button', { name: 'Dismiss scan result for acme/new', exact: true }).click();
  await atlas.scan(200, true);
  await page.getByRole('button', { name: 'Retry scan', exact: true }).click();
  await expect.poll(async () => {
    await tick();
    return page.locator('.job[data-state="running"]').count();
  }).toBe(1);
  await settle();
  await checkpoint('scan-retrying');
  await page.getByRole('button', { name: 'Dismiss scan result for acme/skills', exact: true }).click();
  await atlas.scan(200, false);
  await expect.poll(async () => {
    await tick();
    return page.locator('.job[data-state="succeeded"]').count();
  }).toBe(1);
  await settle();
  await expect(page.locator('.job-status')).toHaveText('2 skills found');
  await expect(page.locator('.repository-row')).toHaveCount(2);
  await checkpoint('scan-succeeded');
  await page.getByRole('link', { name: 'View results', exact: false }).click();
  await expect(page.locator('.skill-link')).toHaveCount(2);
});


test('explore skill connections', async ({ page, atlas, checkpoint }) => {
  await atlas.graph();
  await page.goto('/explore');
  await page.getByRole('button', { name: 'Generate groups', exact: true }).click();
  const ready = async () => {
    await expect(page.locator('#skill-graph')).toHaveAttribute('data-ready', 'true');
  };
  await expect(page.getByRole('button', { name: 'Ship with confidence, 4 skills' })).toBeVisible();
  await ready();
  await checkpoint('explore-capabilities');
  await page.getByRole('button', { name: 'Ship with confidence, 4 skills' }).click();
  await ready();
  await page.getByRole('button', { name: 'Secure systems, 2 skills' }).click();
  await ready();
  await expect(page.locator('#graph-count')).toHaveText('4 groups · 5 visible skills');
  await checkpoint('explore-overlap');
  await page.getByRole('link', { name: 'code-review Acme/skills', exact: true }).click();
  await expect(page.locator('.markdown h1')).toHaveText('Review changes');
  await page.getByRole('button', { name: 'Source', exact: true }).click();
  await expect(page.locator('#document-source')).toContainText('name: code-review');
  await page.getByRole('link', { name: 'Back to Explore', exact: false }).click();
  await ready();
  await expect(page.getByRole('button', { name: 'Secure systems, 2 skills' })).toHaveAttribute('aria-expanded', 'true');
  await page.getByRole('button', { name: 'Topics', exact: true }).click();
  await ready();
  await page.getByRole('button', { name: 'Reliability, 3 skills' }).click();
  await ready();
  await checkpoint('explore-topics');
});
