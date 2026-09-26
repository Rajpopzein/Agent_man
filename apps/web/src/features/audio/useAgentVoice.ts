import { useCallback, useEffect, useMemo, useState } from "react";

export type VoiceSettings = {
  enabled: boolean;
  autoSpeak: boolean;
  voiceURI: string;
  rate: number;
  pitch: number;
  volume: number;
  wakeEnabled: boolean;
  wakePhrase: string;
  wakeLanguage: string;
};

const STORAGE_KEY = "agent-man.voice.settings.v1";
const SPEAK_EVENT = "agent-man:speak";

export function requestAgentSpeech(text: string) {
  window.dispatchEvent(
    new CustomEvent(SPEAK_EVENT, {
      detail: { text },
    }),
  );
}

const DEFAULT_SETTINGS: VoiceSettings = {
  enabled: true,
  autoSpeak: true,
  voiceURI: "",
  rate: 0.92,
  pitch: 0.78,
  volume: 0.92,
  wakeEnabled: false,
  wakePhrase: "hey agent man",
  wakeLanguage: "en-IN",
};

const PREFERRED_VOICE_HINTS = [
  "Microsoft Guy",
  "Microsoft Ryan",
  "Microsoft David",
  "Microsoft Mark",
  "Google UK English Male",
  "English United Kingdom",
  "English (United Kingdom)",
];

function loadSettings(): VoiceSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    return {
      ...DEFAULT_SETTINGS,
      ...JSON.parse(raw),
    };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function useAgentVoice() {
  const [settings, setSettings] = useState<VoiceSettings>(loadSettings);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [speaking, setSpeaking] = useState(false);

  useEffect(() => {
    const synth = window.speechSynthesis;

    function refresh() {
      setVoices(synth.getVoices());
    }

    refresh();
    synth.addEventListener("voiceschanged", refresh);
    return () => synth.removeEventListener("voiceschanged", refresh);
  }, []);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  }, [settings]);

  const selectedVoice = useMemo(() => {
    if (settings.voiceURI) {
      const exact = voices.find((voice) => voice.voiceURI === settings.voiceURI);
      if (exact) return exact;
    }

    for (const hint of PREFERRED_VOICE_HINTS) {
      const preferred = voices.find(
        (voice) =>
          voice.name.toLowerCase().includes(hint.toLowerCase()) &&
          voice.lang.toLowerCase().startsWith("en"),
      );
      if (preferred) return preferred;
    }

    return (
      voices.find(
        (voice) =>
          voice.default &&
          voice.lang.toLowerCase().startsWith("en"),
      ) ||
      voices.find((voice) => voice.lang.toLowerCase().startsWith("en")) ||
      voices[0] ||
      null
    );
  }, [settings.voiceURI, voices]);

  const stop = useCallback(() => {
    window.speechSynthesis.cancel();
    setSpeaking(false);
  }, []);

  const speak = useCallback(
    (text: string, force = false) => {
      const cleaned = text.trim();
      if (!cleaned) return;
      if (!force && (!settings.enabled || !settings.autoSpeak)) return;

      const synth = window.speechSynthesis;
      synth.cancel();

      const utterance = new SpeechSynthesisUtterance(cleaned);
      utterance.rate = settings.rate;
      utterance.pitch = settings.pitch;
      utterance.volume = settings.volume;
      if (selectedVoice) {
        utterance.voice = selectedVoice;
        utterance.lang = selectedVoice.lang;
      } else {
        utterance.lang = "en-GB";
      }

      utterance.onstart = () => setSpeaking(true);
      utterance.onend = () => setSpeaking(false);
      utterance.onerror = () => setSpeaking(false);
      synth.speak(utterance);
    },
    [selectedVoice, settings],
  );

  useEffect(() => {
    function onSpeak(event: Event) {
      const detail = (event as CustomEvent<{ text?: string }>).detail;
      if (detail?.text) {
        speak(detail.text);
      }
    }

    window.addEventListener(SPEAK_EVENT, onSpeak);
    return () => window.removeEventListener(SPEAK_EVENT, onSpeak);
  }, [speak]);

  const speakAsync = useCallback(
    (text: string, force = false) =>
      new Promise<void>((resolve) => {
        const cleaned = text.trim();
        if (!cleaned) {
          resolve();
          return;
        }
        if (!force && (!settings.enabled || !settings.autoSpeak)) {
          resolve();
          return;
        }

        const synth = window.speechSynthesis;
        synth.cancel();

        const utterance = new SpeechSynthesisUtterance(cleaned);
        utterance.rate = settings.rate;
        utterance.pitch = settings.pitch;
        utterance.volume = settings.volume;
        if (selectedVoice) {
          utterance.voice = selectedVoice;
          utterance.lang = selectedVoice.lang;
        } else {
          utterance.lang = "en-GB";
        }

        utterance.onstart = () => setSpeaking(true);
        utterance.onend = () => {
          setSpeaking(false);
          resolve();
        };
        utterance.onerror = () => {
          setSpeaking(false);
          resolve();
        };
        synth.speak(utterance);
      }),
    [selectedVoice, settings],
  );

  const testVoice = useCallback(() => {
    const synth = window.speechSynthesis;
    synth.cancel();

    const utterance = new SpeechSynthesisUtterance(
      "Agent Man online. Systems linked. Standing by for your directive.",
    );
    utterance.rate = settings.rate;
    utterance.pitch = settings.pitch;
    utterance.volume = settings.volume;
    if (selectedVoice) {
      utterance.voice = selectedVoice;
      utterance.lang = selectedVoice.lang;
    } else {
      utterance.lang = "en-GB";
    }
    utterance.onstart = () => setSpeaking(true);
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    synth.speak(utterance);
  }, [selectedVoice, settings]);

  function update(patch: Partial<VoiceSettings>) {
    setSettings((current) => ({ ...current, ...patch }));
  }

  function resetSignature() {
    setSettings((current) => ({
      ...current,
      enabled: true,
      autoSpeak: true,
      rate: DEFAULT_SETTINGS.rate,
      pitch: DEFAULT_SETTINGS.pitch,
      volume: DEFAULT_SETTINGS.volume,
      voiceURI: selectedVoice?.voiceURI || current.voiceURI,
    }));
  }

  return {
    settings,
    voices,
    selectedVoice,
    speaking,
    update,
    speak,
    speakAsync,
    stop,
    testVoice,
    resetSignature,
  };
}
