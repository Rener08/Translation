import { spawn } from "node:child_process";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import os from "node:os";
import path from "node:path";

const nodeMajorVersion = Number.parseInt(process.versions.node.split(".")[0] ?? "0", 10);
const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(scriptDirectory, "..");
const repoRoot = path.resolve(frontendDirectory, "..");
const nextBinaryPath = path.join(
  frontendDirectory,
  "node_modules",
  "next",
  "dist",
  "bin",
  "next",
);
const nextCommand = process.argv[2] ?? "dev";
const configuredApiBaseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").trim();
const backendSupervisionEnabled =
  nextCommand === "dev" &&
  process.env.TRANSLATION_DISABLE_BACKEND_SUPERVISOR !== "1" &&
  shouldSuperviseLocalBackend(configuredApiBaseUrl);
const backendTarget = resolveBackendTarget(configuredApiBaseUrl);
const backendHealthUrl = backendTarget ? `${backendTarget.baseUrl}/health` : "";
let backendChild = null;
let backendStartAt = 0;
let backendMonitorTimer = null;
let backendLogFd = null;
let shuttingDown = false;

const env = { ...process.env };
const existingNodeOptions = env.NODE_OPTIONS ?? "";
const sanitizedNodeOptions = existingNodeOptions
  .replace(/(^|\s)--localstorage-file(?:=[^\s]*)?(?=\s|$)/g, " ")
  .trim()
  .replace(/\s+/g, " ");

const polyfillPath = path.join(scriptDirectory, "localstorage-polyfill.js");
const requirePolyfill = `--require=${polyfillPath}`;

// Node 25 can expose a broken server-side localStorage in Next dev.
// We polyfill it instead of relying on the experimental --localstorage-file flag.
if (nodeMajorVersion >= 25) {
  env.NODE_OPTIONS = sanitizedNodeOptions
    ? `${sanitizedNodeOptions} ${requirePolyfill}`
    : requirePolyfill;
} else if (sanitizedNodeOptions) {
  env.NODE_OPTIONS = sanitizedNodeOptions;
} else {
  delete env.NODE_OPTIONS;
}

const child = spawn(process.execPath, [nextBinaryPath, nextCommand, ...process.argv.slice(3)], {
  stdio: "inherit",
  env,
});

if (backendSupervisionEnabled && backendTarget) {
  void superviseBackend();
}

child.on("exit", (code, signal) => {
  shuttingDown = true;
  clearBackendMonitorTimer();
  stopBackendChild();
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }

  process.exit(code ?? 0);
});

process.on("SIGINT", () => {
  shuttingDown = true;
  clearBackendMonitorTimer();
  stopBackendChild();
  child.kill("SIGINT");
});

process.on("SIGTERM", () => {
  shuttingDown = true;
  clearBackendMonitorTimer();
  stopBackendChild();
  child.kill("SIGTERM");
});

process.on("exit", () => {
  shuttingDown = true;
  clearBackendMonitorTimer();
  stopBackendChild();
  closeBackendLogFile();
});

function shouldSuperviseLocalBackend(apiBaseUrl) {
  if (!apiBaseUrl) {
    return true;
  }

  try {
    const parsed = new URL(apiBaseUrl);
    return isLocalBackendHostname(parsed.hostname);
  } catch {
    return false;
  }
}

function resolveBackendTarget(apiBaseUrl) {
  const defaultTarget = {
    baseUrl: "http://127.0.0.1:8000",
    host: "127.0.0.1",
    port: 8000,
  };

  if (!apiBaseUrl) {
    return defaultTarget;
  }

  try {
    const parsed = new URL(apiBaseUrl);
    if (!isLocalBackendHostname(parsed.hostname)) {
      return null;
    }

    const host = parsed.hostname;
    const port = Number.parseInt(parsed.port || "8000", 10) || 8000;
    const protocol = parsed.protocol || "http:";
    return {
      baseUrl: `${protocol}//${host}:${port}`,
      host,
      port,
    };
  } catch {
    return defaultTarget;
  }
}

function isLocalBackendHostname(hostname) {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

function resolveBackendLauncher(target) {
  const host = target.host || "127.0.0.1";
  const port = String(target.port || 8000);
  const backendDir = path.join(repoRoot, "backend");

  if (process.platform === "win32") {
    const uvicornCmd = path.join(backendDir, "uvicorn.cmd");
    if (fs.existsSync(uvicornCmd)) {
      return {
        command: uvicornCmd,
        args: [
          "app.main:app",
          "--app-dir",
          backendDir,
          "--host",
          host,
          "--port",
          port,
        ],
      };
    }
  }

  const backendPythonCandidates = process.platform === "win32"
    ? [
        path.join(backendDir, ".venv", "Scripts", "python.exe"),
        path.join(backendDir, ".venv", "Scripts", "python"),
      ]
    : [
        path.join(backendDir, ".venv", "bin", "python"),
        path.join(backendDir, ".venv", "bin", "python3"),
      ];

  for (const candidate of backendPythonCandidates) {
    if (fs.existsSync(candidate)) {
      return {
        command: candidate,
        args: [
          "-m",
          "uvicorn",
          "app.main:app",
          "--app-dir",
          backendDir,
          "--host",
          host,
          "--port",
          port,
        ],
      };
    }
  }

  return null;
}

async function superviseBackend() {
  while (!shuttingDown) {
    try {
      if (await probeBackendHealth()) {
        clearBackendMonitorTimer();
        await waitForBackendMonitorTick();
        continue;
      }

      if (backendChild && backendChild.exitCode === null && !backendChild.killed) {
        const backendAgeMs = Date.now() - backendStartAt;
        if (backendAgeMs < 45_000) {
          await waitForBackendMonitorTick(1500);
          continue;
        }
        stopBackendChild();
      }

      if (!backendChild || backendChild.exitCode !== null) {
        startBackendChild();
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.warn(`[backend-supervisor] ${message}`);
    }

    await waitForBackendMonitorTick();
  }
}

function startBackendChild() {
  if (!backendTarget) {
    return;
  }

  const launcher = resolveBackendLauncher(backendTarget);
  if (!launcher) {
    throw new Error(
      "Backend supervisor could not find a local Python/uvicorn launcher. Install backend/.venv first.",
    );
  }

  if (backendLogFd === null) {
    backendLogFd = fs.openSync(path.join(repoRoot, "backend_run.log"), "a");
  }

  fs.mkdirSync(path.join(repoRoot, "tmp"), { recursive: true });
  backendStartAt = Date.now();
  backendChild = spawn(launcher.command, launcher.args, {
    cwd: repoRoot,
    env,
    stdio: ["ignore", backendLogFd, backendLogFd],
    windowsHide: true,
  });

  try {
    fs.writeFileSync(
      path.join(repoRoot, "tmp", "backend.pid"),
      `${backendChild.pid ?? ""}\n`,
      { encoding: "utf8" },
    );
  } catch {
    // Ignore pid file write failures; the watchdog still keeps the backend alive.
  }

  console.log(
    `[backend-supervisor] started backend on ${backendTarget.baseUrl} (pid: ${backendChild.pid ?? "unknown"})`,
  );

  backendChild.on("exit", (code, signal) => {
    const wasShuttingDown = shuttingDown;
    backendChild = null;
    if (wasShuttingDown) {
      return;
    }
    console.warn(
      `[backend-supervisor] backend exited (code: ${code ?? "unknown"}, signal: ${signal ?? "none"}), will retry`,
    );
  });
}

function stopBackendChild() {
  if (!backendChild) {
    return;
  }

  try {
    backendChild.kill("SIGTERM");
  } catch {
    // Ignore best-effort shutdown errors.
  }
  backendChild = null;
}

function closeBackendLogFile() {
  if (backendLogFd === null) {
    return;
  }

  try {
    fs.closeSync(backendLogFd);
  } catch {
    // Ignore cleanup errors.
  }
  backendLogFd = null;
}

function clearBackendMonitorTimer() {
  if (backendMonitorTimer !== null) {
    clearTimeout(backendMonitorTimer);
    backendMonitorTimer = null;
  }
}

async function waitForBackendMonitorTick(delayMs = 2000) {
  clearBackendMonitorTimer();
  await new Promise((resolve) => {
    backendMonitorTimer = setTimeout(resolve, delayMs);
  });
  backendMonitorTimer = null;
}

async function probeBackendHealth() {
  if (!backendHealthUrl) {
    return false;
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2000);

  try {
    const response = await fetch(backendHealthUrl, {
      method: "GET",
      cache: "no-store",
      signal: controller.signal,
    });
    return response.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timeout);
  }
}
