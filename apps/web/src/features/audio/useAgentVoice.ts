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

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  const audioAbortRef =
    useRef<AbortController | null>(null);

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
    },
    [cleanupAudio],
  );

  const speakBrowserAsync = useCallback(
    (cleaned: string) =>
      new Promise<void>((resolve) => {
        const synth = window.speechSynthesis;
        synth.cancel();

        const utterance =
          new SpeechSynthesisUtterance(cleaned);
        utterance.rate = settings.rate;
        utterance.pitch = settings.pitch;
        utterance.volume = settings.volume;
        if (selectedVoice) {
          utterance.voice = selectedVoice;
          utterance.lang = selectedVoice.lang;
        } else {
          utterance.lang = "en-GB";
        }

        utterance.onstart = () =>
          setSpeaking(true);
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
      const canStream =
        Boolean(response.body) &&
        typeof MediaSource !== "undefined" &&
        MediaSource.isTypeSupported("audio/mpeg");

      if (!canStream || !response.body) {
        const blob = await response.blob();
        if (controller.signal.aborted) return;

        cleanupAudio();
        const url = URL.createObjectURL(blob);
        audioUrlRef.current = url;

        const audio = new Audio(url);
        audio.volume = settings.volume;
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
        return;
      }

      cleanupAudio();
      const mediaSource = new MediaSource();
      const url = URL.createObjectURL(mediaSource);
      audioUrlRef.current = url;

      const audio = new Audio(url);
      audio.volume = settings.volume;
      audioRef.current = audio;

      const ended = new Promise<void>(
        (resolve, reject) => {
          audio.onended = () => resolve();
          audio.onerror = () =>
            reject(
              new Error(
                "Unable to play ElevenLabs audio stream.",
              ),
            );
        },
      );

      await new Promise<void>((resolve, reject) => {
        mediaSource.addEventListener(
          "sourceopen",
          () => resolve(),
          { once: true },
        );
        mediaSource.addEventListener(
          "sourceclose",
          () => {
            if (!controller.signal.aborted) {
              reject(
                new Error(
                  "ElevenLabs media stream closed early.",
                ),
              );
            }
          },
          { once: true },
        );
      });

      if (controller.signal.aborted) return;

      const sourceBuffer =
        mediaSource.addSourceBuffer("audio/mpeg");
      const reader = response.body.getReader();
      let playbackStarted = false;

      const append = (chunk: Uint8Array) =>
        new Promise<void>((resolve, reject) => {
          const onDone = () => {
            cleanupListeners();
            resolve();
          };
          const onError = () => {
            cleanupListeners();
            reject(
              new Error(
                "Unable to buffer ElevenLabs audio.",
              ),
            );
          };
          const cleanupListeners = () => {
            sourceBuffer.removeEventListener(
              "updateend",
              onDone,
            );
            sourceBuffer.removeEventListener(
              "error",
              onError,
            );
          };

          sourceBuffer.addEventListener(
            "updateend",
            onDone,
          );
          sourceBuffer.addEventListener(
            "error",
            onError,
          );
          const safeChunk = new Uint8Array(
            chunk.byteLength,
          );
          safeChunk.set(chunk);
          sourceBuffer.appendBuffer(
            safeChunk.buffer,
          );
        });

      try {
        while (!controller.signal.aborted) {
          const { done, value } =
            await reader.read();
          if (done) break;
          if (!value?.byteLength) continue;

          await append(value);

          if (!playbackStarted) {
            await audio.play();
            playbackStarted = true;
          }
        }

        if (
          !controller.signal.aborted &&
          mediaSource.readyState === "open"
        ) {
          mediaSource.endOfStream();
        }

        if (
          !controller.signal.aborted &&
          !playbackStarted
        ) {
          await audio.play();
        }

        if (!controller.signal.aborted) {
          await ended;
        }
      } finally {
        if (controller.signal.aborted) {
          await reader.cancel().catch(() => undefined);
        }
      }
    },
    [cleanupAudio, settings.volume],
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
      setElevenStatus("Generating ElevenLabs voice...");

      try {
        const response =
          await api.streamElevenLabsSpeech(
            cleaned,
            controller.signal,
          );

        setElevenStatus(
          "ElevenLabs audio streaming...",
        );
        await playElevenResponse(
          response,
          controller,
        );

        setElevenStatus("ElevenLabs voice ready.");
      } catch (error) {
        if (!controller.signal.aborted) {
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
