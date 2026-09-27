import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  workers: 1,
  retries: process.env.CI ? 2 : 0,
  reporter: [['html', { open: 'never' }], ['list']],

  use: {
    baseURL: 'http://localhost:3000',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    launchOptions: {
      args: [
        '--autoplay-policy=no-user-gesture-required',
        '--allow-file-access-from-files',
        '--mute-audio',
      ],
    },
  },

  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],

  webServer: [
    {
      command: 'npm run dev --workspace=apps/studio',
      url: 'http://localhost:3000',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});