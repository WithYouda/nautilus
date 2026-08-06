import { lstatSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, resolve } from "node:path";

export default function globalTeardown() {
  const dataDir = process.env.NAUTILUS_E2E_DATA_DIR;
  const tempRoot = resolve(tmpdir());
  const resolvedDataDir = dataDir ? resolve(dataDir) : "";
  const dataName = resolvedDataDir ? basename(resolvedDataDir) : "";

  if (
    dataDir &&
    dirname(resolvedDataDir) === tempRoot &&
    dataName.startsWith("nautilus-playwright.")
  ) {
    try {
      if (lstatSync(resolvedDataDir).isSymbolicLink()) return;
    } catch {
      return;
    }
    rmSync(resolvedDataDir, { recursive: true, force: true });
  }
}
