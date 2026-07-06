const { app, BrowserWindow, dialog, ipcMain, safeStorage, systemPreferences } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { redactSecrets } = require("./security");

const projectRoot = process.env.FLUENTAI_PROJECT_ROOT || path.resolve(__dirname, "..", "..");
const pythonExecutable = resolvePythonExecutable();
let mainWindow = null;
let sessionOpenAIKey = null;

function resolvePythonExecutable() {
  if (process.env.PYTHON_EXECUTABLE) {
    return process.env.PYTHON_EXECUTABLE;
  }

  const venvPython = process.platform === "win32"
    ? path.join(projectRoot, ".venv", "Scripts", "python.exe")
    : path.join(projectRoot, ".venv", "bin", "python");
  if (fs.existsSync(venvPython)) {
    return venvPython;
  }

  return process.platform === "win32" ? "python" : "python3";
}

app.setName("FluentAI");
if (process.env.FLUENTAI_USER_DATA_PATH) {
  app.setPath("userData", process.env.FLUENTAI_USER_DATA_PATH);
}

function resolveStatePath() {
  if (process.env.FLUENTAI_STATE_PATH) {
    return process.env.FLUENTAI_STATE_PATH;
  }

  if (app.isPackaged) {
    return path.join(app.getPath("userData"), "progress.json");
  }

  return path.join(projectRoot, "data", "progress.json");
}

function resolveLegacyStatePath() {
  if (process.env.FLUENTAI_LEGACY_STATE_PATH && fs.existsSync(process.env.FLUENTAI_LEGACY_STATE_PATH)) {
    return process.env.FLUENTAI_LEGACY_STATE_PATH;
  }

  if (!process.env.FLUENTAI_PROJECT_ROOT) {
    return null;
  }

  const repoStatePath = path.join(process.env.FLUENTAI_PROJECT_ROOT, "data", "progress.json");
  return fs.existsSync(repoStatePath) ? repoStatePath : null;
}

function migratePackagedStateIfNeeded() {
  if (!app.isPackaged || process.env.FLUENTAI_STATE_PATH) {
    return;
  }

  const statePath = resolveStatePath();
  if (fs.existsSync(statePath)) {
    return;
  }

  const legacyStatePath = resolveLegacyStatePath();
  if (!legacyStatePath) {
    return;
  }

  fs.mkdirSync(path.dirname(statePath), { recursive: true });
  fs.copyFileSync(legacyStatePath, statePath, fs.constants.COPYFILE_EXCL);
  console.log("[Memory Agent] Migrated learner profile to Application Support.");
}

function settingsPath() {
  return path.join(app.getPath("userData"), "settings.json");
}

function readSettings() {
  try {
    const filePath = settingsPath();
    if (!fs.existsSync(filePath)) {
      return {};
    }
    const parsed = JSON.parse(fs.readFileSync(filePath, "utf-8"));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch (_error) {
    return {};
  }
}

function writeSettings(settings) {
  const filePath = settingsPath();
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(settings, null, 2) + "\n");
}

function readStoredOpenAIKey() {
  if (!safeStorage.isEncryptionAvailable()) {
    return null;
  }
  const encrypted = readSettings().openai_api_key_encrypted;
  if (!encrypted || typeof encrypted !== "string") {
    return null;
  }
  try {
    return safeStorage.decryptString(Buffer.from(encrypted, "base64"));
  } catch (_error) {
    return null;
  }
}

function saveStoredOpenAIKey(key) {
  const now = new Date().toISOString();
  const encrypted = safeStorage.encryptString(key).toString("base64");
  writeSettings({
    openai_api_key_encrypted: encrypted,
    created_at: readSettings().created_at || now,
    last_validated_at: now
  });
}

function deleteStoredOpenAIKey() {
  const current = readSettings();
  delete current.openai_api_key_encrypted;
  delete current.created_at;
  delete current.last_validated_at;
  writeSettings(current);
}

function devEnvFileHasOpenAIKey() {
  if (app.isPackaged) {
    return false;
  }
  const envPath = path.join(projectRoot, ".env");
  try {
    const text = fs.readFileSync(envPath, "utf-8");
    return text.split(/\r?\n/).some((line) => /^\s*OPENAI_API_KEY\s*=\s*\S+/.test(line));
  } catch (_error) {
    return false;
  }
}

function resolveOpenAIKeyStatus() {
  if (process.env.OPENAI_API_KEY) {
    return { available: true, source: "env", persisted: false, encryptionAvailable: safeStorage.isEncryptionAvailable() };
  }

  if (sessionOpenAIKey) {
    return { available: true, source: "session", persisted: false, encryptionAvailable: safeStorage.isEncryptionAvailable() };
  }

  const stored = readStoredOpenAIKey();
  if (stored) {
    return { available: true, source: "stored", persisted: true, encryptionAvailable: safeStorage.isEncryptionAvailable() };
  }

  if (devEnvFileHasOpenAIKey()) {
    return { available: true, source: "dev-env-file", persisted: false, encryptionAvailable: safeStorage.isEncryptionAvailable() };
  }

  return { available: false, source: "missing", persisted: false, encryptionAvailable: safeStorage.isEncryptionAvailable() };
}

function resolvedOpenAIKeyForChild() {
  if (process.env.OPENAI_API_KEY) {
    return process.env.OPENAI_API_KEY;
  }
  if (sessionOpenAIKey) {
    return sessionOpenAIKey;
  }
  return readStoredOpenAIKey();
}

function buildPackagedEnv(statePath, openAIKeyOverride) {
  const env = {};
  for (const key of ["PATH", "HOME", "TMPDIR", "LANG"]) {
    if (process.env[key]) {
      env[key] = process.env[key];
    }
  }

  const openAIKey = openAIKeyOverride || resolvedOpenAIKeyForChild();
  if (openAIKey) {
    env.OPENAI_API_KEY = openAIKey;
  }

  for (const [key, value] of Object.entries(process.env)) {
    if (key.startsWith("FLUENTAI_")) {
      env[key] = value;
    }
  }

  env.FLUENTAI_STATE_PATH = statePath;
  return env;
}

function resolveBridgeCommand(bridgeCommand, options = {}) {
  const statePath = resolveStatePath();
  const openAIKey = options.openAIKey || resolvedOpenAIKeyForChild();

  if (app.isPackaged) {
    const userDataPath = app.getPath("userData");
    fs.mkdirSync(userDataPath, { recursive: true });
    return {
      command: path.join(process.resourcesPath, "bridge", "fluentai-bridge", "fluentai-bridge"),
      args: [bridgeCommand],
      cwd: userDataPath,
      env: buildPackagedEnv(statePath, openAIKey),
      statePath
    };
  }

  const env = {
    ...process.env,
    PYTHONPATH: projectRoot
  };
  if (openAIKey) {
    env.OPENAI_API_KEY = openAIKey;
  }

  return {
    command: pythonExecutable,
    args: ["-m", "fluent_ai.desktop_bridge", bridgeCommand],
    cwd: projectRoot,
    env,
    statePath
  };
}

function withStatePath(payload, statePath) {
  const bridgePayload = payload && typeof payload === "object" && !Array.isArray(payload)
    ? { ...payload }
    : {};

  if (!bridgePayload.state_path) {
    bridgePayload.state_path = statePath;
  }

  return bridgePayload;
}

if (process.env.FLUENTAI_REMOTE_DEBUGGING_PORT) {
  app.commandLine.appendSwitch("remote-debugging-port", process.env.FLUENTAI_REMOTE_DEBUGGING_PORT);
}

if (process.env.FLUENTAI_FAKE_MEDIA === "1") {
  app.commandLine.appendSwitch("use-fake-ui-for-media-stream");
  app.commandLine.appendSwitch("use-fake-device-for-media-stream");
  app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");
}

function runBridge(command, payload = {}, options = {}) {
  return new Promise((resolve) => {
    const bridge = resolveBridgeCommand(command, options);
    const child = spawn(bridge.command, bridge.args, {
      cwd: bridge.cwd,
      env: bridge.env
    });

    let output = "";
    child.stdout.on("data", (chunk) => {
      output += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      output += chunk.toString();
    });
    child.on("error", (error) => {
      resolve(redactSecrets({ ok: false, error: `Could not start Python agent process: ${error.message}` }));
    });
    child.on("close", (code) => {
      if (code !== 0) {
        resolve(redactSecrets({ ok: false, error: `Agent process exited with status ${code}.`, raw: output.trim() }));
        return;
      }
      try {
        resolve(redactSecrets(JSON.parse(output)));
      } catch (error) {
        resolve(redactSecrets({ ok: false, error: `Agent returned non-JSON output: ${error.message}`, raw: output.trim() }));
      }
    });
    child.stdin.write(JSON.stringify(withStatePath(payload, bridge.statePath)));
    child.stdin.end();
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    title: "FluentAI",
    width: 1440,
    height: 920,
    fullscreen: true,
    autoHideMenuBar: true,
    show: true,
    backgroundColor: "#ffffff",
    webPreferences: {
      preload: path.join(__dirname, "preload.js")
    }
  });

  mainWindow.webContents.session.setPermissionCheckHandler((webContents, permission) => {
    return permission === "media" && webContents && mainWindow && webContents.id === mainWindow.webContents.id;
  });

  mainWindow.webContents.session.setPermissionRequestHandler((webContents, permission, callback) => {
    callback(permission === "media" && webContents && mainWindow && webContents.id === mainWindow.webContents.id);
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  mainWindow.webContents.on("before-input-event", (event, input) => {
    if (input.key === "Escape" && mainWindow && mainWindow.isFullScreen()) {
      mainWindow.setFullScreen(false);
      event.preventDefault();
    }
  });

  mainWindow.loadFile(path.join(__dirname, "renderer.html")).then(() => {
    if (app.dock) {
      app.dock.show();
    }
    mainWindow.show();
    mainWindow.focus();
  });
}

app.whenReady().then(() => {
  migratePackagedStateIfNeeded();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

ipcMain.handle("status", async (_event, payload) => {
  return runBridge("status", payload || {});
});

ipcMain.handle("key:status", async () => {
  return { ok: true, ...resolveOpenAIKeyStatus() };
});

ipcMain.handle("key:validate", async (_event, payload = {}) => {
  const candidate = typeof payload.key === "string" ? payload.key.trim() : "";
  if (!candidate) {
    return { ok: true, valid: false, message: "Add an OpenAI API key to continue." };
  }
  return runBridge("validate_key", {}, { openAIKey: candidate });
});

ipcMain.handle("key:save", async (_event, payload = {}) => {
  const candidate = typeof payload.key === "string" ? payload.key.trim() : "";
  if (!candidate) {
    return { ok: false, message: "Add an OpenAI API key to continue." };
  }

  if (!safeStorage.isEncryptionAvailable()) {
    sessionOpenAIKey = candidate;
    return { ok: true, persisted: false, source: "session", message: "Key is available for this session." };
  }

  try {
    saveStoredOpenAIKey(candidate);
    sessionOpenAIKey = null;
    return { ok: true, persisted: true, source: "stored", message: "Key saved securely." };
  } catch (error) {
    sessionOpenAIKey = candidate;
    return {
      ok: true,
      persisted: false,
      source: "session",
      message: `Secure storage was unavailable; key is available for this session.`
    };
  }
});

ipcMain.handle("key:delete", async () => {
  sessionOpenAIKey = null;
  try {
    deleteStoredOpenAIKey();
  } catch (_error) {
    return { ok: false, message: "Could not remove the stored key." };
  }
  return { ok: true, ...resolveOpenAIKeyStatus() };
});

ipcMain.handle("onboarding:status", async (_event, payload) => {
  return runBridge("onboarding_status", payload || {});
});

ipcMain.handle("onboarding:submit", async (_event, payload) => {
  return runBridge("onboarding_submit", payload || {});
});

ipcMain.handle("placement:start", async (_event, payload) => {
  return runBridge("placement_start", payload || {});
});

ipcMain.handle("placement:submit", async (_event, payload) => {
  return runBridge("placement_submit", payload || {});
});

ipcMain.handle("home:summary", async (_event, payload) => {
  return runBridge("home_summary", payload || {});
});

ipcMain.handle("memory:inspect", async (_event, payload) => {
  return runBridge("memory_inspect", payload || {});
});

ipcMain.handle("memory:export", async (_event, payload) => {
  const result = await runBridge("memory_export", payload || {});
  if (!result.ok) {
    return result;
  }
  const save = await dialog.showSaveDialog(mainWindow, {
    title: "Export FluentAI Memory",
    defaultPath: result.filename || "fluentai-memory.json",
    filters: [{ name: "JSON", extensions: ["json"] }]
  });
  if (save.canceled || !save.filePath) {
    return { ok: false, canceled: true, logs: ["[Privacy Agent] Memory export canceled."] };
  }
  try {
    fs.writeFileSync(save.filePath, JSON.stringify(result.data, null, 2));
    return { ok: true, path: save.filePath, logs: result.logs || [] };
  } catch (error) {
    return { ok: false, error: `Could not write memory export: ${error.message}`, logs: result.logs || [] };
  }
});

ipcMain.handle("memory:reset_language", async (_event, payload) => {
  return runBridge("memory_reset_language", payload || {});
});

ipcMain.handle("memory:delete_all", async (_event, payload) => {
  return runBridge("memory_delete_all", payload || {});
});

ipcMain.handle("session:checkpoints", async (_event, payload) => {
  return runBridge("session_checkpoints", payload || {});
});

ipcMain.handle("lesson:checkpoint", async (_event, payload) => {
  return runBridge("lesson_checkpoint", payload || {});
});

ipcMain.handle("lesson:checkpoint_discard", async (_event, payload) => {
  return runBridge("lesson_checkpoint_discard", payload || {});
});

ipcMain.handle("call:checkpoint", async (_event, payload) => {
  return runBridge("call_checkpoint", payload || {});
});

ipcMain.handle("call:checkpoint_discard", async (_event, payload) => {
  return runBridge("call_checkpoint_discard", payload || {});
});

ipcMain.handle("call:checkpoint_summarize", async (_event, payload) => {
  return runBridge("call_checkpoint_summarize", payload || {});
});

ipcMain.handle("lesson:start", async (_event, payload) => {
  return runBridge("lesson_start", payload || {});
});

ipcMain.handle("lesson:submit", async (_event, payload) => {
  return runBridge("lesson_submit", payload);
});

ipcMain.handle("phrase:audio", async (_event, payload) => {
  return runBridge("phrase_audio", payload || {});
});

ipcMain.handle("realtime:client_secret", async (_event, payload) => {
  return runBridge("realtime_client_secret", payload || {});
});

ipcMain.handle("vision:analyze_frame", async (_event, payload) => {
  return runBridge("vision_analyze_frame", payload || {});
});

ipcMain.handle("media:diagnostics", async () => {
  return {
    ok: true,
    fakeMedia: process.env.FLUENTAI_FAKE_MEDIA === "1",
  };
});

ipcMain.handle("media:request_access", async (_event, payload = {}) => {
  const wantsVideo = payload.video === "on" || payload.video === true;
  if (process.platform !== "darwin") {
    return { ok: true, microphone: "granted", camera: wantsVideo ? "granted" : "not-requested" };
  }

  const result = {
    ok: true,
    microphone: systemPreferences.getMediaAccessStatus("microphone"),
    camera: wantsVideo ? systemPreferences.getMediaAccessStatus("camera") : "not-requested"
  };

  if (result.microphone === "not-determined") {
    const granted = await systemPreferences.askForMediaAccess("microphone");
    result.microphone = granted ? "granted" : systemPreferences.getMediaAccessStatus("microphone");
  }

  if (wantsVideo && result.camera === "not-determined") {
    const granted = await systemPreferences.askForMediaAccess("camera");
    result.camera = granted ? "granted" : systemPreferences.getMediaAccessStatus("camera");
  }

  result.ok = result.microphone === "granted" && (!wantsVideo || result.camera === "granted");
  if (!result.ok) {
    if (result.microphone !== "granted") {
      result.error = "Microphone permission is blocked for FluentAI. Allow access in System Settings, then press Call again.";
    } else if (wantsVideo && result.camera !== "granted") {
      result.error = "Camera is blocked. Continuing voice-only.";
    }
  }
  return result;
});

ipcMain.handle("conversation:start", async (_event, options) => {
  return runBridge("conversation_start", options);
});

ipcMain.handle("conversation:reply", async (_event, payload) => {
  return runBridge("conversation_reply", payload);
});

ipcMain.handle("conversation:end", async (_event, payload) => {
  return runBridge("conversation_end", payload || {});
});
