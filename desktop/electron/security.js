const SECRET_PATTERN = /sk-[A-Za-z0-9_-]{8,}/g;

function redactSecrets(value) {
  if (typeof value === "string") {
    return value.replace(SECRET_PATTERN, "[redacted secret]");
  }
  if (Array.isArray(value)) {
    return value.map(redactSecrets);
  }
  if (value && typeof value === "object") {
    const clean = {};
    for (const [key, item] of Object.entries(value)) {
      clean[key] = redactSecrets(item);
    }
    return clean;
  }
  return value;
}

module.exports = { redactSecrets, SECRET_PATTERN };
