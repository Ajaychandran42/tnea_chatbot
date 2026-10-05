// ── Helper: sanitize text for safe innerHTML injection ────────────────
function sanitizeHTML(str) {
    const div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

function sanitizeRenderedMarkdown(html) {
    const template = document.createElement("template");
    template.innerHTML = html;
    template.content.querySelectorAll("script,style,iframe,object,embed,form,link,meta").forEach(el => el.remove());
    template.content.querySelectorAll("*").forEach(el => {
        [...el.attributes].forEach(attr => {
            const name=attr.name.toLowerCase(), value=attr.value.trim().toLowerCase();
            if (name.startsWith("on") || ((name === "href" || name === "src") && value.startsWith("javascript:"))) el.removeAttribute(attr.name);
        });
    });
    return template.innerHTML;
}

document.addEventListener("DOMContentLoaded", () => {
    const chatContainer = document.getElementById("chatContainer");
    const userInput = document.getElementById("userInput");
    const sendBtn = document.getElementById("sendBtn");
    const micBtn = document.getElementById("micBtn");
    const toast = document.getElementById("toast");

    let chatHistory = [];
    let currentSessionId = null;
    let isGenerating = false;
    const SESSION_KEY = "tnea_chat_sessions_v2";
    const MAX_SAVED_SESSIONS = 20;

    function loadSessions() {
        try {
            const raw = localStorage.getItem(SESSION_KEY);
            const parsed = raw ? JSON.parse(raw) : [];
            return Array.isArray(parsed) ? parsed : [];
        } catch (_) {
            return [];
        }
    }

    function saveSessions(sessions) {
        try {
            localStorage.setItem(SESSION_KEY, JSON.stringify(sessions.slice(0, MAX_SAVED_SESSIONS)));
        } catch (_) {}
    }

    function sessionTitle(messages) {
        const first = messages.find(m => m.role === "user");
        const text = first?.content || "New counselling chat";
        return text.length > 34 ? text.slice(0, 34).trimEnd() + "…" : text;
    }

    function renderSessionList() {
        const list = document.getElementById("sessionList");
        if (!list) return;
        const sessions = loadSessions();
        list.innerHTML = "";
        if (!sessions.length) {
            list.innerHTML = '<div class="session-empty">Your recent chats will appear here.</div>';
            return;
        }
        sessions.sort((a,b) => (b.updatedAt || 0) - (a.updatedAt || 0)).forEach(session => {
            const row = document.createElement("button");
            row.type = "button";
            row.className = "session-item" + (session.id === currentSessionId ? " active" : "");
            row.title = session.title;
            row.innerHTML = '<i class="fa-regular fa-message"></i><span></span>';
            row.querySelector("span").textContent = session.title;
            row.addEventListener("click", () => restoreSession(session.id));
            list.appendChild(row);
        });
    }

    function persistCurrentSession() {
        if (!chatHistory.length) return;
        const sessions = loadSessions();
        const existing = sessions.find(s => s.id === currentSessionId);
        const session = existing || {
            id: currentSessionId || (crypto.randomUUID ? crypto.randomUUID() : String(Date.now())),
            createdAt: Date.now()
        };
        currentSessionId = session.id;
        session.title = sessionTitle(chatHistory);
        session.messages = chatHistory.slice(-MAX_CHAT_HISTORY);
        session.updatedAt = Date.now();
        const filtered = sessions.filter(s => s.id !== session.id);
        saveSessions([session, ...filtered]);
        renderSessionList();
    }

    function restoreSession(id) {
        if (isGenerating) return;
        const session = loadSessions().find(s => s.id === id);
        if (!session) return;
        currentSessionId = session.id;
        chatHistory = Array.isArray(session.messages) ? session.messages.slice(-MAX_CHAT_HISTORY) : [];
        Array.from(chatContainer.children).forEach(child => {
            if (child.id !== "welcomeScreen") child.remove();
        });
        const ws = document.getElementById("welcomeScreen");
        if (ws) ws.style.display = chatHistory.length ? "none" : "flex";
        for (let i = 0; i < chatHistory.length; i += 2) {
            if (chatHistory[i]?.role === "user") appendUserMessage(chatHistory[i].content);
            if (chatHistory[i + 1]?.role === "assistant") appendBotHistoryMessage(chatHistory[i + 1].content, chatHistory[i].content);
        }
        renderSessionList();
        setSidebar(false);
        requestAnimationFrame(() => { chatContainer.scrollTop = chatContainer.scrollHeight; });
    }

    function appendBotHistoryMessage(text, prompt = "") {
        const div = document.createElement("div");
        div.className = "bot-message completed";
        div.setAttribute("data-prompt", prompt);
        div.setAttribute("data-raw-text", text);
        div.innerHTML = '<div class="message-content"></div>' +
            '<div class="message-actions">' +
            '<button class="action-btn tts-btn" title="Listen"><i class="fa-solid fa-play"></i></button>' +
            '<button class="action-btn copy-btn" title="Copy"><i class="fa-regular fa-copy"></i></button>' +
            '<button class="action-btn redo-btn" title="Regenerate"><i class="fa-solid fa-rotate-right"></i></button>' +
            '<button class="action-btn share-btn" title="Share"><i class="fa-solid fa-share-nodes"></i></button>' +
            '</div>';
        div.querySelector(".message-content").innerHTML = sanitizeRenderedMarkdown(marked.parse(text));
        chatContainer.appendChild(div);
    }

    renderSessionList();
    const synth = window.speechSynthesis;
    let currentUtterance = null;
    let activeTtsBtn = null;

    // ── Max history length to prevent memory leak / context overflow ───
    const MAX_CHAT_HISTORY = 40;

    function showToast(msg) {
        if (!toast) return;
        toast.textContent = msg;
        toast.classList.add("show");
        setTimeout(() => toast.classList.remove("show"), 2500);
    }

    // ── Safe clipboard helper (works on HTTP too) ─────────────────────
    async function safeCopy(text) {
        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(text);
            } else {
                // Fallback for non-HTTPS contexts
                const ta = document.createElement("textarea");
                ta.value = text;
                ta.style.position = "fixed";
                ta.style.left = "-9999px";
                document.body.appendChild(ta);
                ta.select();
                document.execCommand("copy");
                document.body.removeChild(ta);
            }
            return true;
        } catch (e) {
            return false;
        }
    }

    // --- Microphone Setup ---
    if (micBtn && userInput) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SpeechRecognition) {
            const recognition = new SpeechRecognition();
            recognition.continuous = false;
            recognition.interimResults = true;
            let isRecording = false;

            micBtn.addEventListener('click', () => {
                try {
                    if (isRecording) { recognition.stop(); } else { recognition.start(); }
                } catch (e) {
                    // Guard: recognition may already be started/stopped
                    console.warn("Speech recognition state error:", e.message);
                }
            });

            recognition.onstart = () => {
                isRecording = true;
                micBtn.classList.add("recording-pulse");
                userInput.placeholder = "Listening...";
            };

            recognition.onresult = (event) => {
                const transcript = Array.from(event.results).map(r => r[0]).map(r => r.transcript).join('');
                userInput.value = transcript;
                userInput.dispatchEvent(new Event('input'));
            };

            recognition.onend = () => {
                isRecording = false;
                micBtn.classList.remove("recording-pulse");
                userInput.placeholder = "Message TNEA AI...";
            };

            // ── Handle speech recognition errors ────────────────────
            recognition.onerror = (event) => {
                isRecording = false;
                micBtn.classList.remove("recording-pulse");
                userInput.placeholder = "Message TNEA AI...";
                if (event.error === "not-allowed") {
                    showToast("Microphone access denied. Please allow microphone permissions.");
                } else if (event.error !== "no-speech" && event.error !== "aborted") {
                    showToast("Voice input error: " + event.error);
                }
            };
        } else {
            // Hide mic button if SpeechRecognition is not supported
            micBtn.style.display = "none";
        }
    }

    // --- Dropdowns & Sidebar ---
    document.addEventListener("click", (e) => {
        const isDropdownTrigger = e.target.closest('.dropdown-trigger');
        const activeDropdowns = document.querySelectorAll('.dropdown-container.open');
        activeDropdowns.forEach(dropdown => {
            if (!dropdown.contains(e.target)) dropdown.classList.remove('open');
        });
        if (isDropdownTrigger) {
            isDropdownTrigger.closest('.dropdown-container').classList.toggle('open');
        }
    });

    const toggleSidebarBtn = document.getElementById("toggleSidebar");
    const closeSidebarBtn = document.getElementById("closeSidebar");
    const sidebar = document.getElementById("sidebar");
    const sidebarOverlay = document.getElementById("sidebarOverlay");
    const mobileQuery = window.matchMedia("(max-width: 868px)");
    function setSidebar(open) {
        if (!sidebar) return;
        sidebar.classList.toggle("is-open", open);
        document.body.classList.toggle("sidebar-open", open && mobileQuery.matches);
        sidebarOverlay?.classList.toggle("is-visible", open && mobileQuery.matches);
        toggleSidebarBtn?.setAttribute("aria-expanded", String(open));
        sidebarOverlay?.setAttribute("aria-hidden", String(!(open && mobileQuery.matches)));
    }
    toggleSidebarBtn?.setAttribute("aria-expanded", "false");
    toggleSidebarBtn?.addEventListener("click", e => { e.stopPropagation(); setSidebar(!sidebar?.classList.contains("is-open")); });
    closeSidebarBtn?.addEventListener("click", () => setSidebar(false));
    sidebarOverlay?.addEventListener("click", () => setSidebar(false));
    mobileQuery.addEventListener("change", () => { if (!mobileQuery.matches) setSidebar(false); });

    // --- Theme & Layout Settings ---
    const themeSelect = document.getElementById('themeSelect');
    function applyTheme(theme) {
        const isDark = theme === 'system' ? window.matchMedia('(prefers-color-scheme: dark)').matches : (theme === 'dark');
        document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
        localStorage.setItem('tnea_theme', theme);
        if (themeSelect) themeSelect.value = theme;
    }
    if (themeSelect) { themeSelect.addEventListener('change', (e) => applyTheme(e.target.value)); }
    applyTheme(localStorage.getItem('tnea_theme') || 'system');

    const fullscreenBtn = document.getElementById('menuFullscreenBtn');
    if (fullscreenBtn) {
        fullscreenBtn.addEventListener('click', () => {
            if (!document.fullscreenElement) { document.documentElement.requestFullscreen(); } 
            else { if (document.exitFullscreen) document.exitFullscreen(); }
        });
    }

    const menuClearBtn = document.getElementById('menuClearBtn');
    const newChatBtn = document.getElementById('newChatBtn');
    if (menuClearBtn) {
        menuClearBtn.addEventListener('click', () => {
            const sessions = loadSessions().filter(s => s.id !== currentSessionId);
            saveSessions(sessions);
            currentSessionId = null;
            chatHistory = [];
            Array.from(chatContainer.children).forEach(child => {
                if (child.id !== "welcomeScreen") child.remove();
            });
            const ws = document.getElementById("welcomeScreen");
            if (ws) ws.style.display = "flex";
            showToast("Chat cleared");
        });
    }
    if (newChatBtn) {
        newChatBtn.addEventListener('click', () => {
            currentSessionId = null;
            chatHistory = [];
            
            // Remove everything except the welcome screen
            Array.from(chatContainer.children).forEach(child => {
                if (child.id !== "welcomeScreen") {
                    child.remove();
                }
            });
            
            const ws = document.getElementById("welcomeScreen");
            if (ws) ws.style.display = "flex";
            
            setSidebar(false);
            showToast("Started new session");
        });
    }

    // --- Input Management ---
    if (userInput && sendBtn) {
        userInput.addEventListener("input", () => {
            userInput.style.height = "auto";
            userInput.style.height = Math.min(userInput.scrollHeight, 120) + "px";
        });
        userInput.addEventListener("keydown", (e) => { 
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } 
        });
        sendBtn.addEventListener("click", () => handleSend());
    }

    // --- Event Delegation (Action Buttons) ---
    if (chatContainer) {
        chatContainer.addEventListener("click", (e) => {
            const toggle = e.target.closest(".thinking-toggle");
            if (toggle) {
                toggle.closest('.thinking-wrapper').classList.toggle('open');
                return;
            }

            const target = e.target.closest(".action-btn");
            if (!target) return;
            
            const msgRow = target.closest('.user-row, .bot-message');
            if (!msgRow) return;

            const rawText = msgRow.getAttribute("data-raw-text") || "";

            if (target.classList.contains("copy-btn")) {
                safeCopy(rawText).then(ok => showToast(ok ? "Copied to clipboard." : "Copy failed."));
            }
            if (target.classList.contains("edit-btn")) {
                userInput.value = rawText; userInput.focus(); userInput.dispatchEvent(new Event('input'));
                msgRow.remove();
            }
            if (target.classList.contains("redo-btn")) {
                const prompt = msgRow.getAttribute("data-prompt"); msgRow.remove(); handleSend(prompt);
            }
            if (target.classList.contains("share-btn")) {
                if (navigator.share) {
                    navigator.share({ title: "TNEA AI", text: rawText }).catch(() => {
                        safeCopy(rawText).then(() => showToast("Copied for sharing."));
                    });
                } else {
                    safeCopy(rawText).then(ok => showToast(ok ? "Copied for sharing." : "Copy failed."));
                }
            }
            if (target.classList.contains("tts-btn")) {
                if (!rawText || !rawText.trim()) {
                    showToast("Nothing to read aloud.");
                    return;
                }
                handleTTS(rawText, target);
            }
        });
    }

    // ── Server health check on load ──────────────────────────────────
    (async function checkServerHealth() {
        try {
            const hCtrl = new AbortController();
            const hTimeout = setTimeout(() => hCtrl.abort(), 5000);
            const healthRes = await fetch("/health", { method: "GET", signal: hCtrl.signal });
            clearTimeout(hTimeout);
            if (healthRes.ok) {
                console.log("[health] Server is reachable");
            } else {
                console.warn("[health] Server returned status:", healthRes.status);
            }
        } catch (e) {
            console.error("[health] Server unreachable:", e);
            showToast("Server unreachable. Is uvicorn running on port 8000?");
        }
    })();

    function handleTTS(text, btnElement) {
        if (!synth) {
            showToast("Text-to-speech is not supported in this browser.");
            return;
        }
        if (synth.speaking && activeTtsBtn === btnElement) {
            if (synth.paused) { synth.resume(); btnElement.innerHTML = '<i class="fa-solid fa-pause"></i>'; }
            else { synth.pause(); btnElement.innerHTML = '<i class="fa-solid fa-play"></i>'; }
            return;
        }
        synth.cancel();
        if (activeTtsBtn && activeTtsBtn !== btnElement) { activeTtsBtn.innerHTML = '<i class="fa-solid fa-play"></i>'; }

        const cleanText = text.replace(/[*#_`]/g, '');
        currentUtterance = new SpeechSynthesisUtterance(cleanText);
        activeTtsBtn = btnElement;
        btnElement.innerHTML = '<i class="fa-solid fa-pause"></i>';

        currentUtterance.onend = () => {
            btnElement.innerHTML = '<i class="fa-solid fa-play"></i>';
            activeTtsBtn = null;
        };
        currentUtterance.onerror = (event) => {
            btnElement.innerHTML = '<i class="fa-solid fa-play"></i>';
            activeTtsBtn = null;
            if (event.error !== "canceled" && event.error !== "interrupted") {
                showToast("Speech playback failed.");
            }
        };
        synth.speak(currentUtterance);
    }

    // --- Welcome Screen Logic ---
    const welcomeScreen = document.getElementById("welcomeScreen");
    document.querySelectorAll(".quick-chip").forEach(chip => {
        chip.addEventListener("click", (e) => {
            const query = e.currentTarget.getAttribute("data-query");
            handleSend(query);
        });
    });

    // --- Message Streaming ---
    async function handleSend(customText = null) {
        const text = (customText !== null ? customText : userInput.value).trim();
        if (!text || isGenerating) return;

        // Hide welcome screen on first message
        if (welcomeScreen && welcomeScreen.style.display !== "none") {
            welcomeScreen.style.display = "none";
        }

        userInput.value = ""; userInput.style.height = "auto";
        userInput.disabled = true; isGenerating = true;

        appendUserMessage(text);
        const botUI = createBotCardShell(text);
        chatContainer.appendChild(botUI.msgElement);
        chatContainer.scrollTop = chatContainer.scrollHeight;

        let accText = "", accThought = "";

        // ── Fetch with abort timeout (90 seconds) ─────────────────────
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 90000);

        try {
            // Log for debugging
            console.log("[chat] Sending request to /chat with:", { message: text, historyCount: chatHistory.length });
            
            const response = await fetch("/chat", {
                method: "POST", headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
                cache: "no-store",
                body: JSON.stringify({ message: text, history: chatHistory }),
                signal: controller.signal
            });
            clearTimeout(timeoutId);

            if (!response.ok) {
                let errorMsg = `Server error (${response.status})`;
                try { const eb = await response.json(); if (eb.error) errorMsg = eb.error; } catch (e) {}
                botUI.content.innerHTML = `<p style="color:#ff3b30; font-weight:500;">⚠️ ${sanitizeHTML(errorMsg)}</p>`;
                console.error("[chat] Server returned error:", response.status, errorMsg);
                return;
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n\n");
                buffer = lines.pop();

                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue;
                    const payload = line.slice(6);
                    if (payload === "[DONE]") {
                        console.log("[chat] Received [DONE]");
                        break;
                    }

                    let data;
                    try { data = JSON.parse(payload); } catch (e) { continue; }

                    if (data.type === "thought") {
                        // Internal progress is intentionally kept out of the
                        // answer UI; users see a clean, uninterrupted response.
                        accThought += data.content + "\n";
                    } else if (data.type === "thought_done") {
                        // No visible reasoning container.
                    } else if (data.type === "token") {
                        accText += data.content;
                        botUI.content.innerHTML = sanitizeRenderedMarkdown(marked.parse(accText));
                        botUI.msgElement.setAttribute("data-raw-text", accText);
                    } else if (data.type === "error") {
                        console.error("[chat] Server error event:", data.content);
                        botUI.content.innerHTML = `<p style="color:#ff3b30; font-weight:500;">⚠️ ${sanitizeHTML(data.content)}</p>`;
                    }
                    chatContainer.scrollTop = chatContainer.scrollHeight;
                }
            }
            // Only push to history if we got a meaningful response
            if (accText.trim()) {
                chatHistory.push({ role: "user", content: text }, { role: "assistant", content: accText });
                while (chatHistory.length > MAX_CHAT_HISTORY) {
                    chatHistory.shift(); chatHistory.shift();
                }
                persistCurrentSession();
            }
        } catch (err) {
            clearTimeout(timeoutId);
            console.error("[chat] Fetch error:", err);
            if (err.name === "AbortError") {
                botUI.content.innerHTML = `<p style="color:#ff3b30; font-weight:500;">⚠️ ${sanitizeHTML("Request timed out. Please try again.")}</p>`;
            } else {
                botUI.content.innerHTML = `<p style="color:#ff3b30; font-weight:500;">⚠️ ${sanitizeHTML(err.message || "Connection error. Is the server running on port 8000?")}</p>`;
            }
        } finally {
            botUI.msgElement.classList.add("completed");
            isGenerating = false;
            userInput.disabled = false;
            userInput.focus();
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }
    }

    function appendUserMessage(text) {
        const div = document.createElement("div");
        div.className = "user-row completed";
        div.setAttribute("data-raw-text", text);

        // Build the DOM safely to prevent XSS from user input
        const msgDiv = document.createElement("div");
        msgDiv.className = "user-message";
        msgDiv.textContent = text;

        const actionsDiv = document.createElement("div");
        actionsDiv.className = "message-actions user-actions";

        const editBtn = document.createElement("button");
        editBtn.className = "action-btn edit-btn";
        editBtn.title = "Edit";
        editBtn.innerHTML = '<i class="fa-solid fa-pen"></i>';

        const copyBtn = document.createElement("button");
        copyBtn.className = "action-btn copy-btn";
        copyBtn.title = "Copy";
        copyBtn.innerHTML = '<i class="fa-regular fa-copy"></i>';

        actionsDiv.appendChild(editBtn);
        actionsDiv.appendChild(copyBtn);
        div.appendChild(msgDiv);
        div.appendChild(actionsDiv);
        chatContainer.appendChild(div);
    }

    function createBotCardShell(prompt) {
        const div = document.createElement("div");
        div.className = "bot-message";
        div.setAttribute("data-prompt", prompt);
        div.setAttribute("data-raw-text", "");
        div.innerHTML = `
            <div class="message-content"><span class="stream-cursor" aria-hidden="true"></span></div>
            <div class="message-actions">
                <button class="action-btn tts-btn" title="Listen"><i class="fa-solid fa-play"></i></button>
                <button class="action-btn copy-btn" title="Copy"><i class="fa-regular fa-copy"></i></button>
                <button class="action-btn redo-btn" title="Regenerate"><i class="fa-solid fa-rotate-right"></i></button>
                <button class="action-btn share-btn" title="Share"><i class="fa-solid fa-share-nodes"></i></button>
            </div>
        `;
        return {
            msgElement: div,
            thoughtWrap: { style: { display: "none" } },
            thoughtBody: null,
            content: div.querySelector(".message-content")
        };
    }
});