const { app, BrowserWindow } = require("electron");
const fs = require("fs");
const path = require("path");

const mockupDir = __dirname;
const htmlPath = path.join(mockupDir, "index.html");
const shots = [
  { id: "concept-a", button: "concept-a", file: "concept-a-path.png" },
  { id: "concept-b", button: "concept-b", file: "concept-b-tutor-call.png" },
  { id: "concept-c", button: "concept-c", file: "concept-c-demo-studio.png" },
];

async function capture() {
  const win = new BrowserWindow({
    width: 1440,
    height: 1000,
    show: false,
    webPreferences: {
      offscreen: true,
      sandbox: true,
    },
  });

  await win.loadFile(htmlPath);

  for (const shot of shots) {
    await win.webContents.executeJavaScript(`
      document.querySelector('[data-target="${shot.button}"]').click();
      new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    `);
    const image = await win.webContents.capturePage();
    fs.writeFileSync(path.join(mockupDir, shot.file), image.toPNG());
  }

  win.destroy();
  app.quit();
}

app.whenReady().then(capture).catch((error) => {
  console.error(error);
  app.exit(1);
});
