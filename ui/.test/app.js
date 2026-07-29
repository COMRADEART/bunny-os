// Stage 29/P6: secure Bunny Box browser client and native Bunny Desktop surface.
export const PROTOCOL_VERSION = 3;
export const MAX_MESSAGE_BYTES = 1024 * 1024;
export const MAX_RENDER_BYTES = 200 * 1024;
export const MAX_RENDER_LINES = 600;
export function validateDesktopClientPreferences(value) {
    const defaults = { updateChannel: "beta", automaticUpdateCheck: true, automaticDownload: false, automaticInstall: false, closeBehavior: "ask", launchAtLogin: false, hardwareAcceleration: true, theme: "system", notificationCategories: { approval: false, task: false, job: false, provider: false, sandbox: false, rollback: false, update: true } };
    if (!isRecord(value))
        return defaults;
    const updateChannel = ["nightly", "beta", "stable"].includes(String(value.updateChannel)) ? value.updateChannel : defaults.updateChannel;
    const closeBehavior = ["quit", "minimize-to-tray", "ask"].includes(String(value.closeBehavior)) ? value.closeBehavior : defaults.closeBehavior;
    const theme = ["system", "light", "dark"].includes(String(value.theme)) ? value.theme : defaults.theme;
    const flag = (key) => typeof value[key] === "boolean" ? value[key] : defaults[key];
    const automaticDownload = flag("automaticDownload");
    const rawCategories = isRecord(value.notificationCategories) ? value.notificationCategories : {};
    const notificationCategories = { ...defaults.notificationCategories };
    for (const category of Object.keys(notificationCategories))
        if (typeof rawCategories[category] === "boolean")
            notificationCategories[category] = rawCategories[category];
    return { updateChannel, automaticUpdateCheck: flag("automaticUpdateCheck"), automaticDownload, automaticInstall: automaticDownload && flag("automaticInstall"), closeBehavior, launchAtLogin: flag("launchAtLogin"), hardwareAcceleration: flag("hardwareAcceleration"), theme, notificationCategories };
}
export function desktopHostAvailable() {
    return typeof window !== "undefined" && typeof window.__TAURI__?.core?.invoke === "function";
}
export function safeDesktopSocketUrl(value) {
    try {
        const url = new URL(value);
        if (url.protocol !== "ws:" || url.hostname !== "127.0.0.1" || !url.port || url.pathname !== "/ws" || url.search || url.hash || url.username || url.password)
            return null;
        return url.href;
    }
    catch {
        return null;
    }
}
export function validDesktopBootstrap(value) {
    if (!isRecord(value))
        return false;
    return ["starting", "ready", "restarting", "failed"].includes(String(value.state))
        && typeof value.protocolVersion === "number"
        && typeof value.safeMode === "boolean"
        && typeof value.recoveryMode === "boolean"
        && typeof value.previousCrash === "boolean"
        && Array.isArray(value.degradedComponents)
        && (value.websocketUrl === null || typeof value.websocketUrl === "string")
        && (value.token === null || typeof value.token === "string")
        && (value.error === null || typeof value.error === "string");
}
async function desktopInvoke(command, args) {
    const invoke = window.__TAURI__?.core?.invoke;
    if (!invoke)
        throw new Error("The trusted desktop host is unavailable");
    return await invoke(command, args);
}
async function desktopBridge(command, args = {}) {
    const response = await desktopInvoke("desktop_bridge", { request: { id: crypto.randomUUID(), command, args } });
    if (!response.ok)
        throw new Error(response.error?.message ?? "Desktop command failed");
    return response.result;
}
async function writeClipboard(value) {
    const text = safeClipboardText(value);
    if (desktopHostAvailable())
        await desktopBridge("clipboard.write", { text });
    else
        await navigator.clipboard.writeText(text);
}
async function openExternal(value) {
    const url = safeUrl(value);
    if (!url)
        throw new Error("External URL is not allowed");
    if (desktopHostAvailable())
        await desktopBridge("shell.openExternal", { url });
    else
        window.open(url, "_blank", "noopener,noreferrer");
}
export function tokenFromFragment(fragment) {
    const normalized = fragment.startsWith("#") ? fragment.slice(1) : fragment;
    const token = new URLSearchParams(normalized).get("token");
    return token && token.length <= 512 ? token : null;
}
export function safeUrl(value) {
    try {
        const url = new URL(value, "http://localhost");
        if (url.protocol !== "https:" && url.protocol !== "http:")
            return null;
        if (url.username || url.password)
            return null;
        return url.href;
    }
    catch {
        return null;
    }
}
export function capRenderedText(value, maxBytes = MAX_RENDER_BYTES, maxLines = MAX_RENDER_LINES) {
    const raw = typeof value === "string" ? value : JSON.stringify(value, null, 2) ?? String(value);
    const lines = raw.split(/\r?\n/);
    const lineLimited = lines.length > maxLines ? lines.slice(0, maxLines).join("\n") : raw;
    if (lineLimited.length <= maxBytes)
        return { text: lineLimited, truncated: lines.length > maxLines };
    return { text: lineLimited.slice(0, maxBytes), truncated: true };
}
export function safeClipboardText(value) {
    return capRenderedText(value).text
        .replace(/Bearer\s+[A-Za-z0-9._~+\/-]+/gi, "Bearer [REDACTED]")
        .replace(/(?:sk|nvapi|hf)_[A-Za-z0-9_-]{8,}/g, "[REDACTED]");
}
export function classifyError(value) {
    const record = isRecord(value) ? value : {};
    const code = typeof record.code === "number" ? record.code : undefined;
    const message = typeof record.message === "string" ? record.message : value instanceof Error ? value.message : String(value || "Unknown error");
    const data = isRecord(record.data) ? record.data : {};
    const marker = `${message} ${String(data.code ?? "")}`.toLowerCase();
    let category = "unknown";
    if (code === -32003 || marker.includes("authentic"))
        category = "authentication";
    else if (code === -32040 || marker.includes("permission") || marker.includes("authoriz"))
        category = "authorization";
    else if (code === -32602 || marker.includes("validat") || marker.includes("invalid"))
        category = "validation";
    else if (code === -32001 || marker.includes("conflict") || marker.includes("stale"))
        category = "conflict";
    else if (code === -32010 || marker.includes("protocol"))
        category = "protocol";
    else if (marker.includes("provider") || marker.includes("model endpoint"))
        category = "provider";
    else if (marker.includes("sandbox") || marker.includes("isolation"))
        category = "sandbox";
    else if (marker.includes("plugin") || marker.includes("publisher"))
        category = "plugin";
    else if (marker.includes("database") || marker.includes("storage") || marker.includes("sqlite"))
        category = "storage";
    else if (marker.includes("network") || marker.includes("socket") || marker.includes("unavailable"))
        category = "network";
    return {
        category,
        title: `${category[0].toUpperCase()}${category.slice(1)} error`,
        message: message.replace(/\n+at\s.+/s, ""),
        code,
        correlationId: typeof data.correlationId === "string" ? data.correlationId : undefined,
        retryable: category === "network" || category === "provider" || category === "sandbox" || category === "storage",
    };
}
export function approvalNeedsStrongConfirmation(request) {
    const text = JSON.stringify(request).toLowerCase();
    return request.reversible === false || /irreversible|external|credential|package install|service|destruct|delete|robot|device/.test(text);
}
export function approvalDecisions(persistent) {
    return persistent ? ["allow-once", "allow-turn", "allow-session", "allow-resource", "deny"] : ["allow-once", "deny"];
}
export function canRetryTurn(failed, active, toolCalls) {
    return failed && !active && toolCalls === 0;
}
export function composerWarnings(providerValue, sandboxValue, permissionValue) {
    const warnings = [];
    const providers = extractRecords(providerValue, "providers").filter(isRecord);
    const publicProvider = providers.find((provider) => provider.privacy === "public-cloud");
    if (publicProvider)
        warnings.push(`Cloud privacy boundary: ${String(publicProvider.id ?? "the selected provider")} may receive prompt content after Bunny Core validates the request.`);
    const withoutTools = providers.find((provider) => provider.toolCalls === false || Array.isArray(provider.capabilities) && !provider.capabilities.includes("tools"));
    if (withoutTools)
        warnings.push(`Capability warning: ${String(withoutTools.id ?? "a configured model")} does not support tool calls.`);
    const sandbox = isRecord(sandboxValue) ? sandboxValue : {};
    if (sandbox.secure !== true)
        warnings.push(`Sandbox unavailable or limited: ${String(sandbox.reason ?? "secure isolation was not detected")}. Execution remains subject to Bunny Core's fail-closed policy.`);
    const grants = extractRecords(permissionValue, "grants");
    if (!grants.length)
        warnings.push("No active capability grants are visible. Tools that need effects will request scoped approval.");
    return warnings;
}
export function tokenizeMarkdown(source) {
    const capped = capRenderedText(source);
    const lines = capped.text.replace(/\r/g, "").split("\n");
    const tokens = [];
    let code = null;
    let language = "";
    let paragraph = [];
    const flush = () => {
        if (paragraph.length)
            tokens.push({ kind: "paragraph", text: paragraph.join(" ") });
        paragraph = [];
    };
    for (const line of lines) {
        const fence = line.match(/^```([A-Za-z0-9_+.-]*)\s*$/);
        if (fence) {
            if (code) {
                tokens.push({ kind: "code", text: code.join("\n"), language });
                code = null;
                language = "";
            }
            else {
                flush();
                code = [];
                language = fence[1] ?? "";
            }
            continue;
        }
        if (code) {
            code.push(line);
            continue;
        }
        const heading = line.match(/^(#{1,4})\s+(.+)$/);
        if (heading) {
            flush();
            tokens.push({ kind: "heading", text: heading[2], level: heading[1].length });
            continue;
        }
        const list = line.match(/^\s*[-*+]\s+(.+)$/);
        if (list) {
            flush();
            tokens.push({ kind: "list", text: list[1] });
            continue;
        }
        const quote = line.match(/^>\s?(.+)$/);
        if (quote) {
            flush();
            tokens.push({ kind: "quote", text: quote[1] });
            continue;
        }
        if (!line.trim())
            flush();
        else
            paragraph.push(line.trim());
    }
    flush();
    if (code)
        tokens.push({ kind: "code", text: code.join("\n"), language });
    if (capped.truncated)
        tokens.push({ kind: "quote", text: `Output was capped at ${MAX_RENDER_LINES} lines or ${MAX_RENDER_BYTES} characters for browser safety.` });
    return tokens;
}
export function virtualWindow(items, start, size) {
    const safeStart = Math.max(0, Math.min(Math.floor(start), items.length));
    const safeSize = Math.max(1, Math.floor(size));
    const end = Math.min(items.length, safeStart + safeSize);
    return { items: items.slice(safeStart, end), before: safeStart, after: items.length - end };
}
export class BunnyConnection {
    url;
    socketFactory;
    timerFactory;
    clearTimer;
    stateValue = "disconnected";
    socket = null;
    #token = null;
    requestId = 10;
    reconnectAttempt = 0;
    reconnectTimer = null;
    manualClose = false;
    initialized = false;
    lastSequence = 0;
    pending = new Map();
    listeners = new Set();
    constructor(url, socketFactory = (value) => new WebSocket(value), timerFactory = (callback, delay) => window.setTimeout(callback, delay), clearTimer = (timer) => window.clearTimeout(timer)) {
        this.url = url;
        this.socketFactory = socketFactory;
        this.timerFactory = timerFactory;
        this.clearTimer = clearTimer;
    }
    get state() { return this.stateValue; }
    subscribe(listener) {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }
    connect(token, endpoint) {
        if (!token || token.length > 512) {
            this.fail("Connection token is missing or invalid", "authentication");
            return;
        }
        if (endpoint) {
            const validated = safeDesktopSocketUrl(endpoint);
            if (!validated) {
                this.fail("Desktop app-server endpoint is invalid", "protocol");
                return;
            }
            if (this.socket) {
                this.fail("Cannot replace an active app-server endpoint", "protocol");
                return;
            }
            this.url = validated;
        }
        this.#token = token;
        this.manualClose = false;
        this.open(this.reconnectAttempt > 0 ? "reconnecting" : "connecting");
    }
    disconnect() {
        this.manualClose = true;
        this.#token = null;
        if (this.reconnectTimer !== null)
            this.clearTimer(this.reconnectTimer);
        this.reconnectTimer = null;
        this.rejectPending(classifyError({ message: "Connection closed", code: -32000 }));
        this.socket?.close(1000, "client disconnect");
        this.socket = null;
        this.transition("disconnected");
    }
    async call(method, params = {}, timeoutMs = 30_000) {
        if (this.stateValue !== "connected" && this.stateValue !== "degraded")
            throw classifyError({ message: "App server is not connected" });
        const id = this.requestId++;
        return await new Promise((resolve, reject) => {
            const timer = this.timerFactory(() => {
                this.pending.delete(id);
                reject(classifyError({ message: `${method} timed out`, code: -32000 }));
            }, timeoutMs);
            this.pending.set(id, { resolve, reject, timer });
            this.send({ id, method, params });
        });
    }
    open(state) {
        if (!this.#token || this.socket)
            return;
        this.transition(state);
        let socket;
        try {
            socket = this.socketFactory(this.url);
        }
        catch (error) {
            this.fail(String(error), "network");
            this.scheduleReconnect();
            return;
        }
        this.socket = socket;
        socket.onopen = () => {
            this.transition("authenticating");
            this.send({ id: 1, method: "auth", params: { token: this.#token } });
        };
        socket.onmessage = (event) => this.receive(event.data);
        socket.onerror = () => this.emit({ type: "error", error: classifyError({ message: "WebSocket transport error" }) });
        socket.onclose = () => {
            this.socket = null;
            this.initialized = false;
            this.rejectPending(classifyError({ message: "App server connection closed" }));
            if (!this.manualClose && this.#token && this.stateValue !== "incompatible" && this.stateValue !== "failed")
                this.scheduleReconnect();
            else if (!this.manualClose && this.stateValue !== "incompatible" && this.stateValue !== "failed")
                this.transition("disconnected");
        };
    }
    receive(raw) {
        if (raw.length > MAX_MESSAGE_BYTES) {
            this.fail("Server message exceeds the 1 MiB protocol limit", "protocol");
            this.socket?.close(1009, "message too large");
            return;
        }
        let message;
        try {
            const parsed = JSON.parse(raw);
            if (!isRecord(parsed))
                throw new Error("message must be an object");
            message = parsed;
        }
        catch {
            this.fail("The app server sent malformed protocol data", "protocol");
            return;
        }
        if (message.id === 1 && !this.initialized) {
            if (isRecord(message.error)) {
                this.fail(String(message.error.message ?? "Authentication failed"), "authentication");
                this.socket?.close();
                return;
            }
            const result = isRecord(message.result) ? message.result : {};
            if (result.protocolVersion !== PROTOCOL_VERSION) {
                this.transition("incompatible", `Server protocol ${String(result.protocolVersion)} is not supported`);
                this.socket?.close();
                return;
            }
            this.initialized = true;
            this.send({ id: 2, method: "initialize", params: { protocolVersion: PROTOCOL_VERSION, clientInfo: { name: "Bunny Box", version: "0.1.0" }, capabilities: { richClient: true } } });
            return;
        }
        if (message.id === 2 && this.initialized && this.stateValue === "authenticating") {
            if (isRecord(message.error)) {
                this.fail(String(message.error.message ?? "Protocol negotiation failed"), "protocol");
                return;
            }
            const result = isRecord(message.result) ? message.result : {};
            if (result.protocolVersion !== PROTOCOL_VERSION) {
                this.transition("incompatible", "Protocol negotiation failed");
                return;
            }
            this.reconnectAttempt = 0;
            this.transition("connected");
            return;
        }
        if ((typeof message.id === "number") && this.pending.has(message.id)) {
            const request = this.pending.get(message.id);
            this.pending.delete(message.id);
            this.clearTimer(request.timer);
            if (isRecord(message.error))
                request.reject(classifyError(message.error));
            else
                request.resolve(message.result);
            return;
        }
        if (typeof message.method === "string") {
            const params = isRecord(message.params) ? message.params : {};
            const sequence = typeof params.sequence === "number" ? params.sequence : undefined;
            if (sequence !== undefined) {
                if (sequence <= this.lastSequence)
                    return;
                this.lastSequence = sequence;
            }
            const protocolMessage = message;
            this.emit({ type: message.id !== undefined ? "server-request" : "notification", message: protocolMessage });
        }
    }
    scheduleReconnect() {
        if (this.reconnectTimer !== null || !this.#token)
            return;
        this.reconnectAttempt++;
        this.transition("reconnecting", `Attempt ${this.reconnectAttempt}`);
        const delay = Math.min(15_000, 500 * (2 ** Math.min(this.reconnectAttempt - 1, 5)));
        this.reconnectTimer = this.timerFactory(() => { this.reconnectTimer = null; this.open("reconnecting"); }, delay);
    }
    send(message) {
        if (!this.socket)
            throw classifyError({ message: "WebSocket is unavailable" });
        this.socket.send(JSON.stringify(message));
    }
    transition(state, detail) {
        this.stateValue = state;
        this.emit({ type: "state", state, detail });
    }
    fail(message, category) {
        const error = classifyError({ message });
        error.category = category;
        error.title = `${category[0].toUpperCase()}${category.slice(1)} error`;
        this.transition("failed", message);
        this.emit({ type: "error", error });
    }
    rejectPending(error) {
        for (const request of this.pending.values()) {
            this.clearTimer(request.timer);
            request.reject(error);
        }
        this.pending.clear();
    }
    emit(event) { for (const listener of this.listeners)
        listener(event); }
}
function isRecord(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
function h(tag, attributes = {}, ...children) {
    const element = document.createElement(tag);
    for (const [name, value] of Object.entries(attributes)) {
        if (value === false || value === null || value === undefined)
            continue;
        if (name === "className")
            element.className = String(value);
        else if (name === "text")
            element.textContent = String(value);
        else if (name.startsWith("on") && typeof value === "function")
            element.addEventListener(name.slice(2).toLowerCase(), value);
        else if (name in element && typeof value !== "object")
            element[name] = value;
        else
            element.setAttribute(name, value === true ? "" : String(value));
    }
    for (const child of children) {
        if (typeof child === "string")
            element.append(document.createTextNode(child));
        else if (child)
            element.append(child);
    }
    return element;
}
function inlineText(container, text) {
    const pattern = /(`[^`]+`|\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*)/g;
    let offset = 0;
    for (const match of text.matchAll(pattern)) {
        const index = match.index ?? 0;
        if (index > offset)
            container.append(document.createTextNode(text.slice(offset, index)));
        const token = match[0];
        if (token.startsWith("`"))
            container.append(h("code", { text: token.slice(1, -1) }));
        else if (token.startsWith("**"))
            container.append(h("strong", { text: token.slice(2, -2) }));
        else {
            const parsed = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
            const href = parsed ? safeUrl(parsed[2]) : null;
            if (parsed && href)
                container.append(h("a", { href, target: desktopHostAvailable() ? null : "_blank", rel: "noopener noreferrer", text: parsed[1], onClick: desktopHostAvailable() ? (event) => { event.preventDefault(); void openExternal(href); } : undefined }));
            else
                container.append(document.createTextNode(parsed?.[1] ?? token));
        }
        offset = index + token.length;
    }
    if (offset < text.length)
        container.append(document.createTextNode(text.slice(offset)));
}
function renderMarkdown(source) {
    const fragment = document.createDocumentFragment();
    let list = null;
    for (const token of tokenizeMarkdown(source)) {
        if (token.kind !== "list")
            list = null;
        if (token.kind === "heading") {
            const level = Math.min(4, Math.max(2, token.level ?? 2));
            const heading = document.createElement(`h${level}`);
            inlineText(heading, token.text);
            fragment.append(heading);
        }
        else if (token.kind === "code") {
            const code = h("code", { text: token.text });
            const copy = h("button", { type: "button", className: "copy-code", text: "Copy code", onClick: () => void writeClipboard(token.text) });
            fragment.append(h("div", { className: "code-block" }, h("div", { className: "code-head" }, h("span", { text: token.language || "text" }), copy), h("pre", {}, code)));
        }
        else if (token.kind === "list") {
            if (!list) {
                list = h("ul");
                fragment.append(list);
            }
            const item = h("li");
            inlineText(item, token.text);
            list.append(item);
        }
        else if (token.kind === "quote") {
            const quote = h("blockquote");
            inlineText(quote, token.text);
            fragment.append(quote);
        }
        else {
            const paragraph = h("p");
            inlineText(paragraph, token.text);
            fragment.append(paragraph);
        }
    }
    return fragment;
}
const NAVIGATION = ["Home", "Chat", "Projects", "Plans", "Tasks", "Memory", "Permissions", "Sandboxes", "Checkpoints", "Jobs", "Plugins", "Models", "Providers", "Audit", "Settings", "Diagnostics"];
const PAGE_SPECS = {
    Projects: { method: "system/diagnostics", description: "Inspect the app-server's confined workspace and health context.", unavailable: "Creating, renaming, and browsing arbitrary workspaces requires a trusted native path-selection bridge and is not exposed by protocol v3." },
    Tasks: { method: "task/list", property: "tasks", description: "Server-authoritative tasks, execution policy, retries, artifacts, and state." },
    Memory: { method: "memory/list", property: "memories", description: "Durable memories with provenance, confidence, sensitivity, correction, and deletion." },
    Permissions: { method: "permission/list", property: "grants", description: "Capability grants and their exact owners, scopes, expiry, and revocation state." },
    Sandboxes: { method: "sandbox/list", property: "sandboxes", description: "Isolation backends, owners, policies, resource limits, and lifecycle. Limited isolation is never presented as secure sandboxing." },
    Checkpoints: { method: "checkpoint/list", property: "checkpoints", description: "Evidence-backed checkpoints, diffs, protection, conflict warnings, partial rollback limitations, and bounded recovery." },
    Jobs: { method: "job/list", property: "jobs", description: "Durable unattended jobs with mandatory sandbox and permission profiles.", unavailable: "Protocol v3 supports inspection, pause, resume, and cancellation. Job authoring remains CLI-only until its validated server mutation schema is available." },
    Plugins: { method: "plugin/list", property: "plugins", description: "Signed packages, publisher trust, declared capabilities, grants, and quarantine state." },
    Models: { method: "model/list", property: "models", description: "Verified local model manifests, revisions, storage, licenses, and runtime compatibility.", unavailable: "Pull and runtime start/stop remain CLI-only in protocol v3; Bunny Box exposes verification, repair, pinning, and storage cleanup." },
    Providers: { method: "provider/list", property: "providers", description: "Provider endpoints, credential aliases, capabilities, privacy, failover attempts, and observed limits.", unavailable: "Provider definitions are inspect-only in protocol v3. Credential aliases and provider configuration remain in Bunny's validated CLI configuration flow." },
    Audit: { method: "audit/read", description: "Search and export redacted permission, plugin, credential, and provider-attempt audit records." },
    Diagnostics: { method: "system/diagnostics", description: "Redacted health, protocol, storage, provider, sandbox, model, plugin, and failure diagnostics." },
};
class BunnyBoxApp {
    root;
    connection;
    desktop = desktopHostAvailable();
    desktopBootstrapActive = false;
    desktopState = null;
    page = "Home";
    main;
    details;
    status;
    workspace;
    provider;
    approvalCount;
    mode;
    live;
    nav;
    notices;
    notificationId = 0;
    notifications = [];
    approvals = new Map();
    activeThread = null;
    activeTurn = null;
    streams = new Map();
    toolActivity = new Set();
    lastUserMessage = "";
    lastTurnFailed = false;
    offeredUpdateVersion = null;
    constructor(root) {
        this.root = root;
        const scheme = location.protocol === "https:" ? "wss:" : "ws:";
        this.connection = new BunnyConnection(`${scheme}//${location.host}/ws`);
        this.connection.subscribe((event) => this.onConnectionEvent(event));
    }
    start() {
        this.renderShell();
        if (this.desktop) {
            this.bindDesktopEvents();
            void this.bootstrapDesktop();
            return;
        }
        const token = tokenFromFragment(location.hash);
        if (token) {
            history.replaceState(null, "", `${location.pathname}${location.search}`);
            this.connection.connect(token);
        }
        else
            this.renderPairing();
    }
    bindDesktopEvents() {
        const listen = window.__TAURI__?.event?.listen;
        if (!listen)
            return;
        void listen("desktop-runtime", (event) => {
            if (event.payload.state === "restarting")
                this.connection.disconnect();
            void this.bootstrapDesktop();
        });
        void listen("desktop-tray", (event) => void this.handleDesktopTray(event.payload.action ?? ""));
        void listen("desktop-deep-link", (event) => void this.handleDesktopDeepLink(event.payload));
    }
    async bootstrapDesktop() {
        if (this.desktopBootstrapActive)
            return;
        this.desktopBootstrapActive = true;
        try {
            for (let attempt = 0; attempt < 150; attempt++) {
                const value = await desktopInvoke("desktop_bootstrap");
                if (!validDesktopBootstrap(value))
                    throw new Error("Desktop bootstrap response is malformed");
                this.desktopState = value;
                this.updateDesktopMode(value);
                if (value.state === "ready") {
                    if (value.protocolVersion !== PROTOCOL_VERSION || !value.token || !value.websocketUrl || !safeDesktopSocketUrl(value.websocketUrl)) {
                        throw new Error("Desktop bootstrap did not provide a compatible local app-server session");
                    }
                    this.connection.connect(value.token, value.websocketUrl);
                    return;
                }
                if (value.state === "failed") {
                    this.renderDesktopFailure(value);
                    return;
                }
                this.renderDesktopStartup(value);
                await new Promise((resolve) => window.setTimeout(resolve, 200));
            }
            throw new Error("Bunny Core did not become ready within 30 seconds");
        }
        catch (error) {
            const value = this.desktopState ?? { state: "failed", websocketUrl: null, token: null, protocolVersion: PROTOCOL_VERSION, safeMode: false, recoveryMode: false, previousCrash: false, degradedComponents: ["desktop-host"], error: String(error) };
            this.renderDesktopFailure({ ...value, state: "failed", error: error instanceof Error ? error.message : String(error) });
        }
        finally {
            this.desktopBootstrapActive = false;
        }
    }
    updateDesktopMode(value) {
        const label = value.recoveryMode ? "Recovery mode" : value.safeMode ? "Safe mode" : "Desktop";
        this.mode.textContent = label;
        this.mode.className = `mode-chip ${value.recoveryMode ? "recovery" : value.safeMode ? "safe" : "normal"}`;
    }
    renderDesktopStartup(value) {
        const title = value.state === "restarting" ? "Restarting Bunny Core" : "Starting Bunny securely";
        this.main.replaceChildren(h("section", { className: "desktop-startup", role: "status" }, h("span", { className: "spinner", "aria-hidden": "true" }), h("p", { className: "eyebrow", text: value.recoveryMode ? "Recovery mode" : value.safeMode ? "Safe mode" : "Private local session" }), h("h1", { text: title }), h("p", { text: "The desktop host is launching the bundled app-server on a random loopback port and establishing a short-lived authenticated channel." }), value.previousCrash ? h("p", { className: "capability-note", text: "The previous desktop session did not shut down cleanly. No third-party plugin is trusted automatically during recovery." }) : null));
    }
    renderDesktopFailure(value) {
        const restart = (mode) => void desktopBridge("app.restart", { mode });
        this.main.replaceChildren(h("section", { className: "error-panel", role: "alert" }, h("p", { className: "eyebrow", text: "Desktop recovery" }), h("h1", { text: "Bunny Core could not start" }), h("p", { text: value.error ?? "The bundled app-server is unavailable." }), value.degradedComponents.length ? h("p", { className: "meta", text: `Degraded: ${value.degradedComponents.join(", ")}` }) : null, h("div", { className: "button-row" }, h("button", { type: "button", className: "primary", text: "Restart normally", onClick: () => restart("normal") }), h("button", { type: "button", text: "Open safe mode", onClick: () => restart("safe") }), h("button", { type: "button", text: "Open recovery mode", onClick: () => restart("recovery") }))));
    }
    async handleDesktopTray(action) {
        if (action === "new-chat") {
            await this.openPage("Chat");
            await this.newThread();
        }
        else if (action === "approvals")
            await this.openPage("Permissions");
        else if (action === "diagnostics")
            await this.openPage("Diagnostics");
        else if (action === "update")
            await this.openPage("Settings");
        else if (action === "pause-jobs" || action === "resume-jobs")
            await this.bulkJobAction(action === "pause-jobs" ? "job/pause" : "job/resume");
    }
    async bulkJobAction(method) {
        try {
            const jobs = extractRecords(await this.connection.call("job/list", {}), "jobs").filter(isRecord);
            const eligible = jobs.filter((job) => method === "job/pause" ? ["queued", "running", "retrying"].includes(String(job.status)) : String(job.status) === "paused");
            for (const job of eligible) {
                const jobId = String(job.jobId ?? job.id ?? "");
                if (jobId)
                    await this.connection.call(method, { jobId });
            }
            this.notify("info", method === "job/pause" ? "Jobs paused" : "Jobs resumed", `${eligible.length} validated job operation(s) completed.`);
            await this.openPage("Jobs");
        }
        catch (error) {
            this.notify("error", "Job action failed", classifyError(error).message);
        }
    }
    async handleDesktopDeepLink(route) {
        const kind = String(route.kind ?? "");
        if (kind === "chat-new") {
            await this.openPage("Chat");
            await this.newThread();
        }
        else if (kind === "thread" && typeof route.id === "string") {
            await this.openPage("Chat");
            await this.openThread(route.id);
        }
        else if (kind === "task")
            await this.openPage("Tasks");
        else if (kind === "approval")
            await this.openPage("Permissions");
        else if (kind === "plugin-install" && window.confirm("A deep link requested the plugin installation screen. Continue without installing anything automatically?"))
            await this.openPage("Plugins");
    }
    renderShell() {
        const skip = h("a", { className: "skip-link", href: "#main-content", text: "Skip to content" });
        this.nav = h("nav", { className: "primary-nav", "aria-label": "Primary" });
        this.nav.append(h("div", { className: "brand" }, h("span", { className: "brand-mark", "aria-hidden": "true", text: "B" }), h("span", { text: "Bunny Box" })));
        for (const item of NAVIGATION) {
            const button = h("button", { type: "button", className: item === this.page ? "nav-item active" : "nav-item", "aria-current": item === this.page ? "page" : null, onClick: () => void this.openPage(item) }, h("span", { className: "nav-glyph", "aria-hidden": "true", text: item.slice(0, 1) }), h("span", { text: item }));
            button.dataset.page = item;
            this.nav.append(button);
        }
        this.status = h("span", { className: "status-chip disconnected", text: "Disconnected" });
        this.workspace = h("span", { className: "top-context", text: "Workspace unavailable" });
        this.provider = h("span", { className: "top-context", text: "Provider unavailable" });
        this.approvalCount = h("button", { type: "button", className: "approval-indicator", text: "Approvals 0", onClick: () => void this.openPage("Permissions") });
        this.mode = h("span", { className: "mode-chip", text: this.desktop ? "Desktop" : "Browser" });
        const menu = h("button", { type: "button", className: "mobile-menu", "aria-label": "Toggle navigation", "aria-expanded": "false", onClick: (event) => {
                const expanded = this.nav.classList.toggle("open");
                event.currentTarget.setAttribute("aria-expanded", String(expanded));
            } }, "Menu");
        const palette = h("button", { type: "button", className: "palette-button", "aria-keyshortcuts": "Control+K", onClick: () => this.commandPalette() }, "Search commands", h("kbd", { text: "Ctrl K" }));
        const top = h("header", { className: "top-bar" }, menu, this.status, this.mode, this.workspace, this.provider, palette, this.approvalCount);
        this.main = h("main", { id: "main-content", className: "main-content", tabindex: "-1" });
        this.details = h("aside", { className: "details-panel", "aria-label": "Contextual details" }, h("h2", { text: "Details" }), h("p", { className: "muted", text: "Select an item to inspect server-provided details." }));
        this.notices = h("section", { className: "notifications", "aria-label": "Notifications" });
        this.live = h("div", { className: "sr-only", "aria-live": "polite", "aria-atomic": "true" });
        const layout = h("div", { className: "box-layout" }, this.nav, h("div", { className: "work-area" }, top, h("div", { className: "content-grid" }, this.main, this.details)));
        this.root.replaceChildren(skip, layout, this.notices, this.live);
        document.addEventListener("keydown", (event) => {
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
                event.preventDefault();
                this.commandPalette();
            }
            if (event.key === "Escape")
                this.nav.classList.remove("open");
        });
        this.renderLoading("Connecting to the local app-server");
    }
    renderPairing() {
        const token = h("input", { id: "pair-token", type: "password", autocomplete: "off", spellcheck: "false", required: true });
        const form = h("form", { className: "pair-card", onSubmit: (event) => {
                event.preventDefault();
                const value = token.value.trim();
                token.value = "";
                this.connection.connect(value);
            } }, h("p", { className: "eyebrow", text: "Local pairing" }), h("h1", { text: "Connect Bunny Box" }), h("p", { text: "Paste the short-lived token printed by `bunny app-server --listen-web`. It stays in memory and is never written to browser storage or a URL query." }), h("label", { for: "pair-token", text: "Connection token" }), token, h("button", { type: "submit", className: "primary", text: "Connect securely" }), h("p", { className: "muted", text: "Loopback and same-origin WebSocket connections only. The app server remains the authority for every operation." }));
        this.main.replaceChildren(form);
        queueMicrotask(() => token.focus());
    }
    onConnectionEvent(event) {
        if (event.type === "state") {
            this.status.className = `status-chip ${event.state}`;
            this.status.textContent = event.state.replace(/^./, (letter) => letter.toUpperCase());
            this.live.textContent = `Connection ${event.state}${event.detail ? `: ${event.detail}` : ""}`;
            if (event.state === "connected") {
                this.notify("info", "Connected", "Authenticated app protocol v3 session established.");
                void this.openPage(this.page);
            }
            if (event.state === "incompatible" || event.state === "failed") {
                if (this.desktop && this.desktopState)
                    this.renderDesktopFailure({ ...this.desktopState, state: "failed", error: event.detail ?? event.state });
                else
                    this.renderConnectionFailure(event.detail ?? event.state);
            }
            return;
        }
        if (event.type === "error") {
            this.notify("error", event.error.title, event.error.message);
            return;
        }
        if (event.type === "server-request") {
            this.handleServerRequest(event.message);
            return;
        }
        this.handleNotification(event.message);
    }
    renderConnectionFailure(detail) {
        const retry = h("button", { type: "button", className: "primary", text: "Enter another token", onClick: () => this.renderPairing() });
        this.main.replaceChildren(h("section", { className: "empty-state" }, h("p", { className: "eyebrow", text: "Connection unavailable" }), h("h1", { text: "Bunny Box could not connect" }), h("p", { text: detail }), retry, h("button", { type: "button", text: "Open troubleshooting", onClick: () => void this.openPage("Diagnostics") })));
    }
    async openPage(page) {
        this.page = page;
        for (const button of this.nav.querySelectorAll(".nav-item")) {
            const active = button.dataset.page === page;
            button.classList.toggle("active", active);
            if (active)
                button.setAttribute("aria-current", "page");
            else
                button.removeAttribute("aria-current");
        }
        this.nav.classList.remove("open");
        if (this.connection.state !== "connected" && this.connection.state !== "degraded") {
            if (this.desktop && this.desktopState)
                this.renderDesktopStartup(this.desktopState);
            else
                this.renderPairing();
            return;
        }
        this.renderLoading(`Loading ${page}`);
        try {
            if (page === "Home")
                await this.renderHome();
            else if (page === "Chat")
                await this.renderChat();
            else if (page === "Plans")
                await this.renderPlans();
            else if (page === "Memory")
                await this.renderMemory();
            else if (page === "Settings")
                this.renderSettings();
            else if (page === "Permissions")
                await this.renderPermissions();
            else
                await this.renderResourcePage(page);
            this.main.focus();
        }
        catch (error) {
            this.renderError(classifyError(error), () => void this.openPage(page));
        }
    }
    renderLoading(label) {
        this.main.replaceChildren(h("section", { className: "loading", role: "status" }, h("span", { className: "spinner", "aria-hidden": "true" }), h("p", { text: label })));
    }
    renderError(error, retry) {
        const actions = h("div", { className: "button-row" });
        if (retry && error.retryable)
            actions.append(h("button", { type: "button", className: "primary", text: "Retry safely", onClick: retry }));
        actions.append(h("button", { type: "button", text: "Open diagnostics", onClick: () => void this.openPage("Diagnostics") }));
        this.main.replaceChildren(h("section", { className: "error-panel", role: "alert" }, h("p", { className: "eyebrow", text: error.category }), h("h1", { text: error.title }), h("p", { text: error.message }), error.code !== undefined ? h("p", { className: "meta", text: `Error code ${error.code}${error.correlationId ? ` · correlation ${error.correlationId}` : ""}` }) : null, actions));
    }
    notify(level, title, body) {
        const notification = { id: ++this.notificationId, level, title, body: capRenderedText(body, 500, 5).text, at: new Date() };
        this.notifications = [notification, ...this.notifications].slice(0, 25);
        const close = h("button", { type: "button", className: "notice-close", "aria-label": `Dismiss ${title}`, text: "×" });
        const item = h("article", { className: `notice ${level}`, role: level === "error" ? "alert" : "status" }, h("strong", { text: title }), h("p", { text: notification.body }), close);
        close.addEventListener("click", () => item.remove());
        this.notices.prepend(item);
        window.setTimeout(() => item.remove(), 8_000);
    }
    async renderHome() {
        const calls = [
            ["Runtime health", "system/health", {}], ["Provider", "provider/status", {}], ["Approvals", "approval/list", { limit: 10 }], ["Tasks", "task/list", { limit: 10 }], ["Jobs", "job/list", {}], ["Checkpoints", "checkpoint/list", { limit: 10 }], ["Sandbox", "sandbox/status", {}], ["Model storage", "model/storage", {}], ["Plugins", "plugin/list", {}], ["Models", "model/list", {}],
        ];
        const results = await Promise.all(calls.map(async ([title, method, params]) => ({ title, method, value: await this.connection.call(method, params) })));
        const health = isRecord(results[0]?.value) ? results[0].value : {};
        const provider = isRecord(results[1]?.value) ? results[1].value : {};
        this.workspace.textContent = typeof health.workingDirectory === "string" ? health.workingDirectory : "Current workspace";
        this.provider.textContent = `${String(provider.provider ?? "Provider")} / ${String(provider.model ?? "model unavailable")}`;
        const heading = this.pageHeader("Home", "Live operational state from Bunny Core. No dashboard metric is fabricated by the client.");
        const grid = h("section", { className: "metric-grid", "aria-label": "Runtime overview" });
        for (const result of results)
            grid.append(this.metricCard(result.title, result.value, result.method));
        this.main.replaceChildren(heading, grid, h("section", { className: "boundary-card" }, h("h2", { text: "Trust boundary" }), h("p", { text: "Bunny Box presents server state. Permissions, isolation, credentials, provider admission, durable storage, and rollback decisions stay in Bunny Core." })));
    }
    metricCard(title, value, method) {
        const summary = summarize(value);
        return h("article", { className: "metric-card", tabindex: "0", onClick: () => this.showDetails(title, value) }, h("div", { className: "metric-title", text: title }), h("strong", { className: "metric-value", text: summary.primary }), h("p", { className: "metric-detail", text: summary.secondary }), h("span", { className: "method-label", text: method }));
    }
    async renderResourcePage(page) {
        const spec = PAGE_SPECS[page];
        if (!spec?.method) {
            this.main.replaceChildren(this.pageHeader(page, "This section is not available in the negotiated protocol."));
            return;
        }
        const result = await this.connection.call(spec.method, page === "Permissions" ? { includeExpired: true, includeRevoked: true } : {});
        const records = extractRecords(result, spec.property);
        const content = h("div");
        content.append(this.pageHeader(page, spec.description));
        const toolbar = this.pageActionToolbar(page, result);
        if (toolbar)
            content.append(toolbar);
        if (spec.unavailable)
            content.append(h("aside", { className: "capability-note" }, h("strong", { text: "Capability boundary" }), h("p", { text: spec.unavailable })));
        if (page === "Audit")
            content.append(this.auditToolbar(result));
        if (page === "Diagnostics")
            content.append(this.diagnosticsToolbar(result));
        if (!records.length)
            content.append(this.emptyState(`No ${page.toLowerCase()} were returned by Bunny Core.`));
        else
            content.append(this.recordGrid(page, records));
        this.main.replaceChildren(content);
    }
    pageActionToolbar(page, result) {
        if (page === "Sandboxes")
            return h("div", { className: "toolbar" }, h("p", { className: "muted", text: "New sandboxes require secure isolation by default." }), h("button", { type: "button", className: "primary", text: "Create secure sandbox", onClick: () => void this.mutate("Create sandbox", "sandbox/create", { approved: true }, true) }));
        if (page === "Plugins")
            return h("div", { className: "toolbar" }, h("p", { className: "muted", text: "Inspect signature, publisher, files, and capability changes before installation." }), h("button", { type: "button", className: "primary", text: "Inspect package", onClick: () => this.pluginInspectDialog() }));
        if (page === "Models")
            return h("div", { className: "toolbar" }, h("button", { type: "button", text: "Storage status", onClick: () => void this.connection.call("model/storage", {}).then((value) => this.showDetails("Model storage", value)) }), h("button", { type: "button", text: "Preview cleanup", onClick: () => void this.connection.call("model/clean", { approved: false }).then((value) => this.showDetails("Model cleanup preview", value)) }));
        if (page === "Providers")
            return h("div", { className: "toolbar" }, h("button", { type: "button", text: "Active status", onClick: () => void this.connection.call("provider/status", {}).then((value) => this.showDetails("Active provider", value)) }), h("button", { type: "button", text: "Recent attempts and usage", onClick: () => void this.connection.call("provider/attempts", { limit: 100 }).then((value) => this.showDetails("Provider attempts", value)) }));
        if (page === "Audit")
            return null;
        if (page === "Diagnostics")
            return null;
        if (page === "Projects")
            return h("div", { className: "toolbar" }, h("button", { type: "button", text: "Inspect workspace context", onClick: () => this.showDetails("Workspace context", result) }));
        return null;
    }
    pluginInspectDialog() {
        const dialog = h("dialog", { className: "command-dialog", "aria-labelledby": "plugin-source-title" });
        const source = h("input", { id: "plugin-source", required: true, autocomplete: "off", spellcheck: "false", placeholder: "Trusted local package source" });
        dialog.append(h("form", { onSubmit: (event) => {
                event.preventDefault();
                const selected = source.value.trim();
                void this.connection.call("plugin/inspect", { source: selected }).then((preview) => {
                    dialog.close();
                    this.showDetails("Plugin install preview", preview);
                    if (window.confirm("Review the package preview in the details panel. Continue only if publisher, signature, files, capabilities, and network policy are acceptable."))
                        void this.mutate("Install plugin", "plugin/install", { source: selected, approved: true }, true);
                }).catch((error) => this.notify("error", "Plugin inspection failed", classifyError(error).message));
            } }, h("h2", { id: "plugin-source-title", text: "Inspect plugin package" }), h("p", { text: "Bunny Core resolves and confines the package source. Bunny Box does not read plugin files directly." }), h("label", { for: "plugin-source", text: "Package source" }), source, h("div", { className: "button-row" }, h("button", { type: "submit", className: "primary", text: "Inspect before install" }), h("button", { type: "button", text: "Cancel", onClick: () => dialog.close() }))));
        document.body.append(dialog);
        dialog.addEventListener("close", () => dialog.remove());
        dialog.showModal();
        source.focus();
    }
    async renderMemory(query = "", provenance = "", sensitivity = "") {
        const params = query ? { query, limit: 100, activeOnly: true } : { limit: 100 };
        if (provenance)
            params.provenance = [provenance];
        if (sensitivity)
            params.sensitivities = [sensitivity];
        const result = query || provenance || sensitivity ? await this.connection.call("memory/search", params) : await this.connection.call("memory/list", params);
        const records = extractRecords(result, query || provenance || sensitivity ? "results" : "memories");
        const search = h("input", { id: "memory-query", type: "search", value: query, placeholder: "Search content and provenance" });
        const provenanceSelect = h("select", { id: "memory-provenance" }, h("option", { value: "", text: "All provenance" }), ...["user", "file", "tool", "import", "inference"].map((value) => h("option", { value, selected: value === provenance, text: humanize(value) })));
        const sensitivitySelect = h("select", { id: "memory-sensitivity" }, h("option", { value: "", text: "All sensitivity" }), ...["public", "internal", "sensitive", "restricted"].map((value) => h("option", { value, selected: value === sensitivity, text: humanize(value) })));
        const form = h("form", { className: "memory-filter", onSubmit: (event) => { event.preventDefault(); void this.renderMemory(search.value.trim(), provenanceSelect.value, sensitivitySelect.value); } }, h("label", { for: "memory-query", text: "Search" }, search), h("label", { for: "memory-provenance", text: "Provenance" }, provenanceSelect), h("label", { for: "memory-sensitivity", text: "Sensitivity" }, sensitivitySelect), h("button", { type: "submit", className: "primary", text: "Apply filters" }));
        const content = h("div", {}, this.pageHeader("Memory", PAGE_SPECS.Memory.description), form, h("div", { className: "button-row memory-actions" }, h("button", { type: "button", text: "Statistics", onClick: () => void this.connection.call("memory/stats", {}).then((value) => this.showDetails("Memory statistics", value)) }), h("button", { type: "button", text: "Privacy overview", onClick: () => this.showDetails("Memory privacy", { boundary: "Bunny Core controls user, project, workspace, session, sensitivity, provenance, correction, supersession, expiry, and deletion." }) }), h("button", { type: "button", text: "Export", onClick: async () => downloadJson("bunny-memory.json", await this.connection.call("memory/export", {})) })));
        if (!records.length)
            content.append(this.emptyState("No memories match these server-side filters."));
        else
            content.append(this.memoryGrid(records));
        this.main.replaceChildren(content);
    }
    memoryGrid(records) {
        const grid = this.recordGrid("Memory", records);
        const cards = [...grid.querySelectorAll(".record-card")];
        records.forEach((value, index) => {
            const record = isRecord(value) && isRecord(value.memory) ? value.memory : isRecord(value) ? value : {};
            const id = String(record.id ?? "");
            if (!id || !cards[index])
                return;
            cards[index].append(h("div", { className: "button-row compact" }, h("button", { type: "button", text: "Inspect", onClick: () => void this.connection.call("memory/read", { memoryId: id }).then((result) => this.showDetails("Memory", result)) }), h("button", { type: "button", text: "Correct", onClick: () => this.memoryCorrectionDialog(record) }), h("button", { type: "button", className: "danger", text: "Forget", onClick: () => void this.mutate("Forget memory", "memory/forget", { memoryId: id }, true) })));
        });
        return grid;
    }
    memoryCorrectionDialog(record) {
        const id = String(record.id ?? "");
        const dialog = h("dialog", { className: "command-dialog", "aria-labelledby": "memory-correct-title" });
        const content = h("textarea", { id: "memory-correct-content", required: true, rows: "7", value: String(record.content ?? "") });
        dialog.append(h("form", { onSubmit: (event) => { event.preventDefault(); void this.connection.call("memory/correct", { memoryId: id, content: content.value }).then(() => { dialog.close(); void this.renderMemory(); }).catch((error) => this.notify("error", "Memory correction failed", classifyError(error).message)); } }, h("h2", { id: "memory-correct-title", text: "Correct memory" }), h("p", { text: "Bunny Core preserves provenance and supersession history. This does not overwrite the prior record in place." }), h("label", { for: "memory-correct-content", text: "Corrected content" }), content, h("div", { className: "button-row" }, h("button", { type: "submit", className: "primary", text: "Create correction" }), h("button", { type: "button", text: "Cancel", onClick: () => dialog.close() }))));
        document.body.append(dialog);
        dialog.addEventListener("close", () => dialog.remove());
        dialog.showModal();
        content.focus();
    }
    pageHeader(title, description) {
        return h("header", { className: "page-header" }, h("div", {}, h("p", { className: "eyebrow", text: "Bunny Core" }), h("h1", { text: title }), h("p", { text: description })), h("button", { type: "button", text: "Refresh", onClick: () => void this.openPage(this.page) }));
    }
    recordGrid(page, records) {
        const windowed = virtualWindow(records, 0, 100);
        const grid = h("section", { className: "record-grid", "aria-label": `${page} records` });
        for (const value of windowed.items) {
            const record = isRecord(value) ? value : { value };
            const title = recordTitle(record);
            const actions = this.resourceActions(page, record);
            const definition = h("dl", { className: "record-fields" });
            for (const [key, field] of Object.entries(record).slice(0, 8)) {
                if (isSensitiveKey(key))
                    continue;
                definition.append(h("div", {}, h("dt", { text: humanize(key) }), h("dd", { text: shortValue(field) })));
            }
            grid.append(h("article", { className: "record-card" }, h("button", { type: "button", className: "record-title", text: title, onClick: () => this.showDetails(title, record) }), definition, actions));
        }
        if (windowed.after)
            grid.append(h("p", { className: "capability-note", text: `${windowed.after} additional records are not mounted. Refine server filters or inspect the exported data.` }));
        return grid;
    }
    resourceActions(page, record) {
        const row = h("div", { className: "button-row compact" });
        const id = String(record.id ?? record.jobId ?? record.name ?? record.sessionId ?? record.checkpointId ?? "");
        const action = (label, method, params, strong = false) => row.append(h("button", { type: "button", onClick: () => void this.mutate(label, method, params, strong), text: label }));
        if (page === "Tasks" && id) {
            action("Pause", "task/pause", { taskId: id });
            action("Resume", "task/resume", { taskId: id });
            action("Retry", "task/retry", { taskId: id });
            action("Cancel", "task/cancel", { taskId: id }, true);
        }
        if (page === "Permissions" && id) {
            action("Explain", "permission/explain", { grantId: id });
            action("Revoke", "permission/revoke", { grantId: id }, true);
        }
        if (page === "Sandboxes" && id) {
            action("Inspect", "sandbox/read", { sandboxId: id });
            action("Stop", "sandbox/stop", { sandboxId: id, approved: true }, true);
            action("Destroy", "sandbox/destroy", { sandboxId: id, approved: true }, true);
        }
        if (page === "Checkpoints" && id) {
            action("Diff", "checkpoint/diff", { checkpointId: id });
            action("Protect", "checkpoint/protect", { checkpointId: id, protected: true });
            action("Rollback plan", "rollback/plan", { checkpointId: id }, true);
        }
        if (page === "Jobs" && id) {
            action("Pause", "job/pause", { jobId: id, approved: true });
            action("Resume", "job/resume", { jobId: id, approved: true });
            action("Cancel", "job/cancel", { jobId: id, approved: true }, true);
        }
        if (page === "Plugins" && id) {
            action("Verify", "plugin/verify", { name: id });
            action("Enable", "plugin/enable", { name: id, approved: true });
            action("Disable", "plugin/disable", { name: id, approved: true });
            action("Quarantine", "plugin/quarantine", { name: id, approved: true }, true);
        }
        if (page === "Models" && id) {
            action("Verify", "model/verify", { name: id });
            action("Repair", "model/repair", { name: id, approved: true }, true);
            action(record.pinned === true ? "Unpin" : "Pin", record.pinned === true ? "model/unpin" : "model/pin", { name: id, approved: true });
        }
        return row;
    }
    async mutate(label, method, params, strong = false) {
        if (strong && !window.confirm(`${label} is security-sensitive. Review the selected record and confirm that Bunny Core should validate and execute this request.`))
            return;
        try {
            const result = await this.connection.call(method, params);
            this.notify("info", `${label} accepted`, "Bunny Core validated the request. The current view will refresh.");
            this.showDetails(`${label} result`, result);
            await this.openPage(this.page);
        }
        catch (error) {
            this.notify("error", `${label} failed`, classifyError(error).message);
        }
    }
    showDetails(title, value) {
        const capped = capRenderedText(filterSensitive(value));
        this.details.replaceChildren(h("div", { className: "details-head" }, h("h2", { text: title }), h("button", { type: "button", "aria-label": "Close details", text: "×", onClick: () => this.details.classList.remove("open") })), h("pre", { className: "details-data", text: capped.text }));
        if (capped.truncated)
            this.details.append(h("p", { className: "capability-note", text: "Details were capped for rendering safety." }));
        this.details.classList.add("open");
    }
    emptyState(message) { return h("section", { className: "empty-state" }, h("h2", { text: "Nothing to show" }), h("p", { text: message })); }
    auditToolbar(value) {
        return h("div", { className: "toolbar" }, h("label", { for: "audit-filter", text: "Filter audit records" }), h("input", { id: "audit-filter", type: "search", placeholder: "Actor, capability, provider, result…", onInput: (event) => this.filterCards(event.currentTarget.value) }), h("button", { type: "button", text: "Export redacted JSON", onClick: () => downloadJson("bunny-audit.json", value) }));
    }
    diagnosticsToolbar(value) {
        const toolbar = h("div", { className: "toolbar" }, h("button", { type: "button", text: "Copy redacted report", onClick: () => void writeClipboard(filterSensitive(value)) }), h("button", { type: "button", text: "Export diagnostic package", onClick: () => downloadJson("bunny-support-bundle.json", filterSensitive(value)) }), h("button", { type: "button", text: "Run full doctor", onClick: () => void this.connection.call("system/diagnostics", {}).then((result) => this.showDetails("Full doctor", filterSensitive(result))).catch((error) => this.notify("error", "Doctor failed", classifyError(error).message)) }));
        if (this.desktop)
            toolbar.append(h("button", { type: "button", text: "Build provenance", onClick: () => void desktopBridge("diagnostics.provenance", {}).then((result) => this.showDetails("Build provenance", result)).catch((error) => this.notify("error", "Provenance failed", classifyError(error).message)) }), h("button", { type: "button", text: "Verify installation", onClick: () => void desktopBridge("diagnostics.verifyInstallation", {}).then((result) => this.showDetails("Installation verification", result)).catch((error) => this.notify("error", "Verification failed", classifyError(error).message)) }), h("button", { type: "button", text: "Open log directory", onClick: () => void desktopBridge("diagnostics.openLogs", {}).catch((error) => this.notify("error", "Open logs failed", classifyError(error).message)) }), h("button", { type: "button", text: "Safe mode", onClick: () => void desktopBridge("app.restart", { mode: "safe" }) }), h("button", { type: "button", text: "Recovery mode", onClick: () => void desktopBridge("app.restart", { mode: "recovery" }) }));
        return toolbar;
    }
    filterCards(query) {
        const needle = query.toLowerCase().trim();
        for (const card of this.main.querySelectorAll(".record-card"))
            card.hidden = Boolean(needle) && !card.textContent?.toLowerCase().includes(needle);
    }
    commandPalette() {
        const dialog = h("dialog", { className: "command-dialog", "aria-labelledby": "command-title" });
        const input = h("input", { type: "search", placeholder: "Go to a Bunny Box page", "aria-label": "Search commands" });
        const list = h("div", { className: "command-list", role: "listbox" });
        const render = () => {
            list.replaceChildren();
            const needle = input.value.toLowerCase();
            for (const page of NAVIGATION.filter((item) => item.toLowerCase().includes(needle)))
                list.append(h("button", { type: "button", role: "option", text: `Open ${page}`, onClick: () => { dialog.close(); void this.openPage(page); } }));
        };
        input.addEventListener("input", render);
        dialog.append(h("form", { method: "dialog" }, h("div", { className: "dialog-head" }, h("h2", { id: "command-title", text: "Command palette" }), h("button", { type: "submit", "aria-label": "Close", text: "×" })), input, list));
        document.body.append(dialog);
        dialog.addEventListener("close", () => dialog.remove());
        render();
        dialog.showModal();
        input.focus();
    }
    handleServerRequest(message) {
        if (message.id === undefined || !isRecord(message.params))
            return;
        if (message.method === "item/tool/requestApproval") {
            this.approvals.set(message.id, { id: message.id, params: message.params });
            this.updateApprovalCount();
            this.notify("warning", "Approval required", "A tool is waiting for a scoped permission decision.");
            this.nativeNotification("approval", "Bunny approval required", "A scoped permission decision is waiting.", "bunny://approval/pending");
            if (this.page === "Permissions")
                void this.renderPermissions();
        }
        else if (message.method === "item/userInput/request")
            this.userInputDialog(message.id, String(message.params.prompt ?? "The agent needs input."));
    }
    handleNotification(message) {
        const params = isRecord(message.params) ? message.params : {};
        if (message.method === "item/reasoning/delta")
            return;
        if (message.method === "turn/started") {
            const turn = isRecord(params.turn) ? params.turn : {};
            this.activeTurn = typeof turn.id === "string" ? turn.id : null;
            this.lastTurnFailed = false;
            this.live.textContent = "Assistant response is streaming";
        }
        else if (message.method === "turn/completed") {
            const turn = isRecord(params.turn) ? params.turn : {};
            this.lastTurnFailed = turn.status === "failed" || turn.status === "interrupted";
            this.activeTurn = null;
            this.live.textContent = `Assistant turn ${String(turn.status ?? "completed")}`;
            if (this.page === "Chat")
                this.updateComposerState();
            if (this.lastTurnFailed)
                this.notify("error", "Turn incomplete", `The turn ended as ${String(turn.status ?? "failed")}.`);
        }
        else if (message.method === "item/started" || message.method === "item/completed" || message.method === "item/agentMessage/delta" || message.method === "item/toolCall/delta") {
            if (this.page === "Chat")
                this.renderChatEvent(message);
        }
        else if (message.method === "checkpoint/progress" || message.method === "rollback/progress" || message.method === "undo/progress") {
            this.notify("info", humanize(message.method), shortValue(params));
            if (message.method === "rollback/progress" && params.status === "completed")
                this.nativeNotification("rollback", "Bunny rollback completed", "A local rollback completed. Open Bunny to review the result.");
        }
        else if (message.method === "error")
            this.notify("error", "Core error", String(params.message ?? "Unknown server error"));
    }
    updateApprovalCount() {
        this.approvalCount.textContent = `Approvals ${this.approvals.size}`;
        this.approvalCount.classList.toggle("pending", this.approvals.size > 0);
    }
    async renderPermissions() {
        const result = await this.connection.call("permission/list", { includeExpired: true, includeRevoked: true });
        const grants = extractRecords(result, "grants");
        const content = h("div");
        content.append(this.pageHeader("Permissions", PAGE_SPECS.Permissions.description));
        content.append(h("section", { className: "approval-center", "aria-labelledby": "approval-heading" }, h("div", { className: "section-heading" }, h("div", {}, h("p", { className: "eyebrow", text: "Live queue" }), h("h2", { id: "approval-heading", text: `Pending approvals (${this.approvals.size})` }))), this.approvals.size ? this.approvalCards() : this.emptyState("No tools are waiting for approval.")));
        content.append(h("section", { "aria-labelledby": "grant-heading" }, h("h2", { id: "grant-heading", text: "Capability grants" }), grants.length ? this.recordGrid("Permissions", grants) : this.emptyState("No grants were returned.")));
        content.append(h("button", { type: "button", text: "Export permissions", onClick: async () => downloadJson("bunny-permissions.json", await this.connection.call("permission/export", {})) }));
        this.main.replaceChildren(content);
    }
    approvalCards() {
        const list = h("div", { className: "approval-list" });
        for (const approval of this.approvals.values()) {
            const request = isRecord(approval.params.request) ? approval.params.request : {};
            const strong = approvalNeedsStrongConfirmation(request);
            const card = h("article", { className: strong ? "approval-card high-risk" : "approval-card" }, h("div", {}, h("p", { className: "eyebrow", text: strong ? "Strong confirmation required" : "Scoped permission" }), h("h3", { text: String(request.title ?? request.tool ?? "Tool request") }), h("p", { text: String(request.reason ?? "The agent requested a capability for this operation.") })), this.fieldList(request));
            const labels = { "allow-once": "Allow once", "allow-turn": "Allow for this turn", "allow-session": "Allow for this session", "allow-resource": "Allow exact resource", deny: "Deny" };
            const choices = approvalDecisions(request.persistent !== false).map((decision) => [labels[decision], decision]);
            const actions = h("div", { className: "button-row" });
            for (const [label, decision] of choices)
                actions.append(h("button", { type: "button", className: decision === "deny" ? "danger" : "", text: label, onClick: () => void this.answerApproval(approval.id, decision, strong && decision !== "deny") }));
            card.append(actions);
            list.append(card);
        }
        return list;
    }
    async answerApproval(id, decision, strong) {
        if (strong && !window.confirm("This request may be irreversible, external, destructive, credential-related, or device-affecting. Confirm only after reviewing scope, sandbox, affected resources, and reversibility."))
            return;
        try {
            await this.connection.call("approval/respond", { requestId: id, decision });
            this.approvals.delete(id);
            this.updateApprovalCount();
            await this.renderPermissions();
        }
        catch (error) {
            this.notify("error", "Approval response failed", classifyError(error).message);
        }
    }
    fieldList(record) {
        const list = h("dl", { className: "record-fields full" });
        for (const [key, value] of Object.entries(record)) {
            if (isSensitiveKey(key) || typeof value === "object" && value !== null && JSON.stringify(value).length > 2_000)
                continue;
            list.append(h("div", {}, h("dt", { text: humanize(key) }), h("dd", { text: shortValue(value) })));
        }
        return list;
    }
    userInputDialog(id, prompt) {
        const dialog = h("dialog", { className: "command-dialog", "aria-labelledby": "question-title" });
        const answer = h("textarea", { id: "question-answer", rows: "4" });
        dialog.append(h("form", { onSubmit: (event) => { event.preventDefault(); void this.connection.call("user-input/respond", { requestId: id, answer: answer.value }).then(() => dialog.close()); } }, h("h2", { id: "question-title", text: "Agent question" }), h("p", { text: prompt }), h("label", { for: "question-answer", text: "Your answer" }), answer, h("div", { className: "button-row" }, h("button", { type: "submit", className: "primary", text: "Respond" }), h("button", { type: "button", text: "Cancel", onClick: () => dialog.close() }))));
        document.body.append(dialog);
        dialog.addEventListener("close", () => dialog.remove());
        dialog.showModal();
        answer.focus();
    }
    async renderPlans() {
        const [intentsResult, plansResult] = await Promise.all([this.connection.call("intent/list", { limit: 100 }), this.connection.call("plan/list", { latestOnly: false, limit: 100 })]);
        const intents = extractRecords(intentsResult, "intents");
        const plans = extractRecords(plansResult, "plans");
        const content = h("div");
        content.append(this.pageHeader("Plans", "Original intents, versioned living plans, dependencies, blockers, approvals, cost, artifacts, and transition history."));
        content.append(h("section", {}, h("div", { className: "section-heading" }, h("h2", { text: "Intents" }), h("button", { type: "button", text: "Create intent", onClick: () => this.createIntentDialog() })), intents.length ? this.intentGrid(intents) : this.emptyState("No intents have been created.")));
        content.append(h("section", {}, h("h2", { text: "Versioned plans" }), plans.length ? this.planGrid(plans) : this.emptyState("No plans have been created for these intents.")));
        this.main.replaceChildren(content);
    }
    intentGrid(records) {
        const grid = this.recordGrid("Plans", records);
        const cards = [...grid.querySelectorAll(".record-card")];
        records.forEach((value, index) => {
            const record = isRecord(value) ? value : {};
            const id = String(record.id ?? "");
            if (!id || !cards[index])
                return;
            cards[index].append(h("div", { className: "button-row compact" }, h("button", { type: "button", text: "Pause", onClick: () => void this.mutate("Pause intent", "intent/pause", { intentId: id }) }), h("button", { type: "button", text: "Resume", onClick: () => void this.mutate("Resume intent", "intent/resume", { intentId: id }) }), h("button", { type: "button", text: "Cancel", onClick: () => void this.mutate("Cancel intent", "intent/cancel", { intentId: id }, true) })));
        });
        return grid;
    }
    planGrid(records) {
        const grid = this.recordGrid("Plans", records);
        const cards = [...grid.querySelectorAll(".record-card")];
        records.forEach((value, index) => {
            const record = isRecord(value) ? value : {};
            const id = String(record.id ?? "");
            if (!id || !cards[index])
                return;
            cards[index].append(h("div", { className: "button-row compact" }, h("button", { type: "button", text: "Approve", onClick: () => void this.mutate("Approve plan", "plan/approve", { planId: id, approved: true }, true) }), h("button", { type: "button", text: "Pause", onClick: () => void this.mutate("Pause plan", "plan/pause", { planId: id }) }), h("button", { type: "button", text: "Resume", onClick: () => void this.mutate("Resume plan", "plan/resume", { planId: id }) }), h("button", { type: "button", text: "Compare versions", onClick: () => this.showDetails("Plan version", record) })));
        });
        return grid;
    }
    createIntentDialog() {
        const dialog = h("dialog", { className: "command-dialog", "aria-labelledby": "intent-title" });
        const title = h("input", { id: "intent-name", required: true, maxlength: "200" });
        const request = h("textarea", { id: "intent-request", required: true, rows: "4" });
        const objective = h("textarea", { id: "intent-objective", required: true, rows: "4" });
        dialog.append(h("form", { onSubmit: (event) => { event.preventDefault(); void this.connection.call("intent/create", { title: title.value, originalRequest: request.value, interpretedObjective: objective.value, constraints: [], expectedDeliverables: [], completionCriteria: [], priority: "normal" }).then(() => { dialog.close(); void this.renderPlans(); }).catch((error) => this.notify("error", "Intent creation failed", classifyError(error).message)); } }, h("h2", { id: "intent-title", text: "Create intent" }), h("label", { for: "intent-name", text: "Title" }), title, h("label", { for: "intent-request", text: "Original request" }), request, h("label", { for: "intent-objective", text: "Interpreted objective" }), objective, h("div", { className: "button-row" }, h("button", { type: "submit", className: "primary", text: "Create through Bunny Core" }), h("button", { type: "button", text: "Cancel", onClick: () => dialog.close() }))));
        document.body.append(dialog);
        dialog.addEventListener("close", () => dialog.remove());
        dialog.showModal();
        title.focus();
    }
    renderSettings() {
        const sections = ["General", "Appearance", "Providers", "Models", "Permissions", "Privacy", "Memory", "Jobs", "Plugins", "Storage", "Advanced"];
        const cards = h("section", { className: "record-grid" });
        for (const section of sections)
            cards.append(h("article", { className: "record-card" }, h("h2", { text: section }), h("p", { text: settingDescription(section) }), section === "Appearance" ? h("button", { type: "button", text: "Toggle contrast theme", onClick: () => document.documentElement.classList.toggle("light") }) : h("span", { className: "method-label", text: "Server-managed" })));
        const content = h("div", {}, this.pageHeader("Settings", "Safe client preferences and links to validated server-managed configuration. Bunny Box never writes arbitrary configuration files."));
        if (this.desktop)
            content.append(this.desktopSettingsPanel());
        content.append(cards, h("aside", { className: "capability-note" }, h("strong", { text: "Configuration boundary" }), h("p", { text: "Provider credentials remain credential aliases. Provider, model, permission, memory, job, plugin, and storage changes use their authoritative service pages or the Bunny CLI when protocol v3 has no mutation." })));
        this.main.replaceChildren(content);
    }
    desktopSettingsPanel() {
        const preferences = this.loadDesktopPreferences();
        const panel = h("section", { className: "desktop-settings", "aria-labelledby": "desktop-settings-title" }, h("div", { className: "section-heading" }, h("div", {}, h("p", { className: "eyebrow", text: "Native host" }), h("h2", { id: "desktop-settings-title", text: "Bunny Desktop" }))));
        const form = h("div", { className: "settings-grid" });
        const select = (label, key, values) => {
            const input = h("select", { value: preferences[key], onChange: (event) => { preferences[key] = event.currentTarget.value; this.saveDesktopPreferences(preferences); } });
            for (const value of values)
                input.append(h("option", { value, text: humanize(String(value)) }));
            return h("label", { className: "setting-control" }, h("span", { text: label }), input);
        };
        const toggle = (label, key) => h("label", { className: "setting-toggle" }, h("input", { type: "checkbox", checked: preferences[key], onChange: (event) => { preferences[key] = event.currentTarget.checked; if (key === "automaticDownload" && !preferences[key])
                preferences.automaticInstall = false; if (key === "automaticInstall" && preferences[key])
                preferences.automaticDownload = true; this.saveDesktopPreferences(preferences); this.renderSettings(); } }), h("span", { text: label }));
        const notificationToggle = (category) => h("label", { className: "setting-toggle" }, h("input", { type: "checkbox", checked: preferences.notificationCategories[category], onChange: (event) => { preferences.notificationCategories[category] = event.currentTarget.checked; this.saveDesktopPreferences(preferences); } }), h("span", { text: `${humanize(category)} notifications (redacted)` }));
        form.append(select("Update channel", "updateChannel", ["nightly", "beta", "stable"]), select("Close behavior", "closeBehavior", ["ask", "minimize-to-tray", "quit"]), select("Theme", "theme", ["system", "light", "dark"]), toggle("Check automatically for updates", "automaticUpdateCheck"), toggle("Download verified updates automatically", "automaticDownload"), toggle("Install updates automatically after download", "automaticInstall"), toggle("Launch at sign-in", "launchAtLogin"), toggle("Use hardware acceleration after restart", "hardwareAcceleration"));
        for (const category of ["approval", "task", "job", "provider", "sandbox", "rollback", "update"])
            form.append(notificationToggle(category));
        const actions = h("div", { className: "button-row" }, h("button", { type: "button", text: "Choose workspace", onClick: () => void this.chooseDesktopWorkspace() }), h("button", { type: "button", text: "Test notification", onClick: () => void this.testDesktopNotification() }), h("button", { type: "button", className: "primary", text: "Check for updates", onClick: () => void this.checkDesktopUpdate() }), h("button", { type: "button", text: "Install offered update", disabled: !this.offeredUpdateVersion, onClick: () => void this.installDesktopUpdate() }));
        const recovery = h("div", { className: "button-row compact" }, h("button", { type: "button", text: "Restart normally", onClick: () => void desktopBridge("app.restart", { mode: "normal" }) }), h("button", { type: "button", text: "Restart in safe mode", onClick: () => void desktopBridge("app.restart", { mode: "safe" }) }), h("button", { type: "button", text: "Restart in recovery mode", onClick: () => void desktopBridge("app.restart", { mode: "recovery" }) }));
        panel.append(form, actions, recovery, h("p", { className: "muted", text: "Desktop preferences contain no credentials. Native operations remain schema-validated, rate-limited, and auditable; selected paths do not grant filesystem authority." }));
        return panel;
    }
    loadDesktopPreferences() {
        try {
            return validateDesktopClientPreferences(JSON.parse(localStorage.getItem("bunny.desktop.preferences") ?? "null"));
        }
        catch {
            return validateDesktopClientPreferences(null);
        }
    }
    saveDesktopPreferences(value) {
        localStorage.setItem("bunny.desktop.preferences", JSON.stringify(validateDesktopClientPreferences(value)));
        document.documentElement.classList.toggle("light", value.theme === "light");
    }
    async chooseDesktopWorkspace() {
        try {
            const result = await desktopBridge("dialog.open", { purpose: "workspace.open" });
            this.showDetails("Selected workspace", result);
            this.notify("info", "Workspace selected", "The canonical path was returned without granting filesystem permission.");
        }
        catch (error) {
            this.notify("error", "Workspace selection failed", classifyError(error).message);
        }
    }
    async testDesktopNotification() {
        try {
            await desktopBridge("notification.show", { category: "update", title: "Bunny Desktop", body: "Native notifications are enabled for this local workspace." });
        }
        catch (error) {
            this.notify("error", "Notification failed", classifyError(error).message);
        }
    }
    nativeNotification(category, title, body, route) {
        if (!this.desktop || !this.loadDesktopPreferences().notificationCategories[category])
            return;
        const args = { category, title, body };
        if (route)
            args.route = route;
        void desktopBridge("notification.show", args).catch(() => undefined);
    }
    async checkDesktopUpdate() {
        try {
            const result = await desktopBridge("update.check", {});
            const record = isRecord(result) ? result : {};
            this.offeredUpdateVersion = record.available === true && typeof record.version === "string" ? record.version : null;
            this.showDetails("Update check", record);
            this.notify("info", this.offeredUpdateVersion ? "Update offered" : "Bunny is up to date", this.offeredUpdateVersion ? `Version ${this.offeredUpdateVersion} is available; its artifact signature is verified before installation.` : "No update was offered by the configured channel feed.");
            this.renderSettings();
        }
        catch (error) {
            this.notify("error", "Update check failed", classifyError(error).message);
        }
    }
    async installDesktopUpdate() {
        if (!this.offeredUpdateVersion || !window.confirm(`Install the verified Bunny Desktop ${this.offeredUpdateVersion} update and restart when ready?`))
            return;
        try {
            this.showDetails("Update installation", await desktopBridge("update.install", { version: this.offeredUpdateVersion }));
        }
        catch (error) {
            this.notify("error", "Update installation failed", classifyError(error).message);
        }
    }
    async renderChat() {
        const result = await this.connection.call("thread/list", { includeArchived: true });
        const threads = extractRecords(result, "threads");
        const sidebar = h("aside", { className: "thread-list", "aria-label": "Conversations" }, h("div", { className: "section-heading" }, h("h2", { text: "Threads" }), h("button", { type: "button", text: "New", onClick: () => void this.newThread() })));
        if (!threads.length)
            sidebar.append(h("p", { className: "muted", text: "No saved threads." }));
        for (const value of threads) {
            const thread = isRecord(value) ? value : {};
            const id = String(thread.threadId ?? thread.sessionId ?? thread.id ?? "");
            const button = h("button", { type: "button", className: id === this.activeThread ? "thread-button active" : "thread-button", onClick: () => void this.openThread(id) }, h("strong", { text: String(thread.name ?? `Thread ${id.slice(0, 8)}`) }), h("span", { text: `${String(thread.messageCount ?? 0)} messages · ${String(thread.location ?? "active")}` }));
            sidebar.append(button);
        }
        const log = h("section", { id: "chat-log", className: "chat-log", "aria-label": "Conversation", "aria-live": "off" });
        const composer = this.composer();
        const chat = h("div", { className: "chat-layout" }, sidebar, h("div", { className: "chat-work" }, h("header", { className: "chat-head" }, h("div", {}, h("p", { className: "eyebrow", text: "Authenticated local session" }), h("h1", { text: this.activeThread ? `Chat ${this.activeThread.slice(0, 8)}` : "Chat" })), h("div", { className: "button-row compact" }, h("button", { type: "button", text: "Fork", disabled: !this.activeThread, onClick: () => void this.threadMutation("thread/fork") }), h("button", { type: "button", text: "Archive", disabled: !this.activeThread, onClick: () => void this.threadMutation("thread/archive") }), h("button", { type: "button", text: "Delete", className: "danger", disabled: !this.activeThread, onClick: () => void this.threadMutation("thread/delete", true) }))), log, composer));
        this.main.replaceChildren(chat);
        if (!this.activeThread && threads[0]) {
            const first = isRecord(threads[0]) ? threads[0] : {};
            const id = String(first.sessionId ?? first.id ?? "");
            if (id)
                await this.openThread(id);
        }
        else if (this.activeThread)
            await this.loadThread(this.activeThread);
        await this.updateComposerWarnings();
        this.updateComposerState();
    }
    async updateComposerWarnings() {
        const target = this.main.querySelector("#composer-warnings");
        if (!target)
            return;
        try {
            const [providers, sandbox, permissions] = await Promise.all([
                this.connection.call("provider/list", {}),
                this.connection.call("sandbox/status", {}),
                this.connection.call("permission/list", {}),
            ]);
            const warnings = composerWarnings(providers, sandbox, permissions);
            target.replaceChildren(...warnings.map((warning) => h("p", { text: warning })));
            target.hidden = warnings.length === 0;
        }
        catch (error) {
            target.hidden = false;
            target.replaceChildren(h("p", { text: `Preflight status unavailable: ${classifyError(error).message}` }));
        }
    }
    composer() {
        const text = h("textarea", { id: "composer-input", rows: "4", placeholder: "Ask Bunny… Enter sends, Shift+Enter adds a line", "aria-label": "Message", onInput: () => this.saveDraft(text.value), onKeydown: (event) => { if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void this.sendMessage();
            } } });
        const draft = this.loadDraft();
        if (draft)
            text.value = draft;
        const send = h("button", { id: "composer-send", type: "button", className: "primary", text: "Send", onClick: () => void this.sendMessage() });
        const stop = h("button", { id: "composer-stop", type: "button", text: "Cancel turn", onClick: () => void this.interruptTurn() });
        const retry = h("button", { id: "composer-retry", type: "button", text: "Retry safely", onClick: () => void this.retryTurn() });
        const context = h("div", { className: "composer-context" }, h("span", { className: "privacy-chip", text: "Privacy boundary: server-selected provider" }), h("span", { text: "Attachments: workspace references only in protocol v3" }));
        const providerSelect = h("label", {}, h("span", { className: "sr-only", text: "Provider selection" }), h("select", { disabled: true, "aria-label": "Provider selection" }, h("option", { text: "Server active provider" })));
        const modelSelect = h("label", {}, h("span", { className: "sr-only", text: "Model selection" }), h("select", { disabled: true, "aria-label": "Model selection" }, h("option", { text: "Server active model" })));
        const actions = h("div", { className: "composer-actions" }, providerSelect, modelSelect, retry, stop, send);
        return h("footer", { className: "composer" }, h("div", { id: "composer-warnings", className: "composer-warnings", role: "status", "aria-live": "polite" }), context, text, actions);
    }
    async newThread() {
        try {
            const result = await this.connection.call("thread/start", {});
            const thread = isRecord(result) && isRecord(result.thread) ? result.thread : {};
            this.activeThread = String(thread.threadId ?? thread.id ?? thread.sessionId ?? "");
            await this.renderChat();
        }
        catch (error) {
            this.notify("error", "Thread creation failed", classifyError(error).message);
        }
    }
    async openThread(id) {
        if (this.activeTurn) {
            this.notify("warning", "Turn still active", "Interrupt or wait for the active turn before switching threads.");
            return;
        }
        try {
            await this.connection.call("thread/resume", { threadId: id });
            this.activeThread = id;
            await this.renderChat();
        }
        catch (error) {
            this.notify("error", "Thread open failed", classifyError(error).message);
        }
    }
    async loadThread(id) {
        const result = await this.connection.call("thread/read", { threadId: id });
        const thread = isRecord(result) && isRecord(result.thread) ? result.thread : {};
        const messages = Array.isArray(thread.messages) ? thread.messages : [];
        const log = this.main.querySelector("#chat-log");
        if (!log)
            return;
        log.replaceChildren();
        const windowed = virtualWindow(messages, Math.max(0, messages.length - 200), 200);
        if (windowed.before)
            log.append(h("p", { className: "virtual-note", text: `${windowed.before} older messages are not mounted. Use server-side thread export for the complete record.` }));
        for (const value of windowed.items) {
            const message = isRecord(value) ? value : {};
            const role = String(message.role ?? "system");
            const text = messageText(message.content);
            log.append(this.messageCard(role, text));
            if (role === "user")
                this.lastUserMessage = text;
        }
        log.scrollTop = log.scrollHeight;
    }
    messageCard(role, text) {
        const safeRole = role === "assistant" || role === "user" || role === "tool" || role === "system" ? role : "status";
        const body = h("div", { className: "message-body" });
        if (safeRole === "assistant")
            body.append(renderMarkdown(text));
        else
            body.textContent = capRenderedText(text).text;
        const copy = h("button", { type: "button", className: "copy-message", text: "Copy", onClick: () => void writeClipboard(text) });
        return h("article", { className: `message ${safeRole}` }, h("header", {}, h("strong", { text: humanize(safeRole) }), copy), body);
    }
    async sendMessage() {
        const input = this.main.querySelector("#composer-input");
        if (!input || !this.activeThread || this.activeTurn)
            return;
        const text = input.value.trim();
        if (!text)
            return;
        if (text.length > 100_000) {
            this.notify("warning", "Message too large", "Composer text is capped at 100,000 characters. Split the request before sending.");
            return;
        }
        this.lastUserMessage = text;
        this.toolActivity.clear();
        this.lastTurnFailed = false;
        input.value = "";
        this.saveDraft("");
        try {
            const result = await this.connection.call("turn/start", { threadId: this.activeThread, input: text });
            const turn = isRecord(result) && isRecord(result.turn) ? result.turn : {};
            this.activeTurn = typeof turn.id === "string" ? turn.id : null;
            this.updateComposerState();
        }
        catch (error) {
            input.value = text;
            this.saveDraft(text);
            this.notify("error", "Message was not sent", classifyError(error).message);
        }
    }
    async interruptTurn() {
        if (!this.activeThread || !this.activeTurn)
            return;
        try {
            await this.connection.call("turn/interrupt", { threadId: this.activeThread, turnId: this.activeTurn });
        }
        catch (error) {
            this.notify("error", "Interrupt failed", classifyError(error).message);
        }
    }
    async retryTurn() {
        if (!this.lastTurnFailed || !this.lastUserMessage || this.activeTurn)
            return;
        if (this.toolActivity.size) {
            this.notify("warning", "Retry blocked", "This turn invoked tools. Start a new message after inspecting execution records to avoid duplicate side effects.");
            return;
        }
        const input = this.main.querySelector("#composer-input");
        if (input) {
            input.value = this.lastUserMessage;
            await this.sendMessage();
        }
    }
    updateComposerState() {
        const send = this.main.querySelector("#composer-send");
        const stop = this.main.querySelector("#composer-stop");
        const retry = this.main.querySelector("#composer-retry");
        const input = this.main.querySelector("#composer-input");
        if (send)
            send.disabled = !this.activeThread || Boolean(this.activeTurn);
        if (stop)
            stop.disabled = !this.activeTurn;
        if (retry)
            retry.disabled = !canRetryTurn(this.lastTurnFailed, Boolean(this.activeTurn), this.toolActivity.size);
        if (input)
            input.disabled = !this.activeThread || Boolean(this.activeTurn);
    }
    renderChatEvent(message) {
        const log = this.main.querySelector("#chat-log");
        if (!log || !isRecord(message.params))
            return;
        const params = message.params;
        if (params.threadId && this.activeThread && params.threadId !== this.activeThread)
            return;
        if (message.method === "item/started" && isRecord(params.item)) {
            const item = params.item;
            const id = String(item.id ?? "");
            const type = String(item.type ?? "status");
            if (type === "reasoning")
                return;
            const role = type === "agentMessage" ? "assistant" : type === "userMessage" ? "user" : type === "toolCall" ? "tool" : "status";
            const card = this.messageCard(role, messageText(item.content ?? item.text ?? (role === "tool" ? `Tool ${String(item.name ?? "unknown")} queued` : "")));
            card.dataset.itemId = id;
            if (role === "tool") {
                this.toolActivity.add(id);
                card.classList.add("tool-timeline");
            }
            log.append(card);
            this.streams.set(id, card.querySelector(".message-body"));
            log.scrollTop = log.scrollHeight;
        }
        else if ((message.method === "item/agentMessage/delta" || message.method === "item/toolCall/delta") && typeof params.itemId === "string") {
            const target = this.streams.get(params.itemId);
            if (target)
                target.textContent = capRenderedText(`${target.textContent ?? ""}${String(params.delta ?? "")}`).text;
        }
        else if (message.method === "item/completed" && isRecord(params.item)) {
            const item = params.item;
            const id = String(item.id ?? "");
            const target = this.streams.get(id);
            if (target && item.type === "agentMessage")
                target.replaceChildren(renderMarkdown(String(item.text ?? target.textContent ?? "")));
            if (target && item.type === "toolCall") {
                target.replaceChildren(h("details", {}, h("summary", { text: `${String(item.name ?? "Tool")} · ${String(item.status ?? "completed")}` }), this.fieldList(item), h("div", { className: "tool-actions" }, h("button", { type: "button", text: "Inspect provider attempt", onClick: () => void this.inspectProviderAttempts() }), h("button", { type: "button", text: "Open executions", onClick: () => void this.openPage("Tasks") }))));
            }
            this.streams.delete(id);
        }
    }
    async inspectProviderAttempts() {
        try {
            this.showDetails("Provider attempts", await this.connection.call("provider/attempts", { turnId: this.activeTurn ?? undefined, limit: 25 }));
        }
        catch (error) {
            this.notify("error", "Provider attempts unavailable", classifyError(error).message);
        }
    }
    async threadMutation(method, strong = false) {
        if (!this.activeThread)
            return;
        if (strong && !window.confirm("Delete moves this recoverable thread to Bunny's trash. Confirm the selected thread."))
            return;
        try {
            const result = await this.connection.call(method, { threadId: this.activeThread });
            const thread = isRecord(result) && isRecord(result.thread) ? result.thread : {};
            this.activeThread = method === "thread/fork" ? String(thread.threadId ?? thread.id ?? thread.sessionId ?? "") : null;
            await this.renderChat();
        }
        catch (error) {
            this.notify("error", `${humanize(method)} failed`, classifyError(error).message);
        }
    }
    saveDraft(value) {
        try {
            const key = `bunny.box.draft.${this.activeThread ?? "new"}`;
            if (value)
                localStorage.setItem(key, value.slice(0, 100_000));
            else
                localStorage.removeItem(key);
        }
        catch {
            this.notify("warning", "Draft storage unavailable", "The unsent draft remains in this page only.");
        }
    }
    loadDraft() {
        try {
            return localStorage.getItem(`bunny.box.draft.${this.activeThread ?? "new"}`) ?? "";
        }
        catch {
            return "";
        }
    }
}
function extractRecords(value, property) {
    if (property && isRecord(value) && Array.isArray(value[property]))
        return value[property];
    if (Array.isArray(value))
        return value;
    if (!isRecord(value))
        return [];
    for (const candidate of Object.values(value))
        if (Array.isArray(candidate))
            return candidate;
    return [value];
}
function recordTitle(record) {
    return String(record.title ?? record.name ?? record.model ?? record.id ?? record.sessionId ?? record.jobId ?? record.checkpointId ?? "Record");
}
function humanize(value) {
    return value.replace(/[\/_-]+/g, " ").replace(/([a-z])([A-Z])/g, "$1 $2").replace(/^./, (letter) => letter.toUpperCase());
}
function shortValue(value) {
    if (value === null || value === undefined)
        return "Not set";
    if (typeof value === "boolean")
        return value ? "Yes" : "No";
    if (typeof value === "object")
        return capRenderedText(value, 500, 5).text.replace(/\s+/g, " ");
    return String(value).slice(0, 500);
}
function summarize(value) {
    if (!isRecord(value))
        return { primary: shortValue(value), secondary: "Server response" };
    if (typeof value.ok === "boolean")
        return { primary: value.ok ? "Healthy" : "Degraded", secondary: shortValue(value.runtime ?? value.database ?? value) };
    for (const [key, candidate] of Object.entries(value))
        if (Array.isArray(candidate))
            return { primary: String(candidate.length), secondary: humanize(key) };
    const first = Object.entries(value).find(([key]) => !isSensitiveKey(key));
    return { primary: first ? shortValue(first[1]) : "Available", secondary: first ? humanize(first[0]) : "Server response" };
}
function messageText(value) {
    if (typeof value === "string")
        return value;
    if (Array.isArray(value))
        return value.map((block) => isRecord(block) && typeof block.text === "string" ? block.text : "").filter(Boolean).join("\n");
    if (isRecord(value) && typeof value.text === "string")
        return value.text;
    return shortValue(value);
}
function isSensitiveKey(key) { return /token|secret|password|authorization|cookie|api[_-]?key/i.test(key); }
function filterSensitive(value, key = "") {
    if (isSensitiveKey(key))
        return "[REDACTED]";
    if (Array.isArray(value))
        return value.map((item) => filterSensitive(item, key));
    if (!isRecord(value))
        return value;
    return Object.fromEntries(Object.entries(value).map(([childKey, child]) => [childKey, filterSensitive(child, childKey)]));
}
function downloadJson(name, value) {
    const blob = new Blob([JSON.stringify(filterSensitive(value), null, 2) + "\n"], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = h("a", { href: url, download: name });
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
}
function settingDescription(section) {
    const descriptions = {
        General: "Connection and local application behavior.", Appearance: "Contrast and presentation preferences stored without secrets.", Providers: "Credential-alias-only provider configuration through validated Core workflows.", Models: "Local manifest verification, licenses, runtime, and storage.", Permissions: "Capability grant defaults and revocation workflows.", Privacy: "Local/cloud boundaries, diagnostic redaction, and attachment disclosure.", Memory: "Retention, provenance, sensitivity, import, export, and deletion.", Jobs: "Unattended isolation, permission profile, network, runtime, cost, and retry policy.", Plugins: "Publisher trust, signatures, quarantine, capabilities, and grants.", Storage: "Database, checkpoints, local models, quotas, and cleanup previews.", Advanced: "Protocol diagnostics and explicit experimental capabilities.",
    };
    return descriptions[section] ?? "Server-managed setting.";
}
if (typeof document !== "undefined") {
    const root = document.getElementById("app");
    if (root)
        new BunnyBoxApp(root).start();
}
