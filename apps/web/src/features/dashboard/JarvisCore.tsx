import { FormEvent } from "react";
import { ThinkingOrb, type OrbState } from "thinking-orbs";
import {
  Mic,
  Radio,
  Send,
  TerminalSquare,
} from "lucide-react";

export type JarvisOrbState =
  | "offline"
  | "idle"
  | "listening"
  | "thinking"
  | "working"
  | "speaking"
  | "success"
  | "warning"
  | "error";

type Props = {
  state: JarvisOrbState;
  stateLabel: string;
  prompt: string;
  busy: boolean;
  online: boolean;
  processingSeconds: number;
  projectName: string;
  workerName: string;
  currentAction: string;
  currentTool: string;
  responseText: string;
  responseStatus: string;
  onPromptChange: (value: string) => void;
  onSubmit: () => void;
  onListen: () => void;
  onOpenConsole: () => void;
};

function expressionCopy(state: JarvisOrbState) {
  switch (state) {
    case "offline":
      return "Runtime offline";
    case "listening":
      return "I’m listening";
    case "thinking":
      return "Thinking";
    case "working":
      return "Working with my agents";
    case "speaking":
      return "Speaking";
    case "success":
      return "Mission complete";
    case "warning":
      return "I need your attention";
    case "error":
      return "Something needs correction";
    default:
      return "Ready";
  }
}

function packageOrbState(
  state: JarvisOrbState,
  currentTool: string,
  currentAction: string,
): OrbState {
  if (state === "listening") return "listening";
  if (state === "thinking") return "solving";
  if (state === "speaking") return "composing";
  if (state === "working") {
    const activity = (currentTool + " " + currentAction).toLowerCase();
    if (/\b(connecting|delegating|handoff)\b/.test(activity)) {
      return "connecting";
    }
    if (/\b(search|searching|fetch|lookup|find|read_file|list_files|http_get)\b/.test(activity)) {
      return "searching";
    }
    return "working";
  }
  return "breathing";
}

export default function JarvisCore({
  state,
  stateLabel,
  prompt,
  busy,
  online,
  processingSeconds,
  projectName,
  workerName,
  currentAction,
  currentTool,
  responseText,
  responseStatus,
  onPromptChange,
  onSubmit,
  onListen,
  onOpenConsole,
}: Props) {
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!prompt.trim() || busy || !online) return;
    onSubmit();
  }

  return (
    <section className={"jarvisCore state-" + state}>
      <div className="jarvisCoreHeader">
        <div>
          <span className="jarvisCoreEyebrow">JARVIS / EXECUTIVE CORE</span>
          <h2>Direct Control</h2>
        </div>
        <div className="jarvisRuntimeReadout">
          <span className={online ? "online" : "offline"} />
          <b>{online ? "ONLINE" : "OFFLINE"}</b>
          <small>{projectName || "NO PROJECT"}</small>
        </div>
      </div>

      <div className="jarvisStage">
        <div className="jarvisSideStatus left">
          <small>ACTIVE WORKER</small>
          <strong>{workerName || "JARVIS"}</strong>
          <span>{currentAction || "Standing by for your instruction."}</span>
        </div>

        <button
          type="button"
          className="jarvisOrbButton"
          onClick={onListen}
          disabled={!online}
          aria-label="Talk to JARVIS"
          title="Talk to JARVIS"
        >
          <span className="jarvisPackageHalo" aria-hidden="true" />
          <span className="jarvisPackageOrb">
            <ThinkingOrb
              state={packageOrbState(state, currentTool, currentAction)}
              size={64}
              theme="dark"
              speed={state === "thinking" ? 1.25 : state === "working" ? 1.1 : 1}
              paused={["offline", "success", "warning", "error"].includes(state)}
              aria-label={"JARVIS " + stateLabel.toLowerCase()}
              className="jarvisPackageCanvas"
            />
          </span>
        </button>

        <div className="jarvisSideStatus right">
          <small>CORE STATE</small>
          <strong>{stateLabel}</strong>
          <span>
            {currentTool
              ? "Using " + currentTool.replaceAll("_", " ")
              : expressionCopy(state)}
          </span>
        </div>
      </div>

      <div className="jarvisExpressionLabel">
        <strong>{expressionCopy(state)}</strong>
        {busy && processingSeconds > 0 && (
          <small>{processingSeconds}s active</small>
        )}
      </div>

      <form className="jarvisDirectComposer" onSubmit={submit}>
        <div className="jarvisComposerInput">
          <span>J</span>
          <textarea
            value={prompt}
            onChange={(event) => onPromptChange(event.target.value)}
            placeholder="Ask JARVIS anything or give it a task..."
            rows={2}
          />
        </div>
        <button
          type="button"
          className="jarvisVoiceButton"
          onClick={onListen}
          disabled={!online}
          title="Listen now"
        >
          <Mic size={17} />
          Voice
        </button>
        <button
          className="jarvisSendButton"
          disabled={!online || busy || !prompt.trim()}
        >
          <Send size={17} />
          {busy ? "Working" : "Send"}
        </button>
      </form>

      <div className="jarvisResponsePanel">
        <div className="jarvisResponseHeader">
          <span>
            <Radio size={12} />
            {responseStatus || "standby"}
          </span>
          <button type="button" onClick={onOpenConsole}>
            <TerminalSquare size={12} />
            Console
          </button>
        </div>
        <p>
          {responseText ||
            "JARVIS is ready. Click the orb to speak or type a directive above."}
        </p>
      </div>
    </section>
  );
}
