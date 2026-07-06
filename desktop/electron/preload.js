const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("fluentAI", {
  status: (payload) => ipcRenderer.invoke("status", payload),
  onboardingStatus: (payload) => ipcRenderer.invoke("onboarding:status", payload),
  submitOnboarding: (payload) => ipcRenderer.invoke("onboarding:submit", payload),
  startPlacement: (payload) => ipcRenderer.invoke("placement:start", payload),
  submitPlacement: (payload) => ipcRenderer.invoke("placement:submit", payload),
  homeSummary: (payload) => ipcRenderer.invoke("home:summary", payload),
  memoryInspect: (payload) => ipcRenderer.invoke("memory:inspect", payload),
  memoryExport: (payload) => ipcRenderer.invoke("memory:export", payload),
  memoryResetLanguage: (payload) => ipcRenderer.invoke("memory:reset_language", payload),
  memoryDeleteAll: (payload) => ipcRenderer.invoke("memory:delete_all", payload),
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
