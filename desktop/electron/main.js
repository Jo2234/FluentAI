const { app, BrowserWindow, ipcMain, systemPreferences } = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");

const projectRoot = path.resolve(__dirname, "..", "..");
const pythonExecutable = process.env.PYTHON_EXECUTABLE || "/Users/johanvaz/.pyenv/shims/python";
let mainWindow = null;

app.setName("FluentAI");

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
    const child = spawn(pythonExecutable, ["-m", "fluent_ai.desktop_bridge", command], {
      cwd: projectRoot,
      env: {
        ...process.env,
        PYTHONPATH: projectRoot
      }
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
    child.stdin.write(JSON.stringify(payload));
    child.stdin.end();
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    title: "FluentAI",
    width: 1440,
    height: 920,
    fullscreen: false,
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

  mainWindow.loadFile(path.join(__dirname, "renderer.html")).then(() => {
    if (app.dock) {
      app.dock.show();
    }
    mainWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
    mainWindow.setAlwaysOnTop(true, "screen-saver");
    mainWindow.maximize();
    mainWindow.show();
    app.focus({ steal: true });
    mainWindow.focus();
    mainWindow.moveTop();
    setTimeout(() => {
      if (mainWindow) {
        mainWindow.setAlwaysOnTop(false);
        mainWindow.setVisibleOnAllWorkspaces(false);
      }
    }, 3000);
  });
}

app.whenReady().then(() => {
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

ipcMain.handle("status", async () => {
  return runBridge("status");
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
