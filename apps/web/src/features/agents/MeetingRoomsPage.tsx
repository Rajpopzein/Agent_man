import {
  FormEvent,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  Bot,
  CheckCircle2,
  CircleStop,
  Clock3,
  RefreshCw,
  Send,
  ShieldAlert,
  Sparkles,
  Users,
  XCircle,
} from "lucide-react";

import {
  api,
  BackgroundJob,
  MeetingRoom,
  Project,
} from "../../services/api";

type Props = {
  project: Project | null;
  backgroundJobs: BackgroundJob[];
};

const RUNNING_STATUSES = new Set([
  "queued",
  "running",
  "stopping",
  "waiting_approval",
  "waiting_capability",
]);

function jobStatusLabel(job: BackgroundJob) {
  if (job.status === "waiting_approval") return "approval required";
  if (job.status === "stopping") return "stopping safely";
  return job.status.replaceAll("_", " ");
}

function statusIcon(status: string) {
  if (status === "completed") return <CheckCircle2 size={15} />;
  if (["error", "turn_limit"].includes(status)) {
    return <XCircle size={15} />;
  }
  if (status === "stopped") return <CircleStop size={15} />;
  return <Clock3 size={15} />;
}

export default function MeetingRoomsPage({
  project,
  backgroundJobs,
}: Props) {
  const [rooms, setRooms] = useState<MeetingRoom[]>([]);
  const [activeRoomId, setActiveRoomId] = useState("");
  const [room, setRoom] = useState<MeetingRoom | null>(null);
  const [targetAgentId, setTargetAgentId] = useState("");
  const [instruction, setInstruction] = useState("");
  const [allowDelete, setAllowDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");

  async function loadRooms(preferredRoomId?: string) {
    if (!project) {
      setRooms([]);
      setRoom(null);
      setActiveRoomId("");
      return;
    }

    const result = await api.meetingRooms(project.id);
    setRooms(result);

    const nextId =
      preferredRoomId ||
      activeRoomId ||
      result[0]?.id ||
      "";

    if (!nextId) {
      setRoom(null);
      setActiveRoomId("");
      return;
    }

    const found = result.find((item) => item.id === nextId);
    if (found) {
      setActiveRoomId(found.id);
      setRoom(found);
      return;
    }

    const fresh = await api.meetingRoom(nextId);
    setActiveRoomId(fresh.id);
    setRoom(fresh);
  }

  async function refreshRoom(roomId = activeRoomId) {
    if (!roomId) return;
    const fresh = await api.meetingRoom(roomId);
    setRoom(fresh);
    setRooms((current) =>
      current.some((item) => item.id === fresh.id)
        ? current.map((item) =>
            item.id === fresh.id ? fresh : item,
          )
        : [fresh, ...current],
    );
  }

  useEffect(() => {
    void loadRooms();
    // Load only when the active project changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id]);

  useEffect(() => {
    if (!room) {
      setTargetAgentId("");
      return;
    }
    const stillPresent = room.members.some(
      (member) =>
        member.active && member.agent_id === targetAgentId,
    );
    if (!stillPresent) {
      setTargetAgentId(
        room.members.find((member) => member.active)?.agent_id || "",
      );
    }
  }, [room, targetAgentId]);

  const roomJobVersion = useMemo(() => {
    if (!activeRoomId) return "";
    return backgroundJobs
      .filter((job) => job.room_id === activeRoomId)
      .map(
        (job) =>
          job.id +
          ":" +
          job.status +
          ":" +
          job.updated_at +
          ":" +
          job.step_count,
      )
      .join("|");
  }, [activeRoomId, backgroundJobs]);

  useEffect(() => {
    if (!activeRoomId || !roomJobVersion) return;
    void refreshRoom(activeRoomId);
    // The version changes only when a room job changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomJobVersion]);

  const jobs = useMemo(() => {
    if (!room) return [];
    const live = backgroundJobs.filter(
      (job) => job.room_id === room.id,
    );
    const byId = new Map<string, BackgroundJob>();
    for (const job of room.jobs) byId.set(job.id, job);
    for (const job of live) byId.set(job.id, job);
    return Array.from(byId.values()).sort((a, b) =>
      String(b.created_at).localeCompare(String(a.created_at)),
    );
  }, [room, backgroundJobs]);

  const activeJobs = jobs.filter((job) =>
    RUNNING_STATUSES.has(job.status),
  );

  async function selectRoom(roomId: string) {
    setActiveRoomId(roomId);
    setStatus("");
    try {
      await refreshRoom(roomId);
    } catch (error) {
      setStatus(
        error instanceof Error ? error.message : String(error),
      );
    }
  }

  async function sendInstruction(event: FormEvent) {
    event.preventDefault();
    if (
      !project ||
      !room ||
      !targetAgentId ||
      !instruction.trim() ||
      busy
    ) {
      return;
    }

    const task = instruction.trim();
    setInstruction("");
    setBusy(true);
    setStatus("");

    try {
      const fresh = await api.instructMeetingRoom(room.id, {
        agent_id: targetAgentId,
        instruction: task,
        allow_delete: allowDelete,
      });
      setRoom(fresh);
      setRooms((current) =>
        current.map((item) =>
          item.id === fresh.id ? fresh : item,
        ),
      );
      setAllowDelete(false);
      setStatus("Instruction assigned. Agent Man is tracking the job.");
    } catch (error) {
      setInstruction(task);
      setStatus(
        error instanceof Error ? error.message : String(error),
      );
    } finally {
      setBusy(false);
    }
  }

  async function stopJob(job: BackgroundJob) {
    if (!project || busy) return;
    setBusy(true);
    setStatus("");
    try {
      const stopped = await api.stopBackgroundJob(
        project.id,
        job.id,
      );
      setStatus(
        stopped.status === "stopped"
          ? stopped.agent_name + " stopped."
          : "Stop requested for " + stopped.agent_name + ".",
      );
      await refreshRoom();
    } catch (error) {
      setStatus(
        error instanceof Error ? error.message : String(error),
      );
    } finally {
      setBusy(false);
    }
  }

  async function approveJob(job: BackgroundJob) {
    if (!project || busy) return;
    setBusy(true);
    setStatus("");
    try {
      await api.approveBackgroundJob(project.id, job.id);
      setStatus(job.agent_name + " received approval and is resuming.");
      await refreshRoom();
    } catch (error) {
      setStatus(
        error instanceof Error ? error.message : String(error),
      );
    } finally {
      setBusy(false);
    }
  }

  async function closeRoom() {
    if (!room || busy) return;
    setBusy(true);
    setStatus("");
    try {
      const fresh = await api.closeMeetingRoom(room.id);
      setRoom(fresh);
      setRooms((current) =>
        current.map((item) =>
          item.id === fresh.id ? fresh : item,
        ),
      );
      setStatus("Meeting room closed.");
    } catch (error) {
      setStatus(
        error instanceof Error ? error.message : String(error),
      );
    } finally {
      setBusy(false);
    }
  }

  if (!project) {
    return (
      <section className="panel meetingRoomEmpty">
        <Users />
        <h3>Create a project first</h3>
        <p className="muted">
          Meeting rooms are scoped to one Agent Man project.
        </p>
      </section>
    );
  }

  return (
    <section className="meetingRoomsPage">
      <div className="sectionHeading">
        <div>
          <h2>Meeting Rooms</h2>
          <p>
            Persistent user-directed sessions. Agent Man stays in every
            room as the Executive host, tracks worker progress, and keeps
            the task transcript tied to the room.
          </p>
        </div>
        <button
          className="secondaryButton"
          onClick={() => void loadRooms()}
          disabled={busy}
        >
          <RefreshCw size={15} />
          Refresh
        </button>
      </div>

      <div className="meetingRoomLayout">
        <aside className="panel meetingRoomList">
          <div className="meetingRoomListHeader">
            <div>
              <strong>Sessions</strong>
              <small>{rooms.length} rooms</small>
            </div>
          </div>

          {rooms.length === 0 ? (
            <div className="meetingRoomHint">
              <Sparkles size={18} />
              <b>No meeting rooms yet</b>
              <p>
                Ask the Executive: “Create a meeting room for the login
                issue and connect the relevant agents.”
              </p>
            </div>
          ) : (
            <div className="meetingRoomRows">
              {rooms.map((item) => {
                const roomJobs = backgroundJobs.filter(
                  (job) => job.room_id === item.id,
                );
                const running = roomJobs.filter((job) =>
                  RUNNING_STATUSES.has(job.status),
                ).length;
                return (
                  <button
                    key={item.id}
                    className={
                      "meetingRoomRow " +
                      (activeRoomId === item.id ? "active" : "")
                    }
                    onClick={() => void selectRoom(item.id)}
                  >
                    <span>
                      <b>{item.title}</b>
                      <small>
                        {item.members.length} workers · {item.status}
                      </small>
                    </span>
                    {running > 0 && <em>{running} live</em>}
                  </button>
                );
              })}
            </div>
          )}
        </aside>

        <main className="meetingRoomMain">
          {!room ? (
            <div className="panel meetingRoomBlank">
              <Users size={24} />
              <h3>Select a meeting room</h3>
              <p className="muted">
                The Executive creates rooms from your normal command
                console.
              </p>
            </div>
          ) : (
            <>
              <section className="panel meetingRoomHeader">
                <div className="meetingRoomTitle">
                  <div>
                    <small>ACTIVE SESSION</small>
                    <h3>{room.title}</h3>
                    <p>{room.objective || "No objective provided."}</p>
                  </div>
                  <div className="meetingRoomHeaderActions">
                    <span className="taskStatus">
                      {room.status}
                    </span>
                    {room.status === "active" && (
                      <button
                        className="secondaryButton"
                        onClick={() => void closeRoom()}
                        disabled={busy || activeJobs.length > 0}
                        title={
                          activeJobs.length > 0
                            ? "Stop or finish active tasks before closing."
                            : "Close this room"
                        }
                      >
                        Close room
                      </button>
                    )}
                  </div>
                </div>

                <div className="meetingParticipants">
                  <article className="meetingParticipant executive">
                    <Sparkles size={17} />
                    <span>
                      <b>{room.executive.name}</b>
                      <small>
                        Executive · {room.executive.status}
                      </small>
                    </span>
                  </article>
                  {room.members.map((member) => (
                    <article
                      className="meetingParticipant"
                      key={member.agent_id}
                    >
                      <Bot size={17} />
                      <span>
                        <b>{member.agent_name}</b>
                        <small>
                          {member.role} · {member.state}
                        </small>
                      </span>
                    </article>
                  ))}
                </div>
              </section>

              <section className="meetingRoomWorkGrid">
                <div className="panel meetingRoomThread">
                  <div className="meetingPanelHeader">
                    <div>
                      <h3>Room transcript</h3>
                      <small>
                        User instructions, Executive assignments, and
                        worker results
                      </small>
                    </div>
                  </div>

                  <div className="meetingMessages">
                    {room.messages.length === 0 && (
                      <p className="muted">No room messages yet.</p>
                    )}
                    {room.messages.map((message) => (
                      <article
                        className={
                          "meetingMessage " + message.sender_type
                        }
                        key={message.id}
                      >
                        <header>
                          <b>{message.sender_name}</b>
                          <span>{message.kind.replaceAll("_", " ")}</span>
                        </header>
                        <p>{message.content}</p>
                      </article>
                    ))}
                  </div>

                  <form
                    className="meetingComposer"
                    onSubmit={sendInstruction}
                  >
                    <div className="meetingComposerTop">
                      <label>
                        Send task to
                        <select
                          value={targetAgentId}
                          onChange={(event) =>
                            setTargetAgentId(event.target.value)
                          }
                          disabled={room.status !== "active"}
                        >
                          {room.members
                            .filter((member) => member.active)
                            .map((member) => (
                              <option
                                value={member.agent_id}
                                key={member.agent_id}
                              >
                                {member.agent_name} · {member.role}
                              </option>
                            ))}
                        </select>
                      </label>
                      <label className="meetingDeleteApproval">
                        <input
                          type="checkbox"
                          checked={allowDelete}
                          onChange={(event) =>
                            setAllowDelete(event.target.checked)
                          }
                        />
                        <ShieldAlert size={14} />
                        Allow destructive delete
                      </label>
                    </div>
                    <textarea
                      value={instruction}
                      onChange={(event) =>
                        setInstruction(event.target.value)
                      }
                      placeholder="Tell the selected agent exactly what to work on..."
                      disabled={room.status !== "active"}
                    />
                    <button
                      className="primaryButton"
                      disabled={
                        busy ||
                        room.status !== "active" ||
                        !targetAgentId ||
                        !instruction.trim()
                      }
                    >
                      <Send size={15} />
                      Assign task
                    </button>
                  </form>
                </div>

                <aside className="panel meetingRoomJobs">
                  <div className="meetingPanelHeader">
                    <div>
                      <h3>Executive tracking</h3>
                      <small>
                        {activeJobs.length
                          ? activeJobs.length + " active task(s)"
                          : "No active tasks"}
                      </small>
                    </div>
                  </div>

                  <div className="meetingJobList">
                    {jobs.length === 0 && (
                      <div className="meetingRoomHint compact">
                        <Clock3 size={17} />
                        <p>
                          Assign a task to a room member to start a
                          tracked worker session.
                        </p>
                      </div>
                    )}

                    {jobs.map((job) => (
                      <article
                        className={"meetingJob " + job.status}
                        key={job.id}
                      >
                        <header>
                          <span>
                            {statusIcon(job.status)}
                            <b>{job.agent_name}</b>
                          </span>
                          <em>{jobStatusLabel(job)}</em>
                        </header>
                        <p>{job.task}</p>

                        {(job.current_action ||
                          job.current_next_step) && (
                          <div className="meetingJobProgress">
                            {job.current_action && (
                              <span>
                                <small>NOW</small>
                                {job.current_action}
                              </span>
                            )}
                            {job.current_next_step && (
                              <span>
                                <small>NEXT</small>
                                {job.current_next_step}
                              </span>
                            )}
                          </div>
                        )}

                        {job.current_tool && (
                          <code>{job.current_tool}</code>
                        )}

                        <div className="meetingJobActions">
                          {job.status === "waiting_approval" && (
                            <button
                              className="primaryButton"
                              disabled={busy}
                              onClick={() => void approveJob(job)}
                            >
                              Approve & Continue
                            </button>
                          )}
                          {[
                            "queued",
                            "running",
                            "stopping",
                            "waiting_approval",
                            "waiting_capability",
                          ].includes(job.status) && (
                            <button
                              className="dangerButton"
                              disabled={
                                busy || job.status === "stopping"
                              }
                              onClick={() => void stopJob(job)}
                            >
                              <CircleStop size={14} />
                              {job.status === "stopping"
                                ? "Stopping..."
                                : "Stop agent"}
                            </button>
                          )}
                        </div>

                        {job.result_text && (
                          <div className="meetingJobResult">
                            {job.result_text}
                          </div>
                        )}
                      </article>
                    ))}
                  </div>
                </aside>
              </section>

              {status && (
                <div className="connectionStatus meetingRoomStatus">
                  {status}
                </div>
              )}
            </>
          )}
        </main>
      </div>
    </section>
  );
}
