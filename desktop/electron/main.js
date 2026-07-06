const { app, BrowserWindow, ipcMain, systemPreferences } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const projectRoot = process.env.FLUENTAI_PROJECT_ROOT || path.resolve(__dirname, "..", "..");
const pythonExecutable = resolvePythonExecutable();
let mainWindow = null;

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

function buildPackagedEnv(statePath) {
  const env = {};
  for (const key of ["PATH", "HOME", "TMPDIR", "LANG"]) {
    if (process.env[key]) {
      env[key] = process.env[key];
    }
  }

  if (process.env.OPENAI_API_KEY) {
    env.OPENAI_API_KEY = process.env.OPENAI_API_KEY;
  }

  for (const [key, value] of Object.entries(process.env)) {
    if (key.startsWith("FLUENTAI_")) {
      env[key] = value;
    }
  }

  env.FLUENTAI_STATE_PATH = statePath;
  return env;
}

function resolveBridgeCommand(bridgeCommand) {
  const statePath = resolveStatePath();

  if (app.isPackaged) {
    const userDataPath = app.getPath("userData");
    fs.mkdirSync(userDataPath, { recursive: true });
    return {
      command: path.join(process.resourcesPath, "bridge", "fluentai-bridge", "fluentai-bridge"),
      args: [bridgeCommand],
      cwd: userDataPath,
      env: buildPackagedEnv(statePath),
      statePath
    };
  }

  return {
    command: pythonExecutable,
    args: ["-m", "fluent_ai.desktop_bridge", bridgeCommand],
    cwd: projectRoot,
    env: {
      ...process.env,
      PYTHONPATH: projectRoot
    },
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

function runBridge(command, payload = {}) {
  return new Promise((resolve) => {
    const bridge = resolveBridgeCommand(command);
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
      resolve({ ok: false, error: `Could not start Python agent process: ${error.message}` });
    });
    child.on("close", (code) => {
      if (code !== 0) {
        resolve({ ok: false, error: `Agent process exited with status ${code}.`, raw: output.trim() });
        return;
      }
      try {
        resolve(JSON.parse(output));
      } catch (error) {
        resolve({ ok: false, error: `Agent returned non-JSON output: ${error.message}`, raw: output.trim() });
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

ipcMain.handle("lesson:start", async (_event, payload) => {
  return runBridge("lesson_start", payload || {});
});

ipcMain.handle("lesson:submit", async (_event, payload) => {
  return runBridge("lesson_submit", payload);
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
    result.error = wantsVideo
      ? "Microphone or camera permission is blocked for FluentAI. Allow access in System Settings, then press Call again."
      : "Microphone permission is blocked for FluentAI. Allow access in System Settings, then press Call again.";
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
