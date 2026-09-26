import { useCallback, useEffect, useRef, useState } from "react";

export type WakeState =
  | "unsupported"
  | "off"
  | "standby"
  | "waking"
  | "listening"
  | "processing"
  | "error";

type RecognitionAlternativeLike = {
  transcript: string;
  confidence?: number;
};

type RecognitionResultLike = {
  isFinal: boolean;
  length: number;
  [index: number]: RecognitionAlternativeLike;
};

type RecognitionEventLike = Event & {
  resultIndex: number;
  results: ArrayLike<RecognitionResultLike>;
};

type RecognitionErrorEventLike = Event & {
  error: string;
};

type RecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives?: number;
  onstart: (() => void) | null;
  onresult: ((event: RecognitionEventLike) => void) | null;
  onerror: ((event: RecognitionErrorEventLike) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};

type RecognitionConstructor = new () => RecognitionLike;

type Props = {
  enabled: boolean;
  wakePhrase: string;
  language?: string;
  onWake: () => Promise<void> | void;
  onCommand: (command: string) => Promise<void> | void;
};

const COMMAND_SILENCE_MS = 1250;
const RESTART_DELAY_MS = 650;
const MIN_RESTART_GAP_MS = 500;

function recognitionConstructor(): RecognitionConstructor | null {
  const speechWindow = window as Window & {
    SpeechRecognition?: RecognitionConstructor;
    webkitSpeechRecognition?: RecognitionConstructor;
  };
  return (
    speechWindow.SpeechRecognition ||
    speechWindow.webkitSpeechRecognition ||
    null
  );
}

function normalized(value: string) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function compact(value: string) {
  return normalized(value).replace(/\s+/g, "");
}

function levenshtein(a: string, b: string) {
  if (a === b) return 0;
  if (!a.length) return b.length;
  if (!b.length) return a.length;

  const previous = Array.from(
    { length: b.length + 1 },
    (_, index) => index,
  );

  for (let i = 1; i <= a.length; i += 1) {
    let diagonal = previous[0];
    previous[0] = i;

    for (let j = 1; j <= b.length; j += 1) {
      const old = previous[j];
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      previous[j] = Math.min(
        previous[j] + 1,
        previous[j - 1] + 1,
        diagonal + cost,
      );
      diagonal = old;
    }
  }

  return previous[b.length];
}

function wakeCandidates(wakePhrase: string) {
  const wake = normalized(wakePhrase);
  const withoutHey = wake.replace(/^hey\s+/, "").trim();
  const candidates = new Set<string>([wake]);

  if (withoutHey) {
    candidates.add(withoutHey);
    candidates.add("hey " + withoutHey);
  }

  if (withoutHey === "agent man") {
    candidates.add("agentman");
    candidates.add("hey agentman");
    candidates.add("agent men");
    candidates.add("hey agent men");
  }

  return Array.from(candidates).filter(Boolean);
}

function findWake(transcript: string, wakePhrase: string) {
  const source = normalized(transcript);
  if (!source) return null;

  const sourceTokens = source.split(" ");
  const candidates = wakeCandidates(wakePhrase);

  for (const candidate of candidates) {
    const directIndex = source.indexOf(candidate);
    if (directIndex >= 0) {
      return {
        matched: candidate,
        remainder: source
          .slice(directIndex + candidate.length)
          .trim(),
      };
    }

    if (compact(source).includes(compact(candidate))) {
      const candidateTokens = candidate.split(" ");
      const size = candidateTokens.length;
      for (let start = 0; start < sourceTokens.length; start += 1) {
        for (
          let length = Math.max(1, size - 1);
          length <= size + 1 && start + length <= sourceTokens.length;
          length += 1
        ) {
          const windowText = sourceTokens
            .slice(start, start + length)
            .join(" ");
          if (compact(windowText) === compact(candidate)) {
            return {
              matched: windowText,
              remainder: sourceTokens
                .slice(start + length)
                .join(" ")
                .trim(),
            };
          }
        }
      }
    }

    const candidateTokens = candidate.split(" ");
    const size = candidateTokens.length;

    for (let start = 0; start < sourceTokens.length; start += 1) {
      for (
        let length = Math.max(1, size - 1);
        length <= size + 1 && start + length <= sourceTokens.length;
        length += 1
      ) {
        const windowTokens = sourceTokens.slice(
          start,
          start + length,
        );
        const windowText = windowTokens.join(" ");
        const a = compact(windowText);
        const b = compact(candidate);
        const maxDistance = Math.max(1, Math.floor(b.length * 0.16));

        if (
          Math.abs(a.length - b.length) <= maxDistance &&
          levenshtein(a, b) <= maxDistance
        ) {
          return {
            matched: windowText,
            remainder: sourceTokens
              .slice(start + length)
              .join(" ")
              .trim(),
          };
        }
      }
    }
  }

  return null;
}

function joinParts(parts: string[]) {
  return parts
    .map((part) => part.trim())
    .filter(Boolean)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
}

export function useWakeWord({
  enabled,
  wakePhrase,
  language = "en-IN",
  onWake,
  onCommand,
}: Props) {
  const supported = Boolean(recognitionConstructor());
  const [state, setState] = useState<WakeState>(
    supported ? "off" : "unsupported",
  );
  const [lastHeard, setLastHeard] = useState("");
  const [liveTranscript, setLiveTranscript] = useState("");
  const [finalTranscript, setFinalTranscript] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  const recognitionRef = useRef<RecognitionLike | null>(null);
  const activeSessionRef = useRef(0);
  const modeRef = useRef<"standby" | "command" | "off">("off");
  const enabledRef = useRef(enabled);
  const onWakeRef = useRef(onWake);
  const onCommandRef = useRef(onCommand);
  const wakePhraseRef = useRef(wakePhrase);
  const languageRef = useRef(language);
  const commandFinalPartsRef = useRef<string[]>([]);
  const commandInterimRef = useRef("");
  const silenceTimerRef = useRef<number | null>(null);
  const restartTimerRef = useRef<number | null>(null);
  const commandSubmittedRef = useRef(false);
  const lastStartAtRef = useRef(0);
  const startModeRef = useRef<
    ((mode: "standby" | "command") => void) | null
  >(null);

  useEffect(() => {
    enabledRef.current = enabled;
  }, [enabled]);

  useEffect(() => {
    onWakeRef.current = onWake;
  }, [onWake]);

  useEffect(() => {
    onCommandRef.current = onCommand;
  }, [onCommand]);

  useEffect(() => {
    wakePhraseRef.current = wakePhrase;
  }, [wakePhrase]);

  useEffect(() => {
    languageRef.current = language;
  }, [language]);

  const clearTimers = useCallback(() => {
    if (silenceTimerRef.current !== null) {
      window.clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
    if (restartTimerRef.current !== null) {
      window.clearTimeout(restartTimerRef.current);
      restartTimerRef.current = null;
    }
  }, []);

  const invalidateRecognition = useCallback(() => {
    activeSessionRef.current += 1;
    const recognition = recognitionRef.current;
    recognitionRef.current = null;

    if (recognition) {
      recognition.onstart = null;
      recognition.onresult = null;
      recognition.onerror = null;
      recognition.onend = null;
      try {
        recognition.abort();
      } catch {
        // Already stopped.
      }
    }
  }, []);

  const scheduleStart = useCallback(
    (
      mode: "standby" | "command",
      delay = RESTART_DELAY_MS,
    ) => {
      if (!enabledRef.current) return;

      if (restartTimerRef.current !== null) {
        window.clearTimeout(restartTimerRef.current);
      }

      const elapsed = Date.now() - lastStartAtRef.current;
      const safeDelay = Math.max(
        delay,
        MIN_RESTART_GAP_MS - elapsed,
        0,
      );

      restartTimerRef.current = window.setTimeout(() => {
        restartTimerRef.current = null;
        startModeRef.current?.(mode);
      }, safeDelay);
    },
    [],
  );

  const submitCommand = useCallback(
    (override?: string) => {
      if (commandSubmittedRef.current) return;

      const command =
        override?.trim() ||
        joinParts([
          ...commandFinalPartsRef.current,
          commandInterimRef.current,
        ]);

      if (!command) return;

      commandSubmittedRef.current = true;
      clearTimers();
      setFinalTranscript(command);
      setLiveTranscript("");
      setLastHeard(command);
      commandFinalPartsRef.current = [];
      commandInterimRef.current = "";
      modeRef.current = "off";
      setState("processing");
      invalidateRecognition();

      Promise.resolve(onCommandRef.current(command))
        .catch(() => undefined)
        .finally(() => {
          if (!enabledRef.current) return;
          modeRef.current = "standby";
          scheduleStart("standby");
        });
    },
    [
      clearTimers,
      invalidateRecognition,
      scheduleStart,
    ],
  );

  const armSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current !== null) {
      window.clearTimeout(silenceTimerRef.current);
    }
    silenceTimerRef.current = window.setTimeout(() => {
      silenceTimerRef.current = null;
      submitCommand();
    }, COMMAND_SILENCE_MS);
  }, [submitCommand]);

  const startMode = useCallback(
    (mode: "standby" | "command") => {
      const Constructor = recognitionConstructor();
      if (!Constructor || !enabledRef.current) return;

      clearTimers();
      invalidateRecognition();

      const sessionId = activeSessionRef.current + 1;
      activeSessionRef.current = sessionId;
      lastStartAtRef.current = Date.now();

      const recognition = new Constructor();
      recognition.continuous = mode === "standby";
      recognition.interimResults = mode === "command";
      recognition.lang = languageRef.current;
      recognition.maxAlternatives = 3;
      recognitionRef.current = recognition;
      modeRef.current = mode;

      if (mode === "command") {
        commandSubmittedRef.current = false;
        commandFinalPartsRef.current = [];
        commandInterimRef.current = "";
        setLiveTranscript("");
        setFinalTranscript("");
      } else {
        setLiveTranscript("");
      }

      const isCurrent = () =>
        sessionId === activeSessionRef.current &&
        recognitionRef.current === recognition;

      recognition.onstart = () => {
        if (!isCurrent()) return;
        setErrorMessage("");
        setState(
          mode === "command" ? "listening" : "standby",
        );
      };

      recognition.onresult = (event) => {
        if (!isCurrent()) return;

        let interim = "";
        const freshFinals: string[] = [];

        for (
          let index = event.resultIndex;
          index < event.results.length;
          index += 1
        ) {
          const result = event.results[index];
          if (!result) continue;

          const alternatives = Array.from(
            { length: Math.min(result.length || 1, 3) },
            (_, alternativeIndex) =>
              result[alternativeIndex]?.transcript?.trim() || "",
          ).filter(Boolean);

          const transcript = alternatives[0] || "";
          if (!transcript) continue;

          if (modeRef.current === "standby") {
            const wakeMatch =
              alternatives
                .map((item) =>
                  findWake(item, wakePhraseRef.current),
                )
                .find(Boolean) || null;

            if (wakeMatch) {
              setLastHeard(transcript);
              setLiveTranscript("");

              if (wakeMatch.remainder) {
                setFinalTranscript(wakeMatch.remainder);
                submitCommand(wakeMatch.remainder);
                return;
              }

              setState("waking");
              modeRef.current = "off";
              invalidateRecognition();

              Promise.resolve(onWakeRef.current())
                .catch(() => undefined)
                .finally(() => {
                  if (!enabledRef.current) return;
                  scheduleStart("command", 220);
                });
              return;
            }

            if (result.isFinal) {
              setLastHeard(transcript);
            }
            continue;
          }

          if (result.isFinal) {
            freshFinals.push(transcript);
          } else {
            interim = joinParts([interim, transcript]);
          }
        }

        if (modeRef.current !== "command") return;

        if (freshFinals.length > 0) {
          commandFinalPartsRef.current.push(...freshFinals);
        }
        commandInterimRef.current = interim;

        const combined = joinParts([
          ...commandFinalPartsRef.current,
          interim,
        ]);

        if (combined) {
          setLiveTranscript(combined);
          setLastHeard(combined);
          armSilenceTimer();
        }
      };

      recognition.onerror = (event) => {
        if (!isCurrent()) return;

        if (
          event.error === "not-allowed" ||
          event.error === "service-not-allowed"
        ) {
          setErrorMessage(
            "Microphone permission is blocked. Allow microphone access, then turn Wake Mode off and on.",
          );
          setState("error");
          enabledRef.current = false;
          modeRef.current = "off";
          invalidateRecognition();
          return;
        }

        if (event.error === "no-speech") {
          if (modeRef.current === "command") {
            setErrorMessage(
              "I did not hear a command. Still listening...",
            );
          }
          return;
        }

        if (
          event.error === "aborted" ||
          event.error === "network"
        ) {
          return;
        }

        setErrorMessage(
          "Speech recognition error: " + event.error,
        );
      };

      recognition.onend = () => {
        if (!isCurrent()) return;

        recognitionRef.current = null;

        if (!enabledRef.current) {
          setState("off");
          return;
        }

        if (modeRef.current === "command") {
          const command = joinParts([
            ...commandFinalPartsRef.current,
            commandInterimRef.current,
          ]);

          if (command) {
            submitCommand(command);
          } else {
            scheduleStart("command");
          }
          return;
        }

        if (modeRef.current === "standby") {
          scheduleStart("standby");
        }
      };

      try {
        recognition.start();
      } catch {
        if (!isCurrent()) return;
        setErrorMessage(
          "Microphone recognition could not start. Retrying...",
        );
        scheduleStart(mode, 900);
      }
    },
    [
      armSilenceTimer,
      clearTimers,
      invalidateRecognition,
      scheduleStart,
      submitCommand,
    ],
  );

  useEffect(() => {
    startModeRef.current = startMode;
  }, [startMode]);

  const stop = useCallback(() => {
    enabledRef.current = false;
    modeRef.current = "off";
    clearTimers();
    invalidateRecognition();
    commandFinalPartsRef.current = [];
    commandInterimRef.current = "";
    commandSubmittedRef.current = false;
    setLiveTranscript("");
    setState(supported ? "off" : "unsupported");
  }, [
    clearTimers,
    invalidateRecognition,
    supported,
  ]);

  const listenNow = useCallback(async () => {
    if (!supported) return;

    enabledRef.current = true;
    clearTimers();
    invalidateRecognition();
    modeRef.current = "off";
    setState("waking");
    setLiveTranscript("");
    setFinalTranscript("");
    setErrorMessage("");

    await Promise.resolve(onWakeRef.current()).catch(
      () => undefined,
    );

    if (!enabledRef.current) return;
    scheduleStart("command", 220);
  }, [
    clearTimers,
    invalidateRecognition,
    scheduleStart,
    supported,
  ]);

  useEffect(() => {
    enabledRef.current = enabled;

    if (!supported) {
      setState("unsupported");
      return;
    }

    if (enabled) {
      scheduleStart("standby", 0);
    } else {
      stop();
    }

    return () => {
      clearTimers();
      invalidateRecognition();
    };
  }, [
    enabled,
    language,
    wakePhrase,
    supported,
    scheduleStart,
    stop,
    clearTimers,
    invalidateRecognition,
  ]);

  return {
    supported,
    state,
    lastHeard,
    liveTranscript,
    finalTranscript,
    errorMessage,
    listeningForCommand: state === "listening",
    listenNow,
    stop,
  };
}
