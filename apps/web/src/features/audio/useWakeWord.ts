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

const COMMAND_SILENCE_MS = 1150;
const RESTART_DELAY_MS = 320;

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

function wakeIndex(transcript: string, wakePhrase: string) {
  const source = normalized(transcript);
  const wake = normalized(wakePhrase);
  if (!wake) return null;
  const index = source.indexOf(wake);
  if (index < 0) return null;
  return {
    source,
    remainder: source.slice(index + wake.length).trim(),
  };
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
  const intentionalStopRef = useRef(false);
  const commandSubmittedRef = useRef(false);
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

  const destroyRecognition = useCallback(() => {
    if (recognitionRef.current) {
      intentionalStopRef.current = true;
      try {
        recognitionRef.current.abort();
      } catch {
        // Browser may already have ended recognition.
      }
      recognitionRef.current = null;
    }
  }, []);

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

      if (recognitionRef.current) {
        intentionalStopRef.current = true;
        try {
          recognitionRef.current.stop();
        } catch {
          // Ignore stop races.
        }
      }

      Promise.resolve(onCommandRef.current(command))
        .catch(() => undefined)
        .finally(() => {
          if (!enabledRef.current) return;
          modeRef.current = "standby";
          restartTimerRef.current = window.setTimeout(() => {
            startModeRef.current?.("standby");
          }, RESTART_DELAY_MS);
        });
    },
    [clearTimers],
  );

  const armSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current !== null) {
      window.clearTimeout(silenceTimerRef.current);
    }
    silenceTimerRef.current = window.setTimeout(() => {
      submitCommand();
    }, COMMAND_SILENCE_MS);
  }, [submitCommand]);

  const startMode = useCallback(
    (mode: "standby" | "command") => {
      const Constructor = recognitionConstructor();
      if (!Constructor || !enabledRef.current) return;

      destroyRecognition();
      clearTimers();

      const recognition = new Constructor();
      recognition.continuous = mode === "standby";
      recognition.interimResults = true;
      recognition.lang = languageRef.current;
      recognition.maxAlternatives = 3;
      recognitionRef.current = recognition;
      modeRef.current = mode;
      intentionalStopRef.current = false;

      if (mode === "command") {
        commandSubmittedRef.current = false;
        commandFinalPartsRef.current = [];
        commandInterimRef.current = "";
        setLiveTranscript("");
        setFinalTranscript("");
      }

      recognition.onstart = () => {
        setErrorMessage("");
        setState(mode === "command" ? "listening" : "standby");
      };

      recognition.onresult = (event) => {
        let interim = "";
        const freshFinals: string[] = [];

        for (
          let index = event.resultIndex;
          index < event.results.length;
          index += 1
        ) {
          const result = event.results[index];
          const transcript = result?.[0]?.transcript?.trim() || "";
          if (!transcript) continue;

          if (result.isFinal) {
            freshFinals.push(transcript);
          } else {
            interim = joinParts([interim, transcript]);
          }
        }

        if (modeRef.current === "standby") {
          const heard = joinParts([...freshFinals, interim]);
          if (!heard) return;
          setLiveTranscript(heard);

          const wake = wakeIndex(heard, wakePhraseRef.current);
          if (!wake) {
            if (freshFinals.length > 0) {
              setLastHeard(joinParts(freshFinals));
            }
            return;
          }

          setLastHeard(heard);

          if (wake.remainder) {
            setFinalTranscript(wake.remainder);
            setLiveTranscript("");
            submitCommand(wake.remainder);
            return;
          }

          intentionalStopRef.current = true;
          try {
            recognition.stop();
          } catch {
            // Ignore stop races.
          }
          setState("waking");

          Promise.resolve(onWakeRef.current())
            .catch(() => undefined)
            .finally(() => {
              if (!enabledRef.current) return;
              restartTimerRef.current = window.setTimeout(() => {
                startMode("command");
              }, 160);
            });
          return;
        }

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
        if (intentionalStopRef.current) return;

        if (
          event.error === "not-allowed" ||
          event.error === "service-not-allowed"
        ) {
          setErrorMessage(
            "Microphone access is blocked. Allow microphone permission for Agent Man.",
          );
          setState("error");
          enabledRef.current = false;
          return;
        }

        if (event.error === "no-speech") {
          if (modeRef.current === "command") {
            setErrorMessage("No speech detected. Listening again...");
          }
          return;
        }

        setErrorMessage("Speech recognition error: " + event.error);
        setState("error");
      };

      recognition.onend = () => {
        recognitionRef.current = null;

        if (intentionalStopRef.current) {
          intentionalStopRef.current = false;
          return;
        }

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
            return;
          }

          restartTimerRef.current = window.setTimeout(() => {
            startMode("command");
          }, RESTART_DELAY_MS);
          return;
        }

        restartTimerRef.current = window.setTimeout(() => {
          startMode("standby");
        }, RESTART_DELAY_MS);
      };

      try {
        recognition.start();
      } catch {
        setErrorMessage("Unable to start microphone recognition.");
        setState("error");
      }
    },
    [
      armSilenceTimer,
      clearTimers,
      destroyRecognition,
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
    destroyRecognition();
    commandFinalPartsRef.current = [];
    commandInterimRef.current = "";
    setLiveTranscript("");
    setState(supported ? "off" : "unsupported");
  }, [clearTimers, destroyRecognition, supported]);

  const listenNow = useCallback(async () => {
    if (!supported) return;
    enabledRef.current = true;
    clearTimers();
    destroyRecognition();
    setState("waking");
    setLiveTranscript("");
    setFinalTranscript("");
    setErrorMessage("");

    await Promise.resolve(onWakeRef.current()).catch(() => undefined);

    if (!enabledRef.current) return;
    restartTimerRef.current = window.setTimeout(() => {
      startMode("command");
    }, 160);
  }, [clearTimers, destroyRecognition, startMode, supported]);

  useEffect(() => {
    enabledRef.current = enabled;

    if (!supported) {
      setState("unsupported");
      return;
    }

    if (enabled) {
      startMode("standby");
    } else {
      stop();
    }

    return () => {
      clearTimers();
      destroyRecognition();
    };
  }, [
    enabled,
    language,
    wakePhrase,
    supported,
    startMode,
    stop,
    clearTimers,
    destroyRecognition,
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
