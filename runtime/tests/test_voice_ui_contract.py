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

