import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  api,
  ElevenLabsVoice,
  ElevenLabsVoiceConfig,
} from "../../services/api";

export type VoiceEngine = "browser" | "elevenlabs";

export type VoiceSettings = {
  enabled: boolean;
  autoSpeak: boolean;
  engine: VoiceEngine;
  voiceURI: string;
  rate: number;
  pitch: number;
  volume: number;
  wakeEnabled: boolean;
  wakePhrase: string;
  wakeLanguage: string;
};

const STORAGE_KEY = "agent-man.voice.settings.v2";
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
  engine: "browser",
  voiceURI: "",
  rate: 0.92,
  pitch: 0.78,
  volume: 0.92,
  wakeEnabled: false,
  wakePhrase: "hey agent man",
  wakeLanguage: "en-IN",
};

const DEFAULT_ELEVEN_CONFIG: ElevenLabsVoiceConfig = {
  provider_id: "elevenlabs",
  voice_id: "",
  model_id: "eleven_flash_v2_5",
  output_format: "mp3_44100_128",
  has_secret: false,
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
    const raw =
      localStorage.getItem(STORAGE_KEY) ||
      localStorage.getItem("agent-man.voice.settings.v1");
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
  const [settings, setSettings] =
    useState<VoiceSettings>(loadSettings);
  const [voices, setVoices] =
    useState<SpeechSynthesisVoice[]>([]);
  const [speaking, setSpeaking] = useState(false);
  const [elevenConfig, setElevenConfig] =
    useState<ElevenLabsVoiceConfig>(
      DEFAULT_ELEVEN_CONFIG,
    );
  const [elevenVoices, setElevenVoices] =
    useState<ElevenLabsVoice[]>([]);
  const [elevenLoading, setElevenLoading] =
    useState(false);
  const [elevenStatus, setElevenStatus] =
    useState("");
  const [audioStatus, setAudioStatus] =
    useState("Voice ready.");

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  const audioAbortRef =
    useRef<AbortController | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioSourceRef =
    useRef<AudioBufferSourceNode | null>(null);

  const getAudioContext = useCallback(() => {
    if (!audioContextRef.current) {
      const Context =
        window.AudioContext ||
        (
          window as typeof window & {
            webkitAudioContext?: typeof AudioContext;
          }
        ).webkitAudioContext;
      if (Context) {
        audioContextRef.current = new Context();
      }
    }
    return audioContextRef.current;
  }, []);

  useEffect(() => {
    const unlock = () => {
      const context = getAudioContext();
      if (context?.state === "suspended") {
        void context.resume().then(() => {
          setAudioStatus("Audio output ready.");
        });
      }
    };

    window.addEventListener("pointerdown", unlock);
    window.addEventListener("keydown", unlock);
    return () => {
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
    };
  }, [getAudioContext]);

  useEffect(() => {
    const synth = window.speechSynthesis;

    function refresh() {
      setVoices(synth.getVoices());
    }

    refresh();
    synth.addEventListener("voiceschanged", refresh);
    return () =>
      synth.removeEventListener("voiceschanged", refresh);
  }, []);

  useEffect(() => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify(settings),
    );
  }, [settings]);

  useEffect(() => {
    let active = true;
    api
      .elevenLabsVoiceConfig()
      .then((config) => {
        if (active) setElevenConfig(config);
      })
      .catch((error) => {
        if (active) {
          setElevenStatus(
            error instanceof Error
              ? error.message
              : String(error),
          );
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const selectedVoice = useMemo(() => {
    if (settings.voiceURI) {
      const exact = voices.find(
        (voice) =>
          voice.voiceURI === settings.voiceURI,
      );
      if (exact) return exact;
    }

    for (const hint of PREFERRED_VOICE_HINTS) {
      const preferred = voices.find(
        (voice) =>
          voice.name
            .toLowerCase()
            .includes(hint.toLowerCase()) &&
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
      voices.find((voice) =>
        voice.lang.toLowerCase().startsWith("en"),
      ) ||
      voices[0] ||
      null
    );
  }, [settings.voiceURI, voices]);

  const selectedElevenVoice = useMemo(
    () =>
      elevenVoices.find(
        (voice) =>
          voice.voice_id === elevenConfig.voice_id,
      ) || null,
    [elevenVoices, elevenConfig.voice_id],
  );

  const cleanupAudio = useCallback(() => {
    if (audioSourceRef.current) {
      try {
        audioSourceRef.current.stop();
      } catch {
        // Source may already have ended.
      }
      audioSourceRef.current.disconnect();
      audioSourceRef.current = null;
    }
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
      audioRef.current = null;
    }
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    window.speechSynthesis.cancel();
    audioAbortRef.current?.abort();
    audioAbortRef.current = null;
    cleanupAudio();
    setSpeaking(false);
  }, [cleanupAudio]);

  useEffect(
    () => () => {
      window.speechSynthesis.cancel();
      audioAbortRef.current?.abort();
      cleanupAudio();
      void audioContextRef.current?.close();
      audioContextRef.current = null;
    },
    [cleanupAudio],
  );

  const speakBrowserAsync = useCallback(
    async (cleaned: string) => {
      const synth = window.speechSynthesis;

      const speakOnce = (
        voice: SpeechSynthesisVoice | null,
      ) =>
        new Promise<boolean>((resolve) => {
          let started = false;
          let settled = false;
          const utterance =
            new SpeechSynthesisUtterance(cleaned);
          utterance.rate = settings.rate;
          utterance.pitch = settings.pitch;
          utterance.volume = Math.max(
            0.05,
            settings.volume,
          );
          if (voice) {
            utterance.voice = voice;
            utterance.lang = voice.lang;
          } else {
            utterance.lang = "en-GB";
          }

          const finish = (ok: boolean) => {
            if (settled) return;
            settled = true;
            window.clearTimeout(startTimer);
            setSpeaking(false);
            resolve(ok);
          };

          utterance.onstart = () => {
            started = true;
            setSpeaking(true);
            setAudioStatus(
              "System voice speaking" +
                (voice ? " · " + voice.name : "") +
                ".",
            );
          };
          utterance.onend = () => {
            setAudioStatus("Voice ready.");
            finish(true);
          };
          utterance.onerror = (event) => {
            setAudioStatus(
              "System voice error: " +
                (event.error || "unknown error"),
            );
            finish(false);
          };

          const startTimer = window.setTimeout(() => {
            if (!started) {
              synth.cancel();
              setAudioStatus(
                "System voice did not start; retrying.",
              );
              finish(false);
            }
          }, 1800);

          window.setTimeout(() => {
            synth.cancel();
            synth.resume();
            synth.speak(utterance);
          }, 40);
        });

      const first = await speakOnce(selectedVoice);
      if (!first && selectedVoice) {
        await speakOnce(null);
      }
    },
    [
      selectedVoice,
      settings.pitch,
      settings.rate,
      settings.volume,
    ],
  );

  const playElevenResponse = useCallback(
    async (
      response: Response,
      controller: AbortController,
    ) => {
      const bytes = await response.arrayBuffer();
      if (controller.signal.aborted) return;
      if (!bytes.byteLength) {
        throw new Error(
          "ElevenLabs returned an empty audio response.",
        );
      }

      const context = getAudioContext();
      if (context) {
        try {
          if (context.state === "suspended") {
            await context.resume();
          }

          const audioBuffer =
            await context.decodeAudioData(bytes.slice(0));
          if (controller.signal.aborted) return;

          const source = context.createBufferSource();
          const gain = context.createGain();
          gain.gain.value = Math.max(
            0.05,
            settings.volume,
          );
          source.buffer = audioBuffer;
          source.connect(gain);
          gain.connect(context.destination);
          audioSourceRef.current = source;

          await new Promise<void>((resolve) => {
            source.onended = () => resolve();
            source.start();
          });

          if (audioSourceRef.current === source) {
            audioSourceRef.current = null;
          }
          return;
        } catch (error) {
          setAudioStatus(
            "Web Audio playback failed; trying browser audio. " +
              (error instanceof Error
                ? error.message
                : String(error)),
          );
        }
      }

      cleanupAudio();
      const blob = new Blob([bytes], {
        type:
          response.headers.get("content-type") ||
          "audio/mpeg",
      });
      const url = URL.createObjectURL(blob);
      audioUrlRef.current = url;
      const audio = new Audio(url);
      audio.volume = Math.max(
        0.05,
        settings.volume,
      );
      audioRef.current = audio;

      await new Promise<void>((resolve, reject) => {
        audio.onended = () => resolve();
        audio.onerror = () =>
          reject(
            new Error(
              "Unable to play ElevenLabs audio.",
            ),
          );
        audio.play().catch(reject);
      });
    },
    [
      cleanupAudio,
      getAudioContext,
      settings.volume,
    ],
  );

  const speakElevenAsync = useCallback(
    async (cleaned: string) => {
      stop();
      if (
        !elevenConfig.has_secret ||
        !elevenConfig.voice_id
      ) {
        setElevenStatus(
          "Configure an ElevenLabs API key and voice first.",
        );
        await speakBrowserAsync(cleaned);
        return;
      }

      const controller = new AbortController();
      audioAbortRef.current = controller;
      setSpeaking(true);
      setAudioStatus("Generating ElevenLabs voice...");
      setElevenStatus("Generating ElevenLabs voice...");

      try {
        const response =
          await api.streamElevenLabsSpeech(
            cleaned,
            controller.signal,
          );

        setAudioStatus("Playing ElevenLabs voice...");
        setElevenStatus(
          "ElevenLabs audio received.",
        );
        await playElevenResponse(
          response,
          controller,
        );

        setAudioStatus("Voice ready.");
        setElevenStatus("ElevenLabs voice ready.");
      } catch (error) {
        if (!controller.signal.aborted) {
          setAudioStatus(
            "ElevenLabs failed; using system voice.",
          );
          setElevenStatus(
            "ElevenLabs failed; using system voice. " +
              (error instanceof Error
                ? error.message
                : String(error)),
          );
          await speakBrowserAsync(cleaned);
        }
      } finally {
        if (
          audioAbortRef.current === controller
        ) {
          audioAbortRef.current = null;
        }
        cleanupAudio();
        setSpeaking(false);
      }
    },
    [
      cleanupAudio,
      elevenConfig.has_secret,
      elevenConfig.voice_id,
      settings.volume,
      playElevenResponse,
      speakBrowserAsync,
      stop,
    ],
  );

  const speakAsync = useCallback(
    async (text: string, force = false) => {
      const cleaned = text.trim();
      if (!cleaned) return;

      if (
        !force &&
        (!settings.enabled || !settings.autoSpeak)
      ) {
        return;
      }

      if (settings.engine === "elevenlabs") {
        await speakElevenAsync(cleaned);
        return;
      }

      stop();
      await speakBrowserAsync(cleaned);
    },
    [
      settings.autoSpeak,
      settings.enabled,
      settings.engine,
      speakBrowserAsync,
      speakElevenAsync,
      stop,
    ],
  );

  const speak = useCallback(
    (text: string, force = false) => {
      void speakAsync(text, force);
    },
    [speakAsync],
  );

  useEffect(() => {
    function onSpeak(event: Event) {
      const detail = (
        event as CustomEvent<{ text?: string }>
      ).detail;
      if (detail?.text) {
        speak(detail.text);
      }
    }

    window.addEventListener(
      SPEAK_EVENT,
      onSpeak,
    );
    return () =>
      window.removeEventListener(
        SPEAK_EVENT,
        onSpeak,
      );
  }, [speak]);

  const refreshElevenVoices = useCallback(
    async () => {
      setElevenLoading(true);
      setElevenStatus("Loading ElevenLabs voices...");
      try {
        const loaded =
          await api.elevenLabsVoices();
        setElevenVoices(loaded);
        setElevenStatus(
          "Loaded " +
            loaded.length +
            " ElevenLabs voices.",
        );
        return loaded;
      } catch (error) {
        setElevenStatus(
          error instanceof Error
            ? error.message
            : String(error),
        );
        return [];
      } finally {
        setElevenLoading(false);
      }
    },
    [],
  );

  const saveElevenLabs = useCallback(
    async (payload: {
      apiKey?: string;
      voiceId?: string;
      modelId?: string;
      outputFormat?: string;
      clearSecret?: boolean;
    }) => {
      setElevenLoading(true);
      setElevenStatus(
        "Saving ElevenLabs voice configuration...",
      );
      try {
        const config =
          await api.configureElevenLabsVoice({
            voice_id:
              payload.voiceId ??
              elevenConfig.voice_id,
            model_id:
              payload.modelId ??
              elevenConfig.model_id,
            output_format:
              payload.outputFormat ??
              elevenConfig.output_format,
            api_key: payload.apiKey || undefined,
            clear_secret:
              payload.clearSecret || false,
          });
        setElevenConfig(config);
        setElevenStatus(
          "ElevenLabs configuration saved.",
        );
        return config;
      } catch (error) {
        setElevenStatus(
          error instanceof Error
            ? error.message
            : String(error),
        );
        return elevenConfig;
      } finally {
        setElevenLoading(false);
      }
    },
    [elevenConfig],
  );

  const testElevenLabs =
    useCallback(async () => {
      setElevenLoading(true);
      setElevenStatus(
        "Testing ElevenLabs connection...",
      );
      try {
        const result =
          await api.testElevenLabsVoice();
        setElevenStatus(
          result.ok
            ? "ElevenLabs connected."
            : "ElevenLabs test failed.",
        );
        return result.ok;
      } catch (error) {
        setElevenStatus(
          error instanceof Error
            ? error.message
            : String(error),
        );
        return false;
      } finally {
        setElevenLoading(false);
      }
    }, []);

  const testVoice = useCallback(() => {
    setAudioStatus("Testing voice output...");
    void speakAsync(
      "Agent Man online. Systems linked. Standing by for your directive.",
      true,
    );
  }, [speakAsync]);

  function update(
    patch: Partial<VoiceSettings>,
  ) {
    setSettings((current) => ({
      ...current,
      ...patch,
    }));
  }

  function resetSignature() {
    setSettings((current) => ({
      ...current,
      enabled: true,
      autoSpeak: true,
      rate: DEFAULT_SETTINGS.rate,
      pitch: DEFAULT_SETTINGS.pitch,
      volume: DEFAULT_SETTINGS.volume,
      voiceURI:
        selectedVoice?.voiceURI ||
        current.voiceURI,
    }));
  }

  return {
    settings,
    voices,
    selectedVoice,
    selectedElevenVoice,
    speaking,
    elevenConfig,
    elevenVoices,
    elevenLoading,
    elevenStatus,
    audioStatus,
    update,
    speak,
    speakAsync,
    stop,
    testVoice,
    resetSignature,
    refreshElevenVoices,
    saveElevenLabs,
    testElevenLabs,
  };
}
