from pathlib import Path


def test_voice_core_exposes_elevenlabs_engine_without_browser_key_storage():
    root = Path(__file__).resolve().parents[2]
    hook = (
        root
        / "apps"
        / "web"
        / "src"
        / "features"
        / "audio"
        / "useAgentVoice.ts"
    ).read_text(encoding="utf-8")
    control = (
        root
        / "apps"
        / "web"
        / "src"
        / "features"
        / "audio"
        / "VoiceControl.tsx"
    ).read_text(encoding="utf-8")

    assert 'engine: "browser"' in hook
    assert 'settings.engine === "elevenlabs"' in hook
    assert "api.streamElevenLabsSpeech" in hook
    assert "audioContextRef" in hook
    assert "decodeAudioData" in hook
    assert "synth.resume()" in hook
    assert "System voice did not start; retrying." in hook
    assert "api.configureElevenLabsVoice" in hook

    assert 'value="elevenlabs"' in control
    assert "Detect voices" in control
    assert "Test connection" in control
    assert "Save key" in control
    assert "AUDIO OUTPUT" in control
    assert "audioStatus" in control

    # Only non-secret voice preferences are persisted in localStorage.
    assert "apiKey" not in "VoiceSettings = {" + hook.split(
        "VoiceSettings = {", 1
    )[1].split("};", 1)[0]


def test_dashboard_wires_elevenlabs_voice_controls():
    root = Path(__file__).resolve().parents[2]
    dashboard = (
        root
        / "apps"
        / "web"
        / "src"
        / "features"
        / "dashboard"
        / "Dashboard.tsx"
    ).read_text(encoding="utf-8")

    assert "elevenConfig={voice.elevenConfig}" in dashboard
    assert "elevenVoices={voice.elevenVoices}" in dashboard
    assert (
        "onRefreshElevenVoices={voice.refreshElevenVoices}"
        in dashboard
    )
    assert "onSaveElevenLabs={voice.saveElevenLabs}" in dashboard
    assert "audioStatus={voice.audioStatus}" in dashboard

def test_voice_conversation_hands_turn_back_to_user_after_agent_reply():
    root = Path(__file__).resolve().parents[2]
    wake = (
        root
        / "apps"
        / "web"
        / "src"
        / "features"
        / "audio"
        / "useWakeWord.ts"
    ).read_text(encoding="utf-8")

    command_completion = wake.split(
        "Promise.resolve(onCommandRef.current(command))", 1
    )[1].split("const armSilenceTimer", 1)[0]

    # Recognition stays stopped for the entire agent turn, then resumes
    # direct command listening so the conversation alternates naturally:
    # user -> agent -> user -> agent.
    assert 'modeRef.current = "command";' in command_completion
    assert 'setState("waking");' in command_completion
    assert 'scheduleStart("command", 220);' in command_completion
    assert 'scheduleStart("standby")' not in command_completion

def test_voice_conversation_turn_times_out_to_wake_word_standby():
    root = Path(__file__).resolve().parents[2]
    wake = (
        root
        / "apps"
        / "web"
        / "src"
        / "features"
        / "audio"
        / "useWakeWord.ts"
    ).read_text(encoding="utf-8")

    assert "CONVERSATION_IDLE_MS = 30_000" in wake
    assert "armConversationIdleTimer()" in wake
    assert "clearConversationIdleTimer()" in wake
    assert "Conversation idle. Waiting for the wake phrase." in wake

    idle_handler = wake.split(
        "conversationIdleTimerRef.current = window.setTimeout", 1
    )[1].split("}, CONVERSATION_IDLE_MS);", 1)[0]

    # Thirty seconds of silence ends the active conversation, but it must
    # return to wake-word standby so hands-free activation still works.
    assert 'modeRef.current = "standby";' in idle_handler
    assert 'setState("standby");' in idle_handler
    assert 'startModeRef.current?.("standby");' in idle_handler
    assert 'modeRef.current = "off";' not in idle_handler
    assert 'setState("off");' not in idle_handler

def test_voice_sanitizes_markdown_json_and_special_characters_before_tts():
    root = Path(__file__).resolve().parents[2]
    hook = (
        root
        / "apps"
        / "web"
        / "src"
        / "features"
        / "audio"
        / "useAgentVoice.ts"
    ).read_text(encoding="utf-8")
    executive = (
        root
        / "runtime"
        / "app"
        / "agents"
        / "executive.py"
    ).read_text(encoding="utf-8")

    assert "export function sanitizeForSpeech" in hook
    assert "Technical details are shown on screen." in hook
    assert 'value.replaceAll("_", " ")' in hook
    assert '/[*_~]/g' in hook
    assert 'const cleaned = sanitizeForSpeech(text);' in hook
    assert "Do not narrate internal action names" in executive
    assert "propose_upgrade" in executive
    assert "natural conversational" in executive

def test_runtime_status_voice_is_queued_and_background_reply_is_spoken():
    root = Path(__file__).resolve().parents[2]
    hook = (
        root
        / "apps"
        / "web"
        / "src"
        / "features"
        / "audio"
        / "useAgentVoice.ts"
    ).read_text(encoding="utf-8")
    dashboard = (
        root
        / "apps"
        / "web"
        / "src"
        / "features"
        / "dashboard"
        / "Dashboard.tsx"
    ).read_text(encoding="utf-8")

    assert "speechQueueRef" in hook
    assert "queueSpeakAsync" in hook
    assert "requestAgentSpeech(speech)" in dashboard
    assert "runtimeSpeechAnnouncement" in dashboard
    assert '"background_job.started"' in dashboard
    assert '"background_job.progress"' in dashboard
    assert '"background_job.completed"' in dashboard
    assert '"background_job.error"' in dashboard
    assert '"completed", "background"' in dashboard
    assert "voice.queueSpeakAsync(result.text)" in dashboard
    assert 'setConsoleOpen(true);' in dashboard


def test_worker_monitor_exposes_safe_progress_not_private_chain_of_thought():
    root = Path(__file__).resolve().parents[2]
    worker = (
        root
        / "runtime"
        / "app"
        / "agents"
        / "executor.py"
    ).read_text(encoding="utf-8")
    dashboard = (
        root
        / "apps"
        / "web"
        / "src"
        / "features"
        / "dashboard"
        / "Dashboard.tsx"
    ).read_text(encoding="utf-8")

    assert '"progress" field written for the user' in worker
    assert "Do not expose private" in worker
    assert 'phase="planning"' in worker
    assert "safeMonitorDetail" in dashboard
    assert '"[redacted]"' in dashboard
    assert '" · tool: "' in dashboard

def test_worker_approval_interrupts_user_with_text_and_voice():
    root = Path(__file__).resolve().parents[2]
    dashboard = (
        root
        / "apps"
        / "web"
        / "src"
        / "features"
        / "dashboard"
        / "Dashboard.tsx"
    ).read_text(encoding="utf-8")
    supervisor = (
        root
        / "runtime"
        / "app"
        / "agents"
        / "background_jobs.py"
    ).read_text(encoding="utf-8")

    assert '"background_job.approval_required"' in dashboard
    assert "approvalActionLabel" in dashboard
    assert "Agent Man needs your approval" in dashboard
    assert "requestAgentSpeech(speech)" in dashboard
    assert "setConsoleOpen(true)" in dashboard
    assert "setRun((current) => ({" in dashboard
    assert '"waiting_approval"' in dashboard

    assert '"background_job.approval_required"' in supervisor
    assert 'phase="approval"' in supervisor
    assert 'status="waiting_approval"' in supervisor
    assert "ask Agent Man to retry the worker" in supervisor

