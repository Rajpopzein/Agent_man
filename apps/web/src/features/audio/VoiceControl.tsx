import {
  Radio,
  RotateCcw,
  Square,
  Volume2,
  VolumeX,
} from "lucide-react";

import HudModal from "../../components/HudModal";
import { VoiceSettings } from "./useAgentVoice";

type Props = {
  open: boolean;
  onClose: () => void;
  settings: VoiceSettings;
  voices: SpeechSynthesisVoice[];
  selectedVoice: SpeechSynthesisVoice | null;
  speaking: boolean;
  onUpdate: (patch: Partial<VoiceSettings>) => void;
  onTest: () => void;
  onStop: () => void;
  onReset: () => void;
};

export default function VoiceControl({
  open,
  onClose,
  settings,
  voices,
  selectedVoice,
  speaking,
  onUpdate,
  onTest,
  onStop,
  onReset,
}: Props) {
  const englishVoices = voices.filter((voice) =>
    voice.lang.toLowerCase().startsWith("en"),
  );

  return (
    <HudModal
      open={open}
      onClose={onClose}
      title="Voice Core"
      eyebrow="AUDIO / AGENT MAN SIGNATURE"
      footer={
        <>
          <button className="secondaryButton" onClick={onReset}>
            <RotateCcw size={14} />
            Signature preset
          </button>
          <button
            className="secondaryButton"
            onClick={speaking ? onStop : onTest}
          >
            {speaking ? <Square size={14} /> : <Radio size={14} />}
            {speaking ? "Stop voice" : "Test voice"}
          </button>
          <button className="primaryButton" onClick={onClose}>
            Apply
          </button>
        </>
      }
    >
      <div className="voiceIdentity">
        <div className={speaking ? "voiceOrb speaking" : "voiceOrb"}>
          {settings.enabled ? <Volume2 size={28} /> : <VolumeX size={28} />}
        </div>
        <div>
          <span>PROFILE</span>
          <strong>AGENT MAN SIGNATURE</strong>
          <small>
            {selectedVoice
              ? selectedVoice.name + " / " + selectedVoice.lang
              : "System speech voice"}
          </small>
        </div>
      </div>

      <div className="voiceToggleGrid">
        <button
          className={settings.enabled ? "voiceToggle active" : "voiceToggle"}
          onClick={() => onUpdate({ enabled: !settings.enabled })}
        >
          <Volume2 size={15} />
          Voice {settings.enabled ? "ON" : "OFF"}
        </button>
        <button
          className={settings.autoSpeak ? "voiceToggle active" : "voiceToggle"}
          onClick={() => onUpdate({ autoSpeak: !settings.autoSpeak })}
        >
          <Radio size={15} />
          Auto speak {settings.autoSpeak ? "ON" : "OFF"}
        </button>
      </div>

      <label className="voiceField">
        Voice engine
        <select
          value={selectedVoice?.voiceURI || ""}
          onChange={(event) => onUpdate({ voiceURI: event.target.value })}
        >
          {englishVoices.map((voice) => (
            <option value={voice.voiceURI} key={voice.voiceURI}>
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
          onChange={(rate) => onUpdate({ rate })}
        />
        <VoiceSlider
          label="Pitch"
          value={settings.pitch}
          min={0.5}
          max={1.2}
          step={0.01}
          onChange={(pitch) => onUpdate({ pitch })}
        />
        <VoiceSlider
          label="Volume"
          value={settings.volume}
          min={0}
          max={1}
          step={0.01}
          onChange={(volume) => onUpdate({ volume })}
        />
      </div>

      <p className="voiceNote">
        The Signature profile gives Agent Man a consistent lower, measured
        delivery using an installed system voice. Available voice engines vary
        by Windows and browser.
      </p>
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
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}
