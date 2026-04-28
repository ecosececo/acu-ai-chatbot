/**
 * ACU AI Chatbot — Frontend JavaScript
 *
 * Handles:
 * - Chat messaging with streaming (SSE)
 * - Conversation management
 * - UI state (sidebar, theme, etc.)
 * - Markdown rendering
 */

// ── State ───────────────────────────────────────────────
let currentConversationId = null;
let isGenerating = false;
let abortController = null;
let webSearchEnabled = localStorage.getItem("acu-web-search") === "true";

// ── DOM Elements ────────────────────────────────────────
const chatForm = document.getElementById("chatForm");
const questionInput = document.getElementById("questionInput");
const sendBtn = document.getElementById("sendBtn");
const stopBtn = document.getElementById("stopBtn");
const messagesContainer = document.getElementById("messages");
const chatContainer = document.querySelector("main .flex-1.overflow-y-auto");
const welcomeScreen = document.getElementById("welcomeScreen");
const conversationList = document.getElementById("conversationList");
const topbarTitles = document.querySelectorAll("[data-topbar-title]");
const charCount = document.getElementById("charCount");
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const sidebar = document.getElementById("sidebar");
const sidebarToggle = document.querySelectorAll("#sidebarToggle");
const sidebarClose = document.getElementById("sidebarClose");
const newChatBtn = document.getElementById("newChatBtn");
const themeToggle = document.querySelectorAll("#themeToggle");
const statusBtn = document.getElementById("statusBtn");

function setTopbarTitle(text) {
    if (!topbarTitles || topbarTitles.length === 0) return;
    topbarTitles.forEach((el) => {
        el.textContent = text;
    });
}

// ── CSRF Token ──────────────────────────────────────────
function getCsrfToken() {
    const cookie = document.cookie
        .split("; ")
        .find((row) => row.startsWith("csrftoken="));
    return cookie ? cookie.split("=")[1] : "";
}

// ── Configure Marked ────────────────────────────────────
if (typeof marked !== "undefined") {
    marked.setOptions({
        breaks: true,
        gfm: true,
        highlight: function (code, lang) {
            if (typeof hljs !== "undefined" && lang && hljs.getLanguage(lang)) {
                return hljs.highlight(code, { language: lang }).value;
            }
            return code;
        },
    });
}

// ── Initialize ──────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    loadConversations();
    checkSystemStatus();
    initTheme();
    initWebSearchToggle();
    autoResizeTextarea();

    // Check status every 30 seconds
    setInterval(checkSystemStatus, 30000);
});

// ── Theme Management ────────────────────────────────────
function initTheme() {
    const saved = localStorage.getItem("acu-theme");
    if (saved === "light") {
        document.documentElement.classList.remove("dark");
    }
}

themeToggle.forEach((btn) => {
    btn.addEventListener("click", () => {
        const isDark = document.documentElement.classList.contains("dark");
        if (isDark) {
            document.documentElement.classList.remove("dark");
            localStorage.setItem("acu-theme", "light");
        } else {
            document.documentElement.classList.add("dark");
            localStorage.setItem("acu-theme", "dark");
        }
    });
});

// ── Sidebar Toggle ──────────────────────────────────────
sidebarToggle.forEach((btn) => {
    btn.addEventListener("click", () => {
        if (sidebar.classList.contains("-translate-x-full")) {
            sidebar.classList.remove("-translate-x-full");
        } else {
            sidebar.classList.add("-translate-x-full");
        }
    });
});

if (sidebarClose) {
    sidebarClose.addEventListener("click", () => {
        sidebar.classList.add("-translate-x-full");
    });
}

// ── Web Search Toggle ───────────────────────────────────
function initWebSearchToggle() {
    // Web search toggle removed from new UI
    // webSearchEnabled is still tracked in localStorage for API calls
}

// ── Textarea Auto-resize ────────────────────────────────
function autoResizeTextarea() {
    questionInput.addEventListener("input", () => {
        questionInput.style.height = "auto";
        questionInput.style.height = Math.min(questionInput.scrollHeight, 150) + "px";
        if (charCount) charCount.textContent = `${questionInput.value.length} / 2000`;
    });
}

// ── Form Submit ─────────────────────────────────────────
chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const question = questionInput.value.trim();
    if (!question || isGenerating) return;
    sendMessage(question);
});

// Handle Enter key (submit) and Shift+Enter (new line)
questionInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        chatForm.dispatchEvent(new Event("submit"));
    }
});

// ── Suggestion Cards ────────────────────────────────────
document.querySelectorAll(".suggestion-card").forEach((card) => {
    card.addEventListener("click", () => {
        const question = card.getAttribute("data-question");
        questionInput.value = question;
        sendMessage(question);
    });
});

// ── New Chat ────────────────────────────────────────────
newChatBtn.addEventListener("click", () => {
    currentConversationId = null;
    messagesContainer.innerHTML = "";
    messagesContainer.classList.add("hidden");
    welcomeScreen.classList.remove("hidden");
    setTopbarTitle("Yeni Sohbet");
    sidebar.classList.add("-translate-x-full");

    // Remove active class from conversations
    document.querySelectorAll(".conversation-item").forEach((el) => {
        el.classList.remove("bg-primary-container/30", "border", "border-primary/30");
    });
});

// ── Send Message ────────────────────────────────────────
async function sendMessage(question) {
    // Hide welcome screen
    welcomeScreen.classList.add("hidden");
    messagesContainer.classList.remove("hidden");

    // Show user message
    appendMessage("user", question);

    // Clear input
    questionInput.value = "";
    questionInput.style.height = "auto";
    if (charCount) charCount.textContent = "0 / 2000";

    // UI state
    setGenerating(true);

    // Show typing indicator
    const typingEl = showTypingIndicator();

    try {
        abortController = new AbortController();

        const response = await fetch("/api/chat/", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCsrfToken(),
            },
            body: JSON.stringify({
                question: question,
                conversation_id: currentConversationId,
                stream: true,
                web_search: webSearchEnabled,
            }),
            signal: abortController.signal,
        });

        if (!response.ok) {
            typingEl.remove();
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP ${response.status}`);
        }

        // Check if streaming response
        const contentType = response.headers.get("content-type");
        if (contentType && contentType.includes("text/event-stream")) {
            await handleStreamResponse(response, typingEl);
        } else {
            typingEl.remove();
            const data = await response.json();
            handleRegularResponse(data);
        }
    } catch (error) {
        typingEl.remove();

        if (error.name === "AbortError") {
            appendMessage("assistant", "_Yanıt oluşturma durduruldu._");
        } else {
            appendErrorMessage(
                error.message || "Bir hata oluştu. Lütfen tekrar deneyin."
            );
        }
    } finally {
        setGenerating(false);
        abortController = null;
        loadConversations();
    }
}

// ── Handle Stream Response ──────────────────────────────
async function handleStreamResponse(response, typingEl) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let fullResponse = "";
    let sources = [];
    let messageEl = null;
    let buffer = "";

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
            if (!line.startsWith("data: ")) continue;

            try {
                const data = JSON.parse(line.substring(6));

                if (data.type === "conversation") {
                    currentConversationId = data.conversation_id;
                    setTopbarTitle(data.title || "Yeni Sohbet");
                    upsertConversationListItem({
                        id: data.conversation_id,
                        title: data.title || "Yeni Sohbet",
                    });
                } else if (data.type === "sources") {
                    sources = data.sources || [];
                } else if (data.type === "content") {
                    if (typingEl) {
                        typingEl.remove();
                        typingEl = null;
                    }
                    fullResponse += data.content;
                    if (!messageEl) {
                        messageEl = appendMessage("assistant", "", sources, true);
                    }
                    updateMessageContent(messageEl, fullResponse);
                } else if (data.type === "done") {
                    currentConversationId = data.conversation_id;
                    if (typingEl) {
                        typingEl.remove();
                        typingEl = null;
                    }
                    if (messageEl) {
                        finishMessage(messageEl, fullResponse, sources, data.response_time_ms);
                    }
                }
            } catch (e) {
                // Skip malformed JSON
            }
        }
    }

    if (typingEl) {
        typingEl.remove();
        typingEl = null;
    }

    // If no message element was created, show what we have
    if (!messageEl && fullResponse) {
        appendMessage("assistant", fullResponse, sources);
    }
}

// ── Handle Regular (non-stream) Response ────────────────
function handleRegularResponse(data) {
    currentConversationId = data.conversation_id;
    appendMessage("assistant", data.answer, data.sources, false, data.response_time_ms);
    setTopbarTitle(data.answer.substring(0, 60) + "...");
}

// ── Stop Generation ─────────────────────────────────────
stopBtn.addEventListener("click", () => {
    if (abortController) {
        abortController.abort();
    }
});

// ── UI Helpers ──────────────────────────────────────────
function setGenerating(state) {
    isGenerating = state;
    sendBtn.classList.toggle("hidden", state);
    stopBtn.classList.toggle("hidden", !state);
    sendBtn.disabled = state;
    questionInput.disabled = state;
}

function showTypingIndicator() {
    const el = document.createElement("div");
    el.className = "flex gap-4 mb-4 animate-pulse";
    el.innerHTML = `
        <div class="text-2xl">🎓</div>
        <div class="flex-1">
            <div class="flex gap-2 h-8 items-center">
                <div class="w-2 h-2 bg-primary rounded-full animate-bounce" style="animation-delay: 0s"></div>
                <div class="w-2 h-2 bg-primary rounded-full animate-bounce" style="animation-delay: 0.2s"></div>
                <div class="w-2 h-2 bg-primary rounded-full animate-bounce" style="animation-delay: 0.4s"></div>
            </div>
        </div>
    `;
    messagesContainer.appendChild(el);
    scrollToBottom();
    return el;
}

function appendMessage(role, content, sources = [], isStreaming = false, responseTimeMs = null) {
    const el = document.createElement("div");
    el.className = `flex gap-4 mb-4 ${role === "user" ? "justify-end" : "justify-start"}`;

    const avatar = role === "user" ? "👤" : "🎓";
    const name = role === "user" ? "Sen" : "ACU Asistan";
    const time = new Date().toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });

    const renderedContent = role === "assistant" ? renderMarkdown(content) : escapeHtml(content);

    const contentClass = role === "user"
        ? "bg-primary/20 border border-primary/30 text-on-surface rounded-2xl rounded-tr-sm"
        : "bg-surface-container-high/60 border border-outline-variant/30 text-on-surface rounded-2xl rounded-tl-sm";

    el.innerHTML = `
        <div class="${role === "user" ? "order-2" : "order-1"} text-2xl flex-shrink-0">${avatar}</div>
        <div class="${role === "user" ? "order-1" : "order-2"} flex-1 max-w-2xl">
            <div class="${contentClass} p-4 message-content">
                <div class="flex justify-between items-start gap-3 mb-2">
                    <span class="font-label-md text-label-md text-on-surface-variant">${name}</span>
                    <span class="font-label-sm text-label-sm text-on-surface-variant">${time}</span>
                </div>
                <div class="message-body text-body-md text-body-md">${renderedContent}</div>
                ${role === "assistant" && sources.length > 0 ? renderSources(sources) : ""}
                ${role === "assistant" && responseTimeMs ? `<div class="text-label-sm text-label-sm text-on-surface-variant mt-2">⏱️ ${(responseTimeMs / 1000).toFixed(1)}s</div>` : ""}
            </div>
        </div>
    `;

    messagesContainer.appendChild(el);
    scrollToBottom();
    return el;
}

function updateMessageContent(messageEl, content) {
    const bodyEl = messageEl.querySelector(".message-body");
    if (bodyEl) {
        bodyEl.innerHTML = renderMarkdown(content);
        scrollToBottom();
    }
}

function finishMessage(messageEl, content, sources, responseTimeMs) {
    const bodyEl = messageEl.querySelector(".message-body");
    if (bodyEl) {
        bodyEl.innerHTML = renderMarkdown(content);
    }

    // Add sources
    const contentEl = messageEl.querySelector(".message-content");
    if (sources && sources.length > 0) {
        const existingSources = contentEl.querySelector(".message-sources");
        if (!existingSources) {
            contentEl.insertAdjacentHTML("beforeend", renderSources(sources));
        }
    }

    // Add response time
    if (responseTimeMs) {
        contentEl.insertAdjacentHTML(
            "beforeend",
            `<div class="text-label-sm text-label-sm text-on-surface-variant mt-2">⏱️ ${(responseTimeMs / 1000).toFixed(1)}s</div>`
        );
    }

    // Highlight code blocks
    messageEl.querySelectorAll("pre code").forEach((block) => {
        if (typeof hljs !== "undefined") {
            hljs.highlightElement(block);
        }
    });

    scrollToBottom();
}

function appendErrorMessage(message) {
    const el = document.createElement("div");
    el.className = "flex gap-4 mb-4";
    el.innerHTML = `
        <div class="text-2xl">⚠️</div>
        <div class="flex-1">
            <div class="bg-error/20 border border-error/30 p-4 rounded-2xl rounded-tl-sm">
                <div class="text-body-md text-body-md text-error">${escapeHtml(message)}</div>
            </div>
        </div>
    `;
    messagesContainer.appendChild(el);
    scrollToBottom();
}

function renderSources(sources) {
    if (!sources || sources.length === 0) return "";

    const items = sources
        .map(
            (s) => `
        <div class="text-body-sm text-body-sm text-on-surface-variant flex items-center gap-2">
            📄 <a href="${escapeHtml(s.url)}" target="_blank" title="${escapeHtml(s.title)}" class="text-primary hover:text-primary-container underline truncate">${escapeHtml(s.title || s.url)}</a>
            ${s.score ? `<span class="text-label-sm text-label-sm">(${(s.score * 100).toFixed(0)}%)</span>` : ""}
        </div>`
        )
        .join("");

    return `
        <details class="mt-3 message-sources">
            <summary class="text-label-md text-label-md text-primary cursor-pointer hover:text-primary-container">📚 Kaynaklar (${sources.length})</summary>
            <div class="mt-2 space-y-1 pl-4 border-l border-outline-variant">${items}</div>
        </details>
    `;
}

function renderMarkdown(text) {
    if (!text) return "";
    if (typeof marked !== "undefined") {
        return marked.parse(text);
    }
    return escapeHtml(text).replace(/\n/g, "<br>");
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function scrollToBottom() {
    requestAnimationFrame(() => {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    });
}

// ── Conversations ───────────────────────────────────────
async function loadConversations() {
    try {
        const response = await fetch("/api/conversations/");
        if (!response.ok) return;

        const conversations = await response.json();
        renderConversationList(conversations);
    } catch (error) {
        console.warn("Failed to load conversations:", error);
    }
}

function renderConversationList(conversations) {
    conversationList.innerHTML = "";

    if (conversations.length === 0) {
        conversationList.innerHTML = `
            <div class="text-center text-on-surface-variant text-body-sm py-8">
                Henüz sohbet yok
            </div>
        `;
        return;
    }

    conversations.forEach((conv) => {
        const el = document.createElement("button");
        el.className = `conversation-item w-full text-left px-3 py-2 rounded-lg transition-all hover:bg-white/10 ${
            conv.id === currentConversationId ? "bg-primary-container/30 border border-primary/30" : "hover:border border-transparent"
        }`;
        el.dataset.id = conv.id;
        el.innerHTML = `
            <div class="flex items-center justify-between gap-2">
                <div class="flex items-center gap-2 flex-1 min-w-0">
                    <span class="text-xl flex-shrink-0">💬</span>
                    <span class="conv-title text-body-sm text-on-surface truncate">${escapeHtml(conv.title || "Başlıksız Sohbet")}</span>
                </div>
                <button type="button" class="conv-delete p-1 text-on-surface-variant hover:text-error flex-shrink-0" title="Sil" data-id="${conv.id}">
                    <span class="material-symbols-outlined text-lg">delete</span>
                </button>
            </div>
        `;

        el.addEventListener("click", (e) => {
            if (e.target.closest(".conv-delete")) return;
            loadConversation(conv.id);
            sidebar.classList.add("-translate-x-full");
        });

        el.querySelector(".conv-delete").addEventListener("click", (e) => {
            e.stopPropagation();
            e.preventDefault();
            deleteConversation(conv.id);
        });

        conversationList.appendChild(el);
    });
}

function upsertConversationListItem(conv) {
    if (!conv || !conv.id) return;

    const emptyState = conversationList.querySelector("[data-empty-state]");
    if (emptyState) emptyState.remove();

    let el = conversationList.querySelector(`.conversation-item[data-id="${conv.id}"]`);
    if (!el) {
        el = document.createElement("button");
        el.className = "conversation-item w-full text-left px-3 py-2 rounded-lg transition-all hover:bg-white/10";
        el.dataset.id = conv.id;
        el.type = "button";
        el.innerHTML = `
            <div class="flex items-center justify-between gap-2">
                <div class="flex items-center gap-2 flex-1 min-w-0">
                    <span class="text-xl flex-shrink-0">💬</span>
                    <span class="conv-title text-body-sm text-on-surface truncate"></span>
                </div>
                <button type="button" class="conv-delete p-1 text-on-surface-variant hover:text-error flex-shrink-0" title="Sil" data-id="${conv.id}">
                    <span class="material-symbols-outlined text-lg">delete</span>
                </button>
            </div>
        `;
        el.addEventListener("click", (e) => {
            if (e.target.closest(".conv-delete")) return;
            loadConversation(conv.id);
            sidebar.classList.add("-translate-x-full");
        });
        el.querySelector(".conv-delete").addEventListener("click", (e) => {
            e.stopPropagation();
            e.preventDefault();
            deleteConversation(conv.id);
        });
        conversationList.prepend(el);
    }

    el.querySelector(".conv-title").textContent = conv.title || "Yeni Sohbet";
    document.querySelectorAll(".conversation-item").forEach((item) => {
        if (item.dataset.id === conv.id) {
            item.classList.add("bg-primary-container/30", "border", "border-primary/30");
        } else {
            item.classList.remove("bg-primary-container/30", "border", "border-primary/30");
        }
    });
}

async function loadConversation(conversationId) {
    try {
        const response = await fetch(`/api/conversations/${conversationId}/`);
        if (!response.ok) return;

        const data = await response.json();

        currentConversationId = data.id;
        setTopbarTitle(data.title || "Sohbet");
        welcomeScreen.classList.add("hidden");
        messagesContainer.classList.remove("hidden");
        messagesContainer.innerHTML = "";

        // Render messages
        (data.messages || []).forEach((msg) => {
            if (msg.role === "user") {
                appendMessage("user", msg.content || "");
            } else if (msg.role === "assistant") {
                let sources = msg.sources || [];
                if (sources.length > 0 && typeof sources[0] === "string") {
                    sources = sources.map(url => ({ url, title: url }));
                }
                appendMessage("assistant", msg.content || "", sources, false, msg.response_time_ms);
            }
        });

        // Update active state in sidebar
        document.querySelectorAll(".conversation-item").forEach((el) => {
            el.classList.remove("bg-primary-container/30", "border", "border-primary/30");
        });
        const activeItem = document.querySelector(`[data-id="${conversationId}"]`);
        if (activeItem) {
            activeItem.classList.add("bg-primary-container/30", "border", "border-primary/30");
        }
    } catch (error) {
        console.error("Failed to load conversation:", error);
    }
}

async function deleteConversation(conversationId) {
    if (!confirm("Bu sohbeti silmek istediğinize emin misiniz?")) return;

    try {
        await fetch(`/api/conversations/${conversationId}/delete/`, {
            method: "DELETE",
            headers: { "X-CSRFToken": getCsrfToken() },
        });

        if (currentConversationId === conversationId) {
            currentConversationId = null;
            messagesContainer.innerHTML = "";
            messagesContainer.classList.add("hidden");
            welcomeScreen.classList.remove("hidden");
            setTopbarTitle("Yeni Sohbet");
        }

        loadConversations();
    } catch (error) {
        console.error("Failed to delete conversation:", error);
    }
}

// ── System Status ───────────────────────────────────────
async function checkSystemStatus() {
    try {
        const response = await fetch("/api/health/");
        if (!response.ok) throw new Error();

        const data = await response.json();

        if (data.llm_available) {
            statusDot.className = "w-3 h-3 rounded-full bg-green-500";
            statusDot.removeAttribute("class");
            statusDot.className = "w-3 h-3 rounded-full bg-green-500";
            statusText.textContent = `Çevrimiçi — ${data.model}`;
            statusBtn.classList.remove("opacity-50");
        } else {
            statusDot.className = "w-3 h-3 rounded-full bg-yellow-500 animate-pulse";
            statusText.textContent = "Model yükleniyor...";
            statusBtn.classList.add("opacity-50");
        }
    } catch (error) {
        statusDot.className = "w-3 h-3 rounded-full bg-red-500";
        statusText.textContent = "Bağlantı hatası";
        statusBtn.classList.add("opacity-50");
    }
}
// Touch event optimization - OmerV7
