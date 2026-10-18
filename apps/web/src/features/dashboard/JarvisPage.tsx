import type { ReactNode } from "react";
import {
  Activity,
  ArrowUpRight,
  Bot,
  CircleDot,
  Clock3,
  FolderTree,
  MessageSquareText,
  Settings2,
  Signal,
} from "lucide-react";

type Conversation = {
  id: string;
  command: string;
  response: string;
  status: string;
};

type ActivityEntry = {
  id: string;
  actor: string;
  phase: string;
  text: string;
  status: string;
};

type JobEntry = {
  id: string;
  agent: string;
  action: string;
  status: string;
};

type Props = {
  children: ReactNode;
  online: boolean;
  streamConnected: boolean;
  configured: boolean;
  hasProject: boolean;
  workerCount: number;
  activeJobCount: number;
  recentJobs: JobEntry[];
  activity: ActivityEntry[];
  history: Conversation[];
  onOverview: () => void;
  onWorkbench: () => void;
  onLogs: () => void;
  onSettings: () => void;
  onCreateProject: () => void;
};

export default function JarvisPage({
  children,
  online,
  streamConnected,
  configured,
  hasProject,
  workerCount,
  activeJobCount,
  recentJobs,
  activity,
  history,
  onOverview,
  onWorkbench,
  onLogs,
  onSettings,
  onCreateProject,
}: Props) {
  return (
    <div className="jarvisPage">
      <div className="jarvisPageIntro">
        <div>
          <span className="hudEyebrow">PERSONAL AI / DIRECT LINK</span>
          <h2>JARVIS is at your command.</h2>
          <p>Speak naturally or type a task. Watch its status and delegated work in one place.</p>
        </div>
        <div className="jarvisPageLive">
          <span className={online ? "connected" : "disconnected"} />
          {online ? "RUNTIME CONNECTED" : "RUNTIME OFFLINE"}
          <small>{streamConnected ? "EVENT FEED LIVE" : "EVENT FEED DISCONNECTED"}</small>
        </div>
      </div>

      {!hasProject && (
        <div className="jarvisSetupPrompt">
          <span>No project is configured yet. Create a workspace before running JARVIS tasks.</span>
          <button type="button" onClick={onCreateProject}>Create project</button>
        </div>
      )}
      {hasProject && !configured && (
        <div className="jarvisSetupPrompt">
          <span>Set up JARVIS's executive AI model to start accepting directives.</span>
          <button type="button" onClick={onSettings}>Configure JARVIS</button>
        </div>
      )}

      <div className="jarvisPageCore">{children}</div>

      <div className="jarvisPageMetrics">
        <div><Bot size={15}/><span>Worker agents</span><strong>{workerCount}</strong></div>
        <div><Activity size={15}/><span>Active missions</span><strong>{activeJobCount}</strong></div>
        <div><Signal size={15}/><span>Event stream</span><strong>{streamConnected ? "Live" : "Disconnected"}</strong></div>
        <button type="button" onClick={onOverview}>
          <CircleDot size={15}/><span>Mission Control</span><strong>Open <ArrowUpRight size={13}/></strong>
        </button>
      </div>

      <div className="jarvisPageDetails">
        <section className="jarvisPagePanel">
          <div className="jarvisPagePanelHeader">
            <div><MessageSquareText size={16}/><h3>Conversation</h3></div>
            <small>THIS SESSION</small>
          </div>
          <div className="jarvisConversation" aria-live="polite">
            {history.length === 0 && (
              <p className="jarvisNoData">No conversation yet. Start by speaking to JARVIS or sending a message above.</p>
            )}
            {history.map((entry) => (
              <article className="jarvisExchange" key={entry.id}>
                <div className="jarvisMessage user">
                  <small>YOU</small>
                  <p>{entry.command}</p>
                </div>
                <div className="jarvisMessage assistant">
                  <div><small>JARVIS</small><em>{entry.status.replaceAll("_", " ")}</em></div>
                  <p>{entry.response || "The request was accepted."}</p>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="jarvisPagePanel">
          <div className="jarvisPagePanelHeader">
            <div><Activity size={16}/><h3>Live mission activity</h3></div>
            <small>{activeJobCount} ACTIVE</small>
          </div>
          <div className="jarvisMissionList">
            {activity.length === 0 && recentJobs.length === 0 && (
              <p className="jarvisNoData">No recent activity. Agent actions and worker updates appear here.</p>
            )}
            {activity.map((item) => (
              <div className="jarvisMissionRow" key={item.id}>
                <span className={"jarvisMissionDot status-" + item.status} />
                <div>
                  <strong>{item.actor || "JARVIS"}</strong>
                  <p>{item.text || item.phase}</p>
                </div>
                <small>{item.phase.replaceAll("_", " ")}</small>
              </div>
            ))}
            {recentJobs.map((job) => (
              <div className="jarvisMissionRow" key={"job:" + job.id}>
                <Clock3 size={13}/>
                <div>
                  <strong>{job.agent}</strong>
                  <p>{job.action}</p>
                </div>
                <small>{job.status.replaceAll("_", " ")}</small>
              </div>
            ))}
          </div>
          <div className="jarvisPageShortcuts">
            <button type="button" onClick={onWorkbench}><FolderTree size={14}/> Workbench</button>
            <button type="button" onClick={onLogs}><Activity size={14}/> Model logs</button>
            <button type="button" onClick={onSettings}><Settings2 size={14}/> Settings</button>
          </div>
        </section>
      </div>
    </div>
  );
}
