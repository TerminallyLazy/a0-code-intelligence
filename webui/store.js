import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import { open } from "/js/surfaces.js";
import { toastFrontendError, toastFrontendSuccess } from "/components/notifications/notification-store.js";

export const store = createStore("codeIntelligence", {
  tab: "diagnostics", status: null, busy: false, timer: null, context: "",
  path: "", line: 1, column: 1, newName: "", queryResult: null, actions: [],
  queryAction: "references", queryKind: "", actionsLoaded: false,
  target: "", breakpointPath: "", breakpointLines: "", session: null, frames: [], scopes: [], variables: [], output: "",
  selectedFrame: null, selectedScope: null, variableHistory: [],
  tabs: [
    {id:"diagnostics", label:"Diagnostics", icon:"rule"},
    {id:"edits", label:"Edits", icon:"difference"},
    {id:"debugger", label:"Debugger", icon:"bug_report"},
    {id:"setup", label:"Setup", icon:"tune"},
  ],
  controls: [
    {action:"continue", label:"Continue", icon:"play_arrow"},
    {action:"pause", label:"Pause", icon:"pause"},
    {action:"next", label:"Step over", icon:"redo"},
    {action:"step_in", label:"Step into", icon:"arrow_downward"},
    {action:"step_out", label:"Step out", icon:"arrow_upward"},
    {action:"stop", label:"Stop session", icon:"stop"},
  ],
  get reports() { return this.status?.workspace?.diagnostics || []; },
  get monitorSummary() {
    const workspace = this.status?.workspace;
    if (!workspace?.monitor?.active) return "Automatic diagnostics are paused.";
    const count = (workspace.servers || []).filter(s => !s.failed).length;
    return count ? `Watching project changes · ${count} language server${count === 1 ? "" : "s"} running` : "Watching project changes · servers start when needed";
  },
  get proposals() { return this.status?.workspace?.proposals || []; },
  get pendingEdits() { return this.proposals.filter(p => p.status === "proposed" && p.expires_in_seconds > 0).length; },
  get errorCount() { return this.reports.reduce((n,r) => n + (r.diagnostics || []).filter(d => d.severity === 1).length, 0); },
  get warningCount() { return this.reports.reduce((n,r) => n + (r.diagnostics || []).filter(d => d.severity === 2).length, 0); },
  get activeDebug() { return this.session && ["starting","running","stopped"].includes(this.session.state); },
  get stopped() { return this.session?.state === "stopped"; },
  relative(path) { const root = this.status?.scope.root; return root && path?.startsWith(root + "/") ? path.slice(root.length + 1) : path || ""; },
  title(value) { return value ? value[0].toUpperCase() + value.slice(1) : ""; },
  severity(item) { return ({1:"Error",2:"Warning",3:"Information",4:"Hint"})[item.severity] || "Information"; },
  severityIcon(item) { return ({1:"error",2:"warning",3:"info",4:"lightbulb"})[item.severity] || "info"; },
  stateIcon(state) { return ({current:"check_circle",unversioned:"history",pending:"hourglass_top",stale:"update",unavailable:"cloud_off",stopped:"pause_circle",running:"play_circle",terminated:"stop_circle",failed:"error"})[state] || "info"; },
  expiry(seconds) { return seconds > 0 ? Math.ceil(seconds / 60) + " min remaining" : "Expired"; },
  diffClass(line) { return line.startsWith("+++") || line.startsWith("---") ? "ci-diff-meta" : line.startsWith("+") ? "ci-diff-add" : line.startsWith("-") ? "ci-diff-remove" : line.startsWith("@@") ? "ci-diff-hunk" : ""; },
  controlDisabled(action) { return this.busy || !this.activeDebug || (action === "pause" ? !["running","starting"].includes(this.session.state) : action !== "stop" && !this.stopped); },
  switchTab(event) {
    if (!["ArrowLeft","ArrowRight","Home","End"].includes(event.key)) return;
    event.preventDefault();
    let index = this.tabs.findIndex(t => t.id === this.tab);
    index = event.key === "Home" ? 0 : event.key === "End" ? 3 : (index + (event.key === "ArrowRight" ? 1 : 3)) % 4;
    this.tab = this.tabs[index].id;
    event.currentTarget.querySelectorAll('[role="tab"]')[index]?.focus();
  },
  get queryItems() {
    const value = this.queryResult?.items || (Array.isArray(this.queryResult?.result) ? this.queryResult.result : this.queryResult?.result ? [this.queryResult.result] : []);
    return value.filter(v => v && (v.uri || v.targetUri || v.location || v.name)).map(v => {
      const uri = v.uri || v.targetUri || v.location?.uri;
      let path = this.path;
      try { if (uri?.startsWith("file:")) path = decodeURIComponent(new URL(uri).pathname); } catch {}
      return {path, label:v.name || this.relative(path), line:(v.range || v.targetSelectionRange || v.location?.range || v.selectionRange)?.start?.line + 1 || 1};
    });
  },
  get hoverText() {
    const contents = this.queryResult?.result?.contents;
    return (Array.isArray(contents) ? contents : contents ? [contents] : []).map(c => typeof c === "string" ? c : c.value || "").join("\n\n");
  },
  async request(operation, more = {}) {
    const context = globalThis.getContext?.();
    if (!context) throw new Error("Select a chat in the intended project.");
    const result = await callJsonApi("plugins/code_intelligence/command", { context_id: context, operation, ...more });
    if (!result.ok) throw new Error(result.error || "Code Intelligence request failed.");
    if (context !== globalThis.getContext?.()) throw new Error("The selected chat changed. Refresh before continuing.");
    return result;
  },
  async run(work) {
    if (this.busy) return;
    this.busy = true;
    try { return await work(); }
    catch (error) { toastFrontendError(String(error.message || error), "Code Intelligence"); }
    finally { this.busy = false; }
  },
  async refresh(silent = false) {
    const refresh = async () => {
      const context = globalThis.getContext?.();
      if (context !== this.context) {
        this.status = null; this.session = null; this.frames = []; this.scopes = []; this.variables = [];
        this.actions = []; this.queryResult = null; this.context = context; this.target = "";
        this.path = ""; this.breakpointPath = ""; this.newName = ""; this.output = "";
      }
      this.status = await this.request("status");
      if (!this.path && this.reports.length) this.path = this.relative(this.reports[0].path);
      if (!this.target) this.target = Object.keys(this.status.scope.debug_targets || {})[0] || "";
      const sessions = this.status.workspace?.debuggers || [];
      const next = sessions.find(s => s.session_id === this.session?.session_id) || sessions[0];
      if (next) {
        if (next.stop_generation !== this.session?.stop_generation || next.state !== "stopped") {
          this.frames = []; this.scopes = []; this.variables = [];
        }
        this.session = next;
        if (this.stopped && !this.frames.length) await this.loadStopped();
      } else if (this.session) {
        this.session = null; this.frames = []; this.scopes = []; this.variables = [];
      }
    };
    if (silent) { try { await refresh(); } catch {} }
    else await this.run(refresh);
  },
  async mount() {
    this.cleanup();
    await this.refresh();
    this.timer = setInterval(() => { if (!this.busy) this.refresh(true); }, 2000);
  },
  cleanup() { if (this.timer) clearInterval(this.timer); this.timer = null; },
  async setup() {
    await this.run(async () => {
      this.status = await this.request("setup", { confirm: true });
      toastFrontendSuccess("Pinned language tools and debug adapters are installed.", "Code Intelligence");
    });
  },
  async grant(kind, enabled) {
    await this.run(async () => {
      this.status = await this.request("grant", { kind, enabled, fingerprint: this.status.scope.fingerprint });
      toastFrontendSuccess(enabled ? "Project access saved." : "Project access revoked.", "Code Intelligence");
    });
  },
  async tool(tool, args) { return (await this.request("tool", { tool, args })).result; },
  async inspect(action) {
    await this.run(async () => {
      this.queryKind = action;
      this.queryResult = await this.tool("code_inspect", { action, path: this.path, line: Number(this.line), column: Number(this.column) });
      this.status = await this.request("status");
    });
  },
  async rename() {
    await this.run(async () => {
      await this.tool("code_propose", { action: "rename", path: this.path, line: Number(this.line), column: Number(this.column), new_name: this.newName });
      this.status = await this.request("status"); this.tab = "edits";
    });
  },
  async findActions() {
    await this.run(async () => {
      this.actions = (await this.tool("code_propose", { action: "actions", path: this.path, line: Number(this.line), column: Number(this.column) })).actions;
      this.actionsLoaded = true;
    });
  },
  async propose(action) {
    await this.run(async () => {
      await this.tool("code_propose", { action: "resolve_action", path: this.path, action_id: action.action_id });
      this.status = await this.request("status"); this.tab = "edits";
    });
  },
  async apply(proposal) {
    await this.run(async () => {
      await this.tool("code_apply", { proposal_id: proposal.id });
      this.status = await this.request("status");
      toastFrontendSuccess("Edits applied; diagnostics are refreshing.", "Code Intelligence");
    });
  },
  async openFile(path) {
    await this.run(() => open("editor", { path, ctxid: globalThis.getContext?.() }));
  },
  async launch() {
    await this.run(async () => {
      const lines = this.breakpointLines.split(",").filter(v => v.trim()).map(Number);
      this.session = await this.tool("debug_launch", { target: this.target, breakpoints: lines.length ? [{ path: this.breakpointPath, lines }] : [] });
      this.frames = []; this.scopes = []; this.variables = []; this.output = "";
      if (this.stopped) await this.loadStopped();
    });
  },
  async control(action) {
    await this.run(async () => {
      this.session = await this.tool("debug_control", { action, session_id: this.session.session_id, stop_generation: this.session.stop_generation, wait_seconds: 1 });
      this.frames = []; this.scopes = []; this.variables = [];
      if (this.stopped) await this.loadStopped();
    });
  },
  async debugRequest(action, extra = {}) {
    return await this.tool("debug_inspect", {action, session_id:this.session.session_id, stop_generation:this.session.stop_generation, ...extra});
  },
  async loadStopped() {
    this.frames = (await this.debugRequest("stack")).stackFrames || [];
    if (this.frames.length) await this.selectFrame(this.frames[0], false);
  },
  async selectFrame(frame, guarded = true) {
    const work = async () => {
      this.selectedFrame = frame.id;
      this.scopes = (await this.debugRequest("scopes", {frame_id:frame.id})).scopes || [];
      this.variables = []; this.variableHistory = []; this.selectedScope = null;
      if (this.scopes.length) await this.selectScope(this.scopes[0], false);
    };
    return guarded ? this.run(work) : work();
  },
  async selectScope(scope, guarded = true) {
    const work = async () => {
      this.selectedScope = scope.name; this.variableHistory = [];
      this.variables = (await this.debugRequest("variables", {variables_reference:scope.variablesReference})).variables || [];
    };
    return guarded ? this.run(work) : work();
  },
  async expandVariable(variable) {
    if (!variable.variablesReference) return;
    await this.run(async () => {
      const result = await this.debugRequest("variables", {variables_reference:variable.variablesReference});
      this.variableHistory.push({name:variable.name, values:this.variables});
      this.variables = result.variables || [];
    });
  },
  backVariables() { this.variables = this.variableHistory.pop()?.values || []; },
  async debugRead(action, extra = {}) {
    await this.run(async () => {
      const result = await this.tool("debug_inspect", { action, session_id: this.session.session_id, stop_generation: this.session.stop_generation, ...extra });
      if (action === "stack") this.frames = result.stackFrames;
      if (action === "scopes") { this.scopes = result.scopes; this.variables = []; }
      if (action === "variables") this.variables = result.variables;
      if (action === "output") this.output = result.output;
    });
  },
});
