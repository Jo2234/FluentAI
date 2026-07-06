const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("fluentAI", {
  status: (payload) => ipcRenderer.invoke("status", payload),
  startLesson: (payload) => ipcRenderer.invoke("lesson:start", payload),
  submitLesson: (payload) => ipcRenderer.invoke("lesson:submit", payload),
  realtimeClientSecret: (payload) => ipcRenderer.invoke("realtime:client_secret", payload),
  analyzeCameraFrame: (payload) => ipcRenderer.invoke("vision:analyze_frame", payload),
  requestMediaAccess: (payload) => ipcRenderer.invoke("media:request_access", payload),
  mediaDiagnostics: () => ipcRenderer.invoke("media:diagnostics"),
  startConversation: (options) => ipcRenderer.invoke("conversation:start", options),
  replyConversation: (payload) => ipcRenderer.invoke("conversation:reply", payload),
  endConversation: (payload) => ipcRenderer.invoke("conversation:end", payload)
});
