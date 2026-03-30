/**
 * OpenVegas e2e helper parity with Pixel Agents launch helper.
 *
 * This is a scaffolding file for Playwright-based UI harness work.
 */
export type OpenVegasUiSession = {
  baseUrl: string;
  cleanup: () => Promise<void>;
};

export async function launchOpenVegasUi(baseUrl: string): Promise<OpenVegasUiSession> {
  return {
    baseUrl,
    cleanup: async () => {},
  };
}
