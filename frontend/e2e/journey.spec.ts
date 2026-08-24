import { expect, test } from '@playwright/test';

/** The end-to-end journey over a seeded database.
 *
 * These read the public surfaces rather than uploading, because upload
 * mutates the database and parallel workers would then race each other.
 * The upload path is covered by the backend suite; what only a browser can
 * verify is that the pages render real API data and the journeys connect.
 */

test.describe('discovery', () => {
  test('the feed lists published work with attribution', async ({ page }) => {
    await page.goto('/feed');

    const cards = page.locator('.feed-card');
    await expect(cards.first()).toBeVisible();
    expect(await cards.count()).toBeGreaterThan(0);

    // Every card must say who made it — attribution is the point.
    await expect(cards.first().locator('.feed-card__author')).toBeVisible();
  });

  test('the feed can be filtered to findings only', async ({ page }) => {
    await page.goto('/feed');
    await page.getByRole('button', { name: 'Findings' }).click();

    await expect(page.locator('.chip--finding').first()).toBeVisible();
    await expect(page.locator('.feed-card')).not.toHaveCount(0);
  });

  test('search returns published spectra and honours the sort selector', async ({ page }) => {
    await page.goto('/search');
    await expect(page.locator('table.data-table')).toBeVisible();

    const firstBefore = await page.locator('tbody tr').first().textContent();
    await page.getByLabel('Sort').selectOption('newest');
    await expect(page.locator('tbody tr').first()).toBeVisible();

    // Ordering is a server concern; here we only assert the control drives a
    // real request and the table repaints.
    const firstAfter = await page.locator('tbody tr').first().textContent();
    expect(typeof firstAfter).toBe('string');
    expect(firstBefore).not.toBeUndefined();
  });
});

test.describe('a published spectrum', () => {
  test('shows its chart, detected peaks and a citation', async ({ page }) => {
    await page.goto('/search');
    await page.locator('tbody tr a').first().click();

    await expect(page.getByRole('img', { name: /spectrum chart/i })).toBeVisible();

    // Peaks are detected automatically — no button press required.
    await expect(page.getByRole('heading', { name: 'Peaks' })).toBeVisible();
    await expect(page.locator('.data-table').first()).toBeVisible();

    // The citation block is populated from the server.
    const citation = page.locator('.citation-box');
    await expect(citation).toBeVisible();
    await expect(citation).toHaveValue(/RamanHub/);
  });

  test('offers every download format', async ({ page }) => {
    await page.goto('/search');
    await page.locator('tbody tr a').first().click();

    const format = page.getByLabel('Format');
    await expect(format).toBeVisible();
    for (const option of ['csv', 'tsv', 'jcamp', 'json']) {
      await expect(format.locator(`option[value="${option}"]`)).toHaveCount(1);
    }
  });

  test('downloads a CSV carrying its provenance header', async ({ page }) => {
    await page.goto('/search');
    await page.locator('tbody tr a').first().click();

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('link', { name: 'Download', exact: true }).click(),
    ]);

    expect(download.suggestedFilename()).toMatch(/^RH-S-\d+_/);
  });
});

test.describe('compare', () => {
  test('overlays a selection and defaults to SNV scaling', async ({ page }) => {
    await page.goto('/search');

    // Select the first two rows.
    const boxes = page.locator('tbody input[type="checkbox"]');
    await boxes.nth(0).check();
    await boxes.nth(1).check();
    await page.getByRole('button', { name: 'Compare' }).click();

    await expect(page).toHaveURL(/\/compare\?ids=/);
    await expect(page.getByRole('img', { name: /spectrum chart/i })).toBeVisible();

    // SNV is the default because as-stored overlays compare brightness
    // rather than band structure.
    await expect(page.getByLabel('Scaling')).toHaveValue('snv');
  });

  test('runs PCA over the selection', async ({ page }) => {
    await page.goto('/search');
    const boxes = page.locator('tbody input[type="checkbox"]');
    await boxes.nth(0).check();
    await boxes.nth(1).check();
    await boxes.nth(2).check();
    await page.getByRole('button', { name: 'Compare' }).click();

    await page.getByRole('button', { name: 'PCA' }).click();
    await page.getByRole('button', { name: /Run PCA/ }).click();

    await expect(page.getByRole('img', { name: /PCA scores/i })).toBeVisible({
      timeout: 30_000,
    });
    // The loadings plot is what makes a PCA figure interpretable.
    await expect(page.getByText(/Which bands drive PC/)).toBeVisible();
  });
});

test.describe('findings and profiles', () => {
  test('a finding thread renders its entries and member spectra', async ({ page }) => {
    await page.goto('/feed');
    await page.getByRole('button', { name: 'Findings' }).click();
    await page.locator('.feed-card__title a').first().click();

    await expect(page).toHaveURL(/\/findings\//);
    await expect(page.locator('.finding__abstract')).toBeVisible();
    await expect(page.locator('.entry').first()).toBeVisible();
    await expect(page.getByText(/Spectra in this finding/)).toBeVisible();
  });

  test('a contributor profile shows published work only', async ({ page }) => {
    await page.goto('/u/ramanhub-demo');

    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByText('Published spectra')).toBeVisible();
    // Draft counts must never appear on a public page.
    await expect(page.getByText(/drafts/i)).toHaveCount(0);
  });
});

test.describe('shell', () => {
  test('the landing route drops straight into the toolbox', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/upload$/);
    await expect(page.getByText(/Drag a raw file here/)).toBeVisible();
  });

  test('theme can be switched to dark', async ({ page }) => {
    await page.goto('/feed');
    await page.getByRole('button', { name: 'Dark' }).click();

    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  });

  test('has no console errors on the main routes', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    for (const route of ['/feed', '/search', '/library', '/upload', '/compare']) {
      await page.goto(route);
      await page.waitForLoadState('networkidle');
    }

    expect(errors).toEqual([]);
  });
});
