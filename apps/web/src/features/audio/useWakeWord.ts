import { useCallback, useEffect, useRef, useState } from "react";

type WakeState =
  | "unsupported"
  | "off"
  | "standby"
  | "waking"
  | "listening"
  | "error";

type RecognitionAlternativeLike = {
  transcript: string;
};

type RecognitionResultLike = {
  isFinal: boolean;
  0: RecognitionAlternativeLike;
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
  onCommand: (command: string) => void;
};

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

function commandAfterWake(transcript: string, wakePhrase: string) {
  const source = normalized(transcript);
  const wake = normalized(wakePhrase);
  const index = source.indexOf(wake);
  if (index < 0) return null;
  return source.slice(index + wake.length).trim();
}

export function useWakeWord({
  enabled,
  wakePhrase,
  language = "en-IN",
  onWake,
  onCommand,
}: Props) {
  const [state, setState] = useState<WakeState>(
    recognitionConstructor() ? "off" : "unsupported",
  );
  const [lastHeard, setLastHeard] = useState("");
  const recognitionRef = useRef<RecognitionLike | null>(null);
  const shouldRunRef = useRef(false);
  const awaitingCommandRef = useRef(false);
  const restartingRef = useRef(false);
  const onWakeRef = useRef(onWake);
  const onCommandRef = useRef(onCommand);
  const wakePhraseRef = useRef(wakePhrase);

  useEffect(() => {
    onWakeRef.current = onWake;
  }, [onWake]);

  useEffect(() => {
    onCommandRef.current = onCommand;
  }, [onCommand]);

  useEffect(() => {
    wakePhraseRef.current = wakePhrase;
  }, [wakePhrase]);

  const startRecognition = useCallback(() => {
    const recognition = recognitionRef.current;
    if (!recognition || !shouldRunRef.current) return;
    try {
      recognition.start();
      setState(
        awaitingCommandRef.current ? "listening" : "standby",
      );
    } catch {
      // Some browsers throw when start() races an existing session.
    }
  }, []);

  const stop = useCallback(() => {
    shouldRunRef.current = false;
    awaitingCommandRef.current = false;
    restartingRef.current = false;
    recognitionRef.current?.abort();
    setState(recognitionConstructor() ? "off" : "unsupported");
  }, []);

  const listenNow = useCallback(async () => {
    if (!recognitionRef.current) return;
    shouldRunRef.current = true;
    awaitingCommandRef.current = true;
    restartingRef.current = true;
    recognitionRef.current.abort();
    setState("waking");
    await onWakeRef.current();
    restartingRef.current = false;
    window.setTimeout(() => {
      startRecognition();
    }, 180);
  }, [startRecognition]);

  useEffect(() => {
    const Constructor = recognitionConstructor();
    if (!Constructor) {
      setState("unsupported");
      return;
    }

    const recognition = new Constructor();
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.lang = language;
    recognitionRef.current = recognition;

    recognition.onresult = (event) => {
      for (
        let index = event.resultIndex;
        index < event.results.length;
        index += 1
      ) {
        const result = event.results[index];
        if (!result?.isFinal) continue;

        const transcript = result[0]?.transcript?.trim() || "";
        if (!transcript) continue;
        setLastHeard(transcript);

        if (awaitingCommandRef.current) {
          const remainder = commandAfterWake(
            transcript,
            wakePhraseRef.current,
          );
          const command = remainder !== null ? remainder : transcript;
          if (command.trim()) {
            awaitingCommandRef.current = false;
            setState("standby");
            onCommandRef.current(command.trim());
          }
          continue;
        }

        const remainder = commandAfterWake(
          transcript,
          wakePhraseRef.current,
        );
        if (remainder === null) continue;

        if (remainder) {
          onCommandRef.current(remainder);
          setState("standby");
          continue;
        }

        awaitingCommandRef.current = true;
        setState("waking");
        restartingRef.current = true;
        recognition.stop();

        Promise.resolve(onWakeRef.current()).finally(() => {
          restartingRef.current = false;
          window.setTimeout(() => {
            startRecognition();
          }, 180);
        });
      }
    };

    recognition.onerror = (event) => {
      if (
        event.error === "not-allowed" ||
        event.error === "service-not-allowed"
      ) {
        shouldRunRef.current = false;
        awaitingCommandRef.current = false;
        setState("error");
        return;
      }

      if (shouldRunRef.current) {
        setState("error");
      }
    };

    recognition.onend = () => {
      if (
        shouldRunRef.current &&
        !restartingRef.current
      ) {
        window.setTimeout(() => {
          startRecognition();
        }, 250);
      }
    };

    if (enabled) {
      shouldRunRef.current = true;
      startRecognition();
    } else {
      stop();
    }

    return () => {
      shouldRunRef.current = false;
      recognition.abort();
      recognitionRef.current = null;
    };
  }, [enabled, language, startRecognition, stop]);

  return {
    supported: state !== "unsupported",
    state,
    lastHeard,
    listeningForCommand: state === "listening",
    listenNow,
    stop,
  };
}
