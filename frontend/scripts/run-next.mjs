import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import os from "node:os";
import path from "node:path";

const nodeMajorVersion = Number.parseInt(process.versions.node.split(".")[0] ?? "0", 10);
const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(scriptDirectory, "..");
const nextBinaryPath = path.join(
  frontendDirectory,
  "node_modules",
  "next",
  "dist",
  "bin",
  "next",
);
const nextCommand = process.argv[2] ?? "dev";

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

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }

  process.exit(code ?? 0);
});
