const assert = require("node:assert/strict");
const { redactSecrets } = require("../desktop/electron/security");

const raw = {
  ok: false,
  raw: "HTTP 401 for sk-test_1234567890abcdef with salt=salt-1234567890",
  logs: ["retry did not expose sk-proj_abcdef1234567890"],
};

const redacted = redactSecrets(raw);

assert(!redacted.raw.includes("sk-test_1234567890abcdef"));
assert(redacted.raw.includes("[redacted secret]"));
assert(redacted.raw.includes("salt=salt-1234567890"));
assert(!redacted.logs[0].includes("sk-proj_abcdef1234567890"));
