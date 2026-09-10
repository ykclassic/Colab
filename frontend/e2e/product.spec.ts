import { expect, test } from '@playwright/test';

test('Command Center turns a user goal into a visible workflow plan', async ({ page }) => {
  await page.goto('/product');
  await expect(page.getByRole('heading', { name: 'Turn a goal into a workflow.' })).toBeVisible();
  await page.getByLabel('What are you trying to accomplish?').fill('investigate whether momentum survives transaction costs');
  await page.getByRole('button', { name: 'Plan workflow' }).click();
  await expect(page.getByText('Recommended workflow')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Quant Validation → Governance' })).toBeVisible();
  for (const stage of ['Quant', 'Agents', 'Governance', 'Artifact / Report']) {
    await expect(page.getByText(stage, { exact: true })).toBeVisible();
  }
});

test('Product surfaces are navigable from the Command Center', async ({ page }) => {
  await page.goto('/product');
  for (const [label, path] of [['Research', '/research'], ['Quant', '/quant/overview'], ['Agents', '/agents'], ['Governance', '/governance'], ['Artifacts / Reports', '/artifacts']]) {
    const link = page.getByRole('link', { name: label, exact: true }).last();
    await expect(link).toHaveAttribute('href', path);
  }
});
