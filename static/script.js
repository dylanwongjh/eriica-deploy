document.addEventListener('DOMContentLoaded', function () {

    // =========================================================
    // DOM references
    // =========================================================
    const scenarioScreen   = document.getElementById('scenarioScreen');
    const chatInterface    = document.getElementById('chatInterface');
    const scenarioInput    = document.getElementById('scenarioInput');
    const beginChatButton  = document.getElementById('beginChat');
    const chatMessages     = document.getElementById('chatMessages');
    const userInput        = document.getElementById('userInput');
    const sendButton       = document.getElementById('sendButton');
    const typingIndicator  = document.getElementById('typingIndicator');
    const resourcesButton  = document.getElementById('resourcesButton');
    const endSessionButton = document.getElementById('endSessionButton');
    const scenarioError    = document.getElementById('scenarioError');

    // =========================================================
    // State
    // =========================================================

    // Mirrors MAX_HISTORY_TURNS in app.py. Each "turn" = 1 user + 1 assistant message.
    const MAX_HISTORY_TURNS = 20;

    let chatHistory     = [];
    let currentScenario = '';
    let scenarios       = [];
    let activeFilter    = 'all';
    let activeFramework = 'spikes';
    let debriefData     = null;
    let activeDebriefFw = 'SPIKES';
    // BUG FIX: track whether a send is in flight so spam-clicking Send is a no-op.
    let isSending       = false;

    // =========================================================
    // Utilities
    // =========================================================

    /** Return only the most recent MAX_HISTORY_TURNS turns to keep payloads small. */
    function trimmedHistory() {
        return chatHistory.slice(-(MAX_HISTORY_TURNS * 2));
    }

    /** Scroll the chat container to the bottom smoothly. */
    function smoothScrollToBottom() {
        const chatContainer = document.querySelector('.chat-container');
        if (chatContainer) {
            chatContainer.scrollTo({ top: chatContainer.scrollHeight, behavior: 'smooth' });
        }
    }

    /**
     * Append a message bubble to the chat window.
     * Uses textContent (not innerHTML) so user input is never treated as HTML.
     */
    function addMessage(text, sender) {
        const wrapper = document.createElement('div');
        wrapper.classList.add('chat-message', `${sender}-message`);

        const bubble = document.createElement('div');
        bubble.classList.add('message-content');
        bubble.textContent = text;

        wrapper.appendChild(bubble);
        chatMessages.appendChild(wrapper);
        setTimeout(smoothScrollToBottom, 100);
    }

    function showTyping() {
        typingIndicator.style.display = 'flex';
        setTimeout(smoothScrollToBottom, 100);
    }

    function hideTyping() {
        typingIndicator.style.display = 'none';
    }

    // =========================================================
    // Scenario library
    // =========================================================

    async function loadScenarios() {
        try {
            const res  = await fetch('/api/scenarios?n=6');
            const data = await res.json();
            scenarios  = data.scenarios || [];
        } catch (e) {
            console.error('[scenarios] failed to load:', e);
            scenarios = [];
        }
        renderScenarioCards();
    }

    function renderScenarioCards() {
        const grid = document.getElementById('scenarioCardGrid');
        if (!grid) return;

        const filtered = activeFilter === 'all'
            ? scenarios
            : scenarios.filter(s => s.difficulty === activeFilter);

        grid.innerHTML = filtered.map(s => `
            <div class="sc-card" data-id="${s.id}">
                <div class="sc-card-top">
                    <span class="sc-diff sc-diff-${s.difficulty}">${s.difficulty}</span>
                </div>
                ${s.summary ? `<p class="sc-card-summary">${s.summary}</p>` : ''}
            </div>
        `).join('');

        grid.querySelectorAll('.sc-card').forEach(card => {
            card.addEventListener('click', () => {
                const scenario = scenarios.find(s => s.id === card.dataset.id);
                if (!scenario) return;
                scenarioInput.value = scenario.prompt;
                grid.querySelectorAll('.sc-card').forEach(c => c.classList.remove('selected'));
                card.classList.add('selected');
            });
        });
    }

    document.getElementById('scenarioFilterRow')?.addEventListener('click', async e => {
        // Handle refresh button
        const refreshBtn = e.target.closest('#refreshScenarios');
        if (refreshBtn) {
            if (refreshBtn.disabled) return;
            refreshBtn.disabled = true;
            refreshBtn.classList.add('spinning');
            await loadScenarios();
            refreshBtn.disabled = false;
            refreshBtn.classList.remove('spinning');
            return;
        }
        // Handle difficulty filter buttons
        if (!e.target.classList.contains('sc-filter')) return;
        document.querySelectorAll('.sc-filter').forEach(b => b.classList.remove('active'));
        e.target.classList.add('active');
        activeFilter = e.target.dataset.filter;
        renderScenarioCards();
    });

    // =========================================================
    // Chat initialisation
    // =========================================================

    async function initChat(scenario) {
        showTyping();
        try {
            const res  = await fetch('/api/start', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ scenario }),
            });
            const data = await res.json();
            hideTyping();

            document.getElementById('patientProfileBar').style.display = 'flex';
            loadPatientProfile();

            if (data.response) {
                addMessage(data.response, 'bot');
                chatHistory.push({ role: 'assistant', content: data.response });
            } else {
                addMessage("I'm having trouble connecting right now. Please try again later.", 'bot');
            }
        } catch (err) {
            hideTyping();
            addMessage("Sorry, I'm experiencing technical difficulties. Please refresh the page.", 'bot');
            console.error('[initChat] error:', err);
        }
    }

    // =========================================================
    // Patient profile
    // =========================================================

    async function loadPatientProfile() {
        try {
            const res  = await fetch('/api/profile', { credentials: 'include' });
            const data = await res.json();
            if (data.profile) renderProfile(data.profile);
        } catch (e) {
            console.error('[loadPatientProfile] error:', e);
        }
    }

    function renderProfile(p) {
        const content = document.getElementById('profileContent');

        const row = (label, value) => `
            <div class="profile-section">
                <div class="profile-label">${label}</div>
                <div class="profile-value">${value}</div>
            </div>`;

        const badges = (label, items, cls) => `
            <div class="profile-section">
                <div class="profile-label">${label}</div>
                <div class="badge-row">
                    ${items.map(i => `<span class="badge ${cls}">${i}</span>`).join(' ')}
                </div>
            </div>`;

        let html = '';
        if (p.scenario)              html += row('Scenario',        p.scenario);
        if (p.topic)                 html += row('Topic',           p.topic);
        if (p.clinical_goal)         html += row('Clinical Goal',   p.clinical_goal);
        if (p.primary_emotions?.length) html += badges('Primary emotions', p.primary_emotions, 'badge-emotion');
        if (p.cognitive_state?.length)  html += badges('Cognitive state',  p.cognitive_state,  'badge-cognitive');
        if (p.underlying_need)       html += row('Underlying need', p.underlying_need);

        content.innerHTML = html
            || '<div class="profile-section"><div class="profile-value">No profile data found for this scenario.</div></div>';
    }

    document.getElementById('profileToggleBar').addEventListener('click', () => {
        const card    = document.getElementById('profileCard');
        const chevron = document.getElementById('profileChevron');
        const isOpen  = card.style.display === 'block';
        card.style.display          = isOpen ? 'none'        : 'block';
        chevron.style.transform     = isOpen ? 'rotate(0deg)' : 'rotate(180deg)';
    });

    // =========================================================
    // Sending messages
    // =========================================================

    async function sendMessage() {
        const message = userInput.value.trim();
        // BUG FIX: guard against empty input AND concurrent in-flight requests.
        if (!message || isSending) return;

        isSending = true;
        sendButton.disabled = true;

        chatHistory.push({ role: 'user', content: message });
        addMessage(message, 'user');
        userInput.value = '';
        showTyping();

        try {
            const res  = await fetch('/api/chat', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ chat_history: trimmedHistory() }),
            });
            const data = await res.json();
            hideTyping();

            if (data.response) {
                addMessage(data.response, 'bot');
                chatHistory.push({ role: 'assistant', content: data.response });
            }
        } catch (err) {
            hideTyping();
            addMessage('Connection error. Please try again.', 'bot');
            console.error('[sendMessage] error:', err);
        } finally {
            isSending           = false;
            sendButton.disabled = false;
            userInput.focus();
        }
    }

    // =========================================================
    // Framework reference panel (SPIKES / NURSE)
    // =========================================================

    const FRAMEWORKS = {
        spikes: [
            { letter: 'S', title: 'Setting Up',           desc: 'Prepare mentally and secure a private, comfortable space.' },
            { letter: 'P', title: "Patient's Perception", desc: 'Find out what the patient already knows or expects before sharing.' },
            { letter: 'I', title: 'Invitation',           desc: 'Ask how much detail the patient wants.' },
            { letter: 'K', title: 'Knowledge',            desc: 'Deliver the medical facts clearly and in small, digestible chunks.' },
            { letter: 'E', title: 'Emotions',             desc: "Acknowledge, validate, and respond to the patient's emotional reactions with empathy." },
            { letter: 'S', title: 'Strategy & Summary',   desc: 'Map out a clear, actionable treatment plan for the future.' },
        ],
        nurse: [
            { letter: 'N', title: 'Naming',       desc: "State the patient's or family's emotion directly to show you notice what they are feeling." },
            { letter: 'U', title: 'Understanding', desc: 'Validate their feelings by explicitly stating that their emotional response makes sense given the situation.' },
            { letter: 'R', title: 'Respecting',   desc: 'Praise them for their strength, resilience, or the care they are showing.' },
            { letter: 'S', title: 'Supporting',   desc: 'Reassure them that they are not alone and there will be support.' },
            { letter: 'E', title: 'Exploring',    desc: 'Encourage them to share more about their feelings, thoughts, and what they need most.' },
        ],
    };

    function renderFramework(key) {
        const steps            = FRAMEWORKS[key] || [];
        const frameworkContent = document.getElementById('frameworkContent');
        frameworkContent.innerHTML = steps.map(s => `
            <div class="fw-step">
                <span class="fw-letter">${s.letter}</span>
                <div>
                    <div class="fw-step-title">${s.title}</div>
                    <div class="fw-step-desc">${s.desc}</div>
                </div>
            </div>`
        ).join('');
    }

    function toggleFrameworkPanel() {
        const panel     = document.getElementById('frameworkPanel');
        const isVisible = panel.style.display === 'block';
        panel.style.display  = isVisible ? 'none' : 'block';
        resourcesButton.innerHTML = isVisible
            ? '<i class="fas fa-book-open"></i> Show Frameworks'
            : '<i class="fas fa-times"></i> Hide Frameworks';
        if (!isVisible) renderFramework(activeFramework);
    }

    // =========================================================
    // Debrief modal
    // =========================================================

    async function openDebrief() {
        // BUG FIX: replaced alert() with an inline error consistent with the
        // rest of the UI (same pattern used for the scenario validation error).
        if (chatHistory.length < 2) {
            showScenarioError('The conversation is too short to evaluate. Please exchange at least a few messages first.');
            return;
        }

        const overlay = document.getElementById('debriefOverlay');
        document.getElementById('debriefLoading').style.display      = 'flex';
        document.getElementById('debriefResults').style.display       = 'none';
        document.getElementById('debriefError').style.display         = 'none';
        document.getElementById('debriefScenarioLabel').textContent   = currentScenario;
        overlay.style.display = 'flex';

        try {
            const res  = await fetch('/api/evaluate', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ chat_history: chatHistory, scenario: currentScenario }),
            });
            const data = await res.json();

            document.getElementById('debriefLoading').style.display = 'none';

            if (data.evaluation) {
                debriefData = data.evaluation;
                renderDebrief(debriefData);
                document.getElementById('debriefResults').style.display = 'block';
            } else {
                document.getElementById('debriefError').style.display = 'block';
            }
        } catch (err) {
            document.getElementById('debriefLoading').style.display = 'none';
            document.getElementById('debriefError').style.display   = 'block';
            console.error('[openDebrief] error:', err);
        }
    }

    function renderDebrief(ev) {
        document.getElementById('debriefSummary').textContent = ev.overall_summary || '';

        // Dimension score rows
        const dimContainer = document.getElementById('debriefDimensions');
        dimContainer.innerHTML = (ev.dimensions || []).map(d => {
            const score  = Math.max(1, Math.min(5, d.score));
            const pct    = ((score - 1) / 4) * 100;
            const colour = score <= 2 ? '#C0714A' : score === 3 ? '#B8973A' : '#5A9E6F';
            return `
                <div class="dim-row">
                    <div class="dim-header">
                        <span class="dim-name">${d.name}</span>
                        <span class="dim-score" style="color:${colour}">${score}<span class="dim-denom">/5</span></span>
                    </div>
                    <div class="dim-bar-track">
                        <div class="dim-bar-fill" style="width:${pct}%; background:${colour};"></div>
                    </div>
                    <p class="dim-justification">${d.justification}</p>
                </div>`;
        }).join('');

        renderChecklistTab(activeDebriefFw);
    }

    function renderChecklistTab(fw) {
        if (!debriefData) return;
        const steps     = debriefData.framework_checklist?.[fw] || [];
        const container = document.getElementById('debriefChecklist');
        container.innerHTML = steps.map(s => `
            <div class="checklist-row ${s.demonstrated ? 'demonstrated' : 'missed'}">
                <span class="checklist-icon">${s.demonstrated ? '✓' : '✗'}</span>
                <div class="checklist-text">
                    <span class="checklist-step">${s.step}</span>
                    <span class="checklist-note">${s.note}</span>
                </div>
            </div>`
        ).join('');
    }

    function closeDebrief() {
        document.getElementById('debriefOverlay').style.display = 'none';
        debriefData     = null;
        activeDebriefFw = 'SPIKES';
    }

    /** Reset all session state and return to the scenario selection screen. */
    function resetSession() {
        closeDebrief();
        chatHistory     = [];
        currentScenario = '';
        isSending       = false;
        sendButton.disabled = false;

        document.getElementById('chatMessages').innerHTML        = '';
        document.getElementById('chatInterface').style.display   = 'none';
        document.getElementById('patientProfileBar').style.display = 'none';
        document.getElementById('profileCard').style.display     = 'none';
        document.getElementById('scenarioInput').value           = '';
        document.getElementById('scenarioScreen').style.display  = 'flex';
        document.getElementById('frameworkPanel').style.display  = 'none';
        resourcesButton.innerHTML = '<i class="fas fa-book-open"></i> Show Frameworks';
    }

    // =========================================================
    // Error helpers
    // =========================================================

    function showScenarioError(msg) {
        scenarioError.textContent = msg;
    }

    function clearScenarioError() {
        scenarioError.textContent = '';
    }

    // =========================================================
    // Event listeners
    // =========================================================

    // --- Scenario submission ---
    beginChatButton.addEventListener('click', function () {
        const scenario = scenarioInput.value.trim();

        // BUG FIX: the old handler recreated #scenarioError dynamically even
        // though it already exists in the HTML. Now just uses the existing element.
        if (scenario.length < 5) {
            showScenarioError('Please describe the situation briefly before starting.');
            scenarioInput.focus();
            return;
        }
        clearScenarioError();

        beginChatButton.disabled    = true;
        beginChatButton.textContent = 'Starting…';

        scenarioScreen.style.display  = 'none';
        chatInterface.style.display   = 'flex';
        currentScenario               = scenario;

        initChat(scenario).finally(() => {
            beginChatButton.disabled    = false;
            beginChatButton.textContent = 'Start with ERIICA';
        });
    });

    // --- Send message ---
    sendButton.addEventListener('click', sendMessage);

    userInput.addEventListener('keydown', function (e) {
        // BUG FIX: was 'keypress', which is deprecated. Use 'keydown' instead.
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // --- Profile toggle ---
    // (listener is registered inline after renderProfile, above)

    // --- Framework tabs (delegated — covers both resource panel and debrief) ---
    document.addEventListener('click', function (e) {
        // Resource panel tabs (data-fw)
        if (e.target.classList.contains('fw-tab') && e.target.dataset.fw) {
            document.querySelectorAll('.fw-tab[data-fw]').forEach(t => t.classList.remove('active'));
            e.target.classList.add('active');
            activeFramework = e.target.dataset.fw;
            renderFramework(activeFramework);
        }
        // Debrief checklist tabs (data-debrief-fw)
        if (e.target.dataset.debriefFw) {
            document.querySelectorAll('[data-debrief-fw]').forEach(t => t.classList.remove('active'));
            e.target.classList.add('active');
            activeDebriefFw = e.target.dataset.debriefFw;
            renderChecklistTab(activeDebriefFw);
        }
    });

    // --- Resources panel ---
    resourcesButton.addEventListener('click', toggleFrameworkPanel);

    // --- End session ---
    endSessionButton.addEventListener('click', openDebrief);

    // --- Debrief actions ---
    document.getElementById('debriefContinueSession').addEventListener('click', closeDebrief);
    document.getElementById('debriefNewSession').addEventListener('click', resetSession);

    // =========================================================
    // Initialise
    // =========================================================
    loadScenarios();
});