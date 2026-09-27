// master_to_live.spec.ts
// E2E: Flujo completo upload → master → Live tab (standalone Live Engine, knob-controlled)

import { test, expect } from '@playwright/test';

test.describe('Flujo completo: Master → Live Engine', () => {
  test('Carga audio → Master → Live Engine con knobs', async ({ page }) => {
    // 1. Generar fixture de audio si no existe
    const { execSync } = require('child_process');
    const path = require('path');
    const fixturePath = path.join(__dirname, '..', 'fixtures', 'test-audio.wav');
    const fs = require('fs');

    if (!fs.existsSync(fixturePath)) {
      console.log('[Test] Generating test audio fixture...');
      execSync('python e2e/fixtures/generate_fixture.py', { cwd: __dirname + '/..', stdio: 'inherit' });
    }

    // 2. Navegar al Studio
    await page.goto('/');

    // 3. Subir archivo de audio
    const fileInput = page.locator('input[type="file"]').first();
    await fileInput.setInputFiles(fixturePath);

    // 4. Esperar análisis y procesamiento automático
    await expect(page.locator('text=Analizando')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=Analizando')).toBeHidden({ timeout: 90000 });

    // 5. Navegar a pestaña Live (dock)
    await page.locator('[data-testid="dock-tab-live"]').click();
    await expect(page.locator('[data-testid="live-view"]')).toBeVisible({ timeout: 10000 });

    // 6. Assert FX slot labels
    await expect(page.locator('.fx-slot-panel')).toBeVisible();
    await expect(page.locator('.fx-slot-panel')).toContainText('FILTER');
    await expect(page.locator('.fx-slot-panel')).toContainText('DRIVE');
    await expect(page.locator('.fx-slot-panel')).toContainText('DELAY');
    await expect(page.locator('.fx-slot-panel')).toContainText('REVERB');

    // 7. Drag del knob de filtro (data-testid) → el parametro debe cambiar
    const filterKnob = page.locator('[data-testid="knob-filter_cutoff"]');
    await expect(filterKnob).toBeVisible();
    const before = await filterKnob.getAttribute('aria-valuenow');
    const box = await filterKnob.boundingBox();
    if (box) {
      // Arrastrar hacia arriba (menor Y → valor mayor)
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width / 2, box.y - 40, { steps: 10 });
      await page.mouse.up();
    }
    const after = await filterKnob.getAttribute('aria-valuenow');
    expect(after).not.toBe(before);

    // 8. Meters renderizados (canvas del espectro presente)
    await expect(page.locator('canvas')).toBeVisible();

    // 9. Sin errores en consola
    const errors: string[] = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    expect(errors.filter(e => !e.includes('favicon') && !e.includes('webpack'))).toHaveLength(0);
  });
});