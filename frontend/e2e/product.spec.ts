import { expect, test } from '@playwright/test';

test('Command Center turns a user goal into a visible workflow plan', async ({ page }) => {
  await page.goto('/product');
  await expect(page.getByRole('heading', { name: 'Turn a goal into a workflow.' })).toBeVisible();
  await page.getByLabel('What are you trying to accomplish?').fill('backtest whether momentum survives transaction costs');
  await page.getByRole('button', { name: 'Plan workflow' }).click();
  await expect(page.getByText('Recommended workflow')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Quant Validation → Governance' })).toBeVisible();
  for (const stage of ['Quant', 'Agents', 'Governance', 'Artifact / Report']) {
    await expect(page.locator('.command-bar .nested .stage span').filter({ hasText: stage })).toBeVisible();
  }
});

test('Product surfaces are navigable from the Command Center', async ({ page }) => {
  await page.goto('/product');
  for (const [label, path] of [['Research', '/research'], ['Quant', '/quant/overview'], ['Agents', '/agents'], ['Governance', '/governance'], ['Artifacts / Reports', '/artifacts']]) {
    const link = page.locator(`a[href="${path}"]`).last();
    await expect(link).toBeVisible();
    await expect(link).toContainText(label);
  }
});
