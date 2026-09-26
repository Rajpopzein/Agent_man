import {
  useEffect,
  useState,
} from "react";
import {
  KeyRound,
  Mic,
  MicOff,
  Radio,
  RefreshCw,
  RotateCcw,
  Save,
  Square,
  Volume2,
  VolumeX,
} from "lucide-react";

import HudModal from "../../components/HudModal";
import {
  ElevenLabsVoice,
  ElevenLabsVoiceConfig,
} from "../../services/api";
import { VoiceSettings } from "./useAgentVoice";
import { WakeState } from "./useWakeWord";

type Props = {
  open: boolean;
  onClose: () => void;
  settings: VoiceSettings;
  voices: SpeechSynthesisVoice[];
  selectedVoice: SpeechSynthesisVoice | null;
  speaking: boolean;
  wakeSupported: boolean;
  wakeState: WakeState;
  lastHeard: string;
  liveTranscript: string;
  finalTranscript: string;
  errorMessage: string;
  elevenConfig: ElevenLabsVoiceConfig;
  elevenVoices: ElevenLabsVoice[];
  selectedElevenVoice: ElevenLabsVoice | null;
  elevenLoading: boolean;
  elevenStatus: string;
  audioStatus: string;
  onUpdate: (patch: Partial<VoiceSettings>) => void;
  onTest: () => void;
  onStop: () => void;
  onReset: () => void;
  onListenNow: () => void;
  onRefreshElevenVoices: () => Promise<ElevenLabsVoice[]>;
  onSaveElevenLabs: (payload: {
    apiKey?: string;
    voiceId?: string;
    modelId?: string;
    outputFormat?: string;
    clearSecret?: boolean;
  }) => Promise<ElevenLabsVoiceConfig>;
  onTestElevenLabs: () => Promise<boolean>;
};

export default function VoiceControl({
  open,
  onClose,
  settings,
  voices,
  selectedVoice,
  speaking,
  wakeSupported,
  wakeState,
  lastHeard,
  liveTranscript,
  finalTranscript,
  errorMessage,
  elevenConfig,
  elevenVoices,
  selectedElevenVoice,
  elevenLoading,
  elevenStatus,
  audioStatus,
  onUpdate,
  onTest,
  onStop,
  onReset,
  onListenNow,
  onRefreshElevenVoices,
  onSaveElevenLabs,
  onTestElevenLabs,
}: Props) {
  const [apiKey, setApiKey] = useState("");

  useEffect(() => {
    if (!open) setApiKey("");
  }, [open]);

  const englishVoices = voices.filter((voice) =>
    voice.lang.toLowerCase().startsWith("en"),
  );

  const wakeLabel =
    speaking
      ? "SPEAKING"
      : wakeState === "standby"
        ? "WAKE STANDBY"
        : wakeState === "waking"
          ? "ACKNOWLEDGING"
          : wakeState === "listening"
            ? "LISTENING"
            : wakeState === "processing"
              ? "PROCESSING"
              : wakeState === "error"
                ? "MIC ERROR"
                : wakeState === "unsupported"
                  ? "UNSUPPORTED"
                  : "WAKE OFF";

  const transcript =
    liveTranscript ||
    finalTranscript ||
    lastHeard ||
    "Say the wake phrase or press Listen now.";

  const voiceIdentity =
    settings.engine === "elevenlabs"
      ? selectedElevenVoice
        ? selectedElevenVoice.name +
          " / " +
          elevenConfig.model_id
        : "ElevenLabs / select a voice"
      : selectedVoice
        ? selectedVoice.name +
          " / " +
          selectedVoice.lang
        : "System speech voice";

  async function saveApiKey() {
    if (!apiKey.trim()) return;
    await onSaveElevenLabs({
      apiKey: apiKey.trim(),
    });
    setApiKey("");
    await onRefreshElevenVoices();
  }

  return (
    <HudModal
      open={open}
      onClose={onClose}
      title="Voice Core"
      eyebrow="AUDIO / AGENT MAN SIGNATURE"
      footer={
        <>
          <button
            className="secondaryButton"
            onClick={onReset}
          >
            <RotateCcw size={14} />
            Signature preset
          </button>
          <button
            className="secondaryButton"
            onClick={speaking ? onStop : onTest}
          >
            {speaking ? (
              <Square size={14} />
            ) : (
              <Radio size={14} />
            )}
            {speaking ? "Stop voice" : "Test voice"}
          </button>
          <button
            className="primaryButton"
            onClick={onClose}
          >
            Apply
          </button>
        </>
      }
    >
      <div className="voiceIdentity">
        <div
          className={
            speaking
              ? "voiceOrb speaking"
              : wakeState === "listening"
                ? "voiceOrb listening"
                : wakeState === "processing"
                  ? "voiceOrb processing"
                  : "voiceOrb"
          }
        >
          {settings.enabled ? (
            <Volume2 size={28} />
          ) : (
            <VolumeX size={28} />
          )}
        </div>
        <div>
          <span>PROFILE</span>
          <strong>AGENT MAN SIGNATURE</strong>
          <small>{voiceIdentity}</small>
        </div>
      </div>

      <div className="voiceRuntimeStatus">
        <span className={speaking ? "active" : ""} />
        <div>
          <small>AUDIO OUTPUT</small>
          <strong>{audioStatus}</strong>
        </div>
      </div>

      <div className="voiceToggleGrid">
        <button
          className={
            settings.enabled
              ? "voiceToggle active"
              : "voiceToggle"
          }
          onClick={() =>
            onUpdate({
              enabled: !settings.enabled,
            })
          }
        >
          <Volume2 size={15} />
          Voice {settings.enabled ? "ON" : "OFF"}
        </button>

        <button
          className={
            settings.autoSpeak
              ? "voiceToggle active"
              : "voiceToggle"
          }
          onClick={() =>
            onUpdate({
              autoSpeak: !settings.autoSpeak,
            })
          }
        >
          <Radio size={15} />
          Auto speak{" "}
          {settings.autoSpeak ? "ON" : "OFF"}
        </button>

        <button
          className={
            settings.wakeEnabled && wakeSupported
              ? "voiceToggle active"
              : "voiceToggle"
          }
          onClick={() =>
            onUpdate({
              wakeEnabled: wakeSupported
                ? !settings.wakeEnabled
                : false,
            })
          }
          disabled={!wakeSupported}
        >
          {settings.wakeEnabled &&
          wakeSupported ? (
            <Mic size={15} />
          ) : (
            <MicOff size={15} />
          )}
          Wake mode{" "}
          {settings.wakeEnabled ? "ON" : "OFF"}
        </button>

        <button
          className={
            wakeState === "listening"
              ? "voiceToggle active"
              : "voiceToggle"
          }
          onClick={onListenNow}
          disabled={
            !wakeSupported ||
            wakeState === "processing" ||
            speaking
          }
        >
          <Mic size={15} />
          Listen now
        </button>
      </div>

      <div className={"wakePanel phase-" + wakeState}>
        <div className="wakeStatusLine">
          <span
            className={
              "wakeStatusDot " +
              (speaking ? "speaking" : wakeState)
            }
          />
          <b>{wakeLabel}</b>
          <small>
            {wakeState === "listening"
              ? "Speak naturally. Command submits after a short silence."
              : wakeState === "processing"
                ? "Agent Man is working on the captured directive."
                : "Wake listener status"}
          </small>
        </div>

        <div className="voiceCaptureMonitor">
          <div
            className={
              "voiceWave " +
              (wakeState === "listening"
                ? "active"
                : wakeState === "processing"
                  ? "processing"
                  : "")
            }
            aria-hidden="true"
          >
            {Array.from({ length: 12 }).map(
              (_, index) => (
                <i key={index} />
              ),
            )}
          </div>
          <div className="voiceTranscript">
            <small>
              {wakeState === "listening"
                ? "LIVE TRANSCRIPT"
                : wakeState === "processing"
                  ? "CAPTURED COMMAND"
                  : "LAST CAPTURE"}
            </small>
            <p>{transcript}</p>
          </div>
        </div>

        {errorMessage && (
          <div className="voiceCaptureError">
            {errorMessage}
          </div>
        )}

        <label className="voiceField">
          Wake phrase
          <input
            value={settings.wakePhrase}
            onChange={(event) =>
              onUpdate({
                wakePhrase: event.target.value,
              })
            }
            placeholder="hey agent man"
          />
        </label>

        <label className="voiceField">
          Recognition language
          <select
            value={settings.wakeLanguage}
            onChange={(event) =>
              onUpdate({
                wakeLanguage: event.target.value,
              })
            }
          >
            <option value="en-IN">
              English · India
            </option>
            <option value="en-GB">
              English · UK
            </option>
            <option value="en-US">
              English · US
            </option>
          </select>
        </label>

        <p className="voiceNote">
          Say “{settings.wakePhrase}”. Agent Man
          acknowledges, opens focused command capture,
          shows the live transcript, and submits after a
          short silence.
        </p>
      </div>

      <label className="voiceField">
        Voice engine
        <select
          value={settings.engine}
          onChange={(event) =>
            onUpdate({
              engine: event.target.value as
                | "browser"
                | "elevenlabs",
            })
          }
        >
          <option value="browser">
            System / browser speech
          </option>
          <option value="elevenlabs">
            ElevenLabs
          </option>
        </select>
      </label>

      {settings.engine === "browser" ? (
        <>
          <label className="voiceField">
            System voice
            <select
              value={selectedVoice?.voiceURI || ""}
              onChange={(event) =>
                onUpdate({
                  voiceURI: event.target.value,
                })
              }
            >
              {englishVoices.map((voice) => (
                <option
                  value={voice.voiceURI}
                  key={voice.voiceURI}
                >
                  {voice.name} · {voice.lang}
                </option>
              ))}
            </select>
          </label>

          <div className="voiceSliders">
            <VoiceSlider
              label="Rate"
              value={settings.rate}
              min={0.6}
              max={1.35}
              step={0.01}
              onChange={(rate) =>
                onUpdate({ rate })
              }
            />
            <VoiceSlider
              label="Pitch"
              value={settings.pitch}
              min={0.5}
              max={1.2}
              step={0.01}
              onChange={(pitch) =>
                onUpdate({ pitch })
              }
            />
            <VoiceSlider
              label="Volume"
              value={settings.volume}
              min={0}
              max={1}
              step={0.01}
              onChange={(volume) =>
                onUpdate({ volume })
              }
            />
          </div>
        </>
      ) : (
        <section className="elevenVoicePanel">
          <div className="elevenVoiceHeader">
            <div>
              <small>ELEVENLABS UPLINK</small>
              <strong>
                {elevenConfig.has_secret
                  ? "API KEY SECURED"
                  : "SETUP REQUIRED"}
              </strong>
            </div>
            <span>
              {elevenConfig.has_secret
                ? "DPAPI"
                : "NO KEY"}
            </span>
          </div>

          <div className="elevenKeyRow">
            <label className="voiceField">
              API key
              <input
                type="password"
                value={apiKey}
                onChange={(event) =>
                  setApiKey(event.target.value)
                }
                placeholder={
                  elevenConfig.has_secret
                    ? "Stored securely · enter to replace"
                    : "Paste ElevenLabs API key"
                }
              />
            </label>
            <button
              className="secondaryButton"
              type="button"
              disabled={
                elevenLoading || !apiKey.trim()
              }
              onClick={() => void saveApiKey()}
            >
              <KeyRound size={14} />
              Save key
            </button>
          </div>

          <div className="elevenActions">
            <button
              className="secondaryButton"
              type="button"
              disabled={
                elevenLoading ||
                !elevenConfig.has_secret
              }
              onClick={() =>
                void onRefreshElevenVoices()
              }
            >
              <RefreshCw
                size={14}
                className={
                  elevenLoading ? "spinIcon" : ""
                }
              />
              Detect voices
            </button>
            <button
              className="secondaryButton"
              type="button"
              disabled={
                elevenLoading ||
                !elevenConfig.has_secret
              }
              onClick={() =>
                void onTestElevenLabs()
              }
            >
              <Radio size={14} />
              Test connection
            </button>
            {elevenConfig.has_secret && (
              <button
                className="secondaryButton dangerAction"
                type="button"
                disabled={elevenLoading}
                onClick={() =>
                  void onSaveElevenLabs({
                    clearSecret: true,
                  })
                }
              >
                Remove key
              </button>
            )}
          </div>

          <label className="voiceField">
            ElevenLabs voice
            <select
              value={elevenConfig.voice_id}
              disabled={
                elevenLoading ||
                elevenVoices.length === 0
              }
              onChange={(event) =>
                void onSaveElevenLabs({
                  voiceId: event.target.value,
                })
              }
            >
              <option value="">
                {elevenVoices.length
                  ? "Select voice"
                  : "Detect voices first"}
              </option>
              {elevenVoices.map((voice) => (
                <option
                  value={voice.voice_id}
                  key={voice.voice_id}
                >
                  {voice.name}
                  {voice.labels.accent
                    ? " · " +
                      voice.labels.accent
                    : ""}
                </option>
              ))}
            </select>
          </label>

          <label className="voiceField">
            ElevenLabs model
            <select
              value={elevenConfig.model_id}
              onChange={(event) =>
                void onSaveElevenLabs({
                  modelId: event.target.value,
                })
              }
            >
              <option value="eleven_flash_v2_5">
                Flash v2.5 · low latency
              </option>
              <option value="eleven_multilingual_v2">
                Multilingual v2 · quality
              </option>
              <option value="eleven_v3">
                Eleven v3 · expressive
              </option>
            </select>
          </label>

          <label className="voiceField">
            Audio quality
            <select
              value={elevenConfig.output_format}
              onChange={(event) =>
                void onSaveElevenLabs({
                  outputFormat:
                    event.target.value,
                })
              }
            >
              <option value="mp3_22050_32">
                MP3 · 22.05 kHz · 32 kbps
              </option>
              <option value="mp3_44100_128">
                MP3 · 44.1 kHz · 128 kbps
              </option>
            </select>
          </label>

          <div className="voiceSliders elevenVolume">
            <VoiceSlider
              label="Playback volume"
              value={settings.volume}
              min={0}
              max={1}
              step={0.01}
              onChange={(volume) =>
                onUpdate({ volume })
              }
            />
          </div>

          {elevenStatus && (
            <div className="elevenStatus">
              {elevenStatus}
            </div>
          )}

          <p className="voiceNote">
            The API key is stored by the local Agent Man
            runtime using Windows DPAPI. It is never stored
            in browser localStorage or sent back to this UI.
          </p>
        </section>
      )}
    </HudModal>
  );
}

function VoiceSlider({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="voiceField">
      <span>
        {label}
        <b>{value.toFixed(2)}</b>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) =>
          onChange(Number(event.target.value))
        }
      />
    </label>
  );
}
