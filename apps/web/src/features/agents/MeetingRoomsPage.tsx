import {
  FormEvent,
  useEffect,
  useMemo,
  useRef,
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
  UserMinus,
  Users,
  XCircle,
} from "lucide-react";

import {
  api,
  BackgroundJob,
  MeetingRoom,
  MeetingRoomCollaboration,
  MeetingRoomMember,
  Project,
} from "../../services/api";

type Props = {
  project: Project | null;
  backgroundJobs: BackgroundJob[];
};

const ACTIVE_COLLABORATION_STATUSES = new Set([
  "created",
  "active",
  "executing",
  "waiting_approval",
  "stopping",
]);

const ACTIVE_JOB_STATUSES = new Set([
  "queued",
  "running",
  "stopping",
  "waiting_approval",
  "waiting_capability",
]);

function collaborationStatusIcon(status: string) {
  if (["completed", "completed_with_errors"].includes(status)) {
    return <CheckCircle2 size={15} />;
  }
  if (status === "failed") return <XCircle size={15} />;
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
  const [instruction, setInstruction] = useState("");
  const [allowDelete, setAllowDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const messagesRef = useRef<HTMLDivElement | null>(null);

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomJobVersion]);

  const latestMessageId =
    room?.messages[room.messages.length - 1]?.id || "";

  useEffect(() => {
    const node = messagesRef.current;
    if (!node) return;

    const frame = window.requestAnimationFrame(() => {
      node.scrollTop = node.scrollHeight;
    });

    return () => window.cancelAnimationFrame(frame);
  }, [room?.id, latestMessageId]);

  const activeCollaboration = useMemo(() => {
    if (!room) return null;
    return (
      room.collaborations.find((item) =>
        ACTIVE_COLLABORATION_STATUSES.has(item.status),
      ) || null
    );
  }, [room]);

  useEffect(() => {
    if (!activeRoomId || !activeCollaboration) return;
    const timer = window.setInterval(() => {
      void refreshRoom(activeRoomId);
    }, 1400);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRoomId, activeCollaboration?.id]);

  const legacyActiveJobs = useMemo(
    () =>
      room
        ? backgroundJobs.filter(
            (job) =>
              job.room_id === room.id &&
              ACTIVE_JOB_STATUSES.has(job.status),
          )
        : [],
    [backgroundJobs, room],
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
    if (!room || !instruction.trim() || busy) return;

    const task = instruction.trim();
    setInstruction("");
    setBusy(true);
    setStatus("");

    try {
      const fresh = await api.instructMeetingRoom(room.id, {
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
      setStatus(
        activeCollaboration
          ? "Instruction added to the live room discussion."
          : "Room collaboration started. All active members are working together.",
      );
    } catch (error) {
      setInstruction(task);
      setStatus(
        error instanceof Error ? error.message : String(error),
      );
    } finally {
      setBusy(false);
    }
  }

  async function kickMember(member: MeetingRoomMember) {
    if (!room || busy || !member.active) return;
    setBusy(true);
    setStatus("");
    try {
      const fresh = await api.kickMeetingRoomMember(
        room.id,
        member.agent_id,
      );
      setRoom(fresh);
      setRooms((current) =>
        current.map((item) =>
          item.id === fresh.id ? fresh : item,
        ),
      );
      setStatus(
        member.agent_name +
          " was kicked. They will stop participating at the next safe turn boundary.",
      );
    } catch (error) {
      setStatus(
        error instanceof Error ? error.message : String(error),
      );
    } finally {
      setBusy(false);
    }
  }

  async function stopCollaboration(
    collaboration: MeetingRoomCollaboration,
  ) {
    if (!room || busy) return;
    setBusy(true);
    setStatus("");
    try {
      const fresh = await api.stopMeetingRoomCollaboration(
        room.id,
        collaboration.id,
      );
      setRoom(fresh);
      setStatus("Stop requested for the shared room session.");
    } catch (error) {
      setStatus(
        error instanceof Error ? error.message : String(error),
      );
    } finally {
      setBusy(false);
    }
  }

  async function approveDelete(
    collaboration: MeetingRoomCollaboration,
  ) {
    if (!room || busy) return;
    setBusy(true);
    setStatus("");
    try {
      const fresh = await api.approveMeetingRoomDelete(
        room.id,
        collaboration.id,
      );
      setRoom(fresh);
      setStatus(
        "Destructive action approved. The room is continuing.",
      );
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
            Shared working sessions. Give the room one instruction and
            the connected agents communicate, use their tools, review one
            another, and keep going until they agree the objective is complete.
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
                Ask Agent Man to create a meeting room and connect the
                relevant agents.
              </p>
            </div>
          ) : (
            <div className="meetingRoomRows">
              {rooms.map((item) => {
                const live = item.collaborations.some((collaboration) =>
                  ACTIVE_COLLABORATION_STATUSES.has(
                    collaboration.status,
                  ),
                );
                const activeMembers = item.members.filter(
                  (member) => member.active,
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
                        {activeMembers} active agents · {item.status}
                      </small>
                    </span>
                    {live && <em>LIVE</em>}
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
                    <small>COLLABORATIVE SESSION</small>
                    <h3>{room.title}</h3>
                    <p>{room.objective || "No objective provided."}</p>
                  </div>
                  <div className="meetingRoomHeaderActions">
                    <span className="taskStatus">{room.status}</span>
                    {activeCollaboration && (
                      <span className="taskStatus active">
                        round {activeCollaboration.current_round} ·{" "}
                        {activeCollaboration.status.replaceAll("_", " ")}
                      </span>
                    )}
                    {room.status === "active" && (
                      <button
                        className="secondaryButton"
                        onClick={() => void closeRoom()}
                        disabled={
                          busy ||
                          Boolean(activeCollaboration) ||
                          legacyActiveJobs.length > 0
                        }
                        title={
                          activeCollaboration
                            ? "Stop or finish the active collaboration first."
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
                        Executive · tracks the shared session
                      </small>
                    </span>
                  </article>

                  {room.members.map((member) => (
                    <article
                      className={
                        "meetingParticipant " +
                        (member.active ? "" : "inactive")
                      }
                      key={member.agent_id}
                    >
                      <Bot size={17} />
                      <span>
                        <b>{member.agent_name}</b>
                        <small>
                          {member.role} ·{" "}
                          {member.active
                            ? member.state
                            : "kicked"}
                        </small>
                      </span>
                      {member.active && room.status === "active" && (
                        <button
                          className="meetingKickButton"
                          disabled={busy}
                          onClick={() => void kickMember(member)}
                          title={
                            "Kick " +
                            member.agent_name +
                            " from this room"
                          }
                        >
                          <UserMinus size={13} />
                          Kick
                        </button>
                      )}
                    </article>
                  ))}
                </div>
              </section>

              <section className="meetingRoomWorkGrid">
                <div className="panel meetingRoomThread">
                  <div className="meetingPanelHeader">
                    <div>
                      <h3>Shared room transcript</h3>
                      <small>
                        Your instructions, peer discussion, reviews, and
                        final confirmations
                      </small>
                    </div>
                  </div>

                  <div
                    className="meetingMessages"
                    ref={messagesRef}
                  >
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
                          <span>
                            {message.kind.replaceAll("_", " ")}
                          </span>
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
                      <div className="meetingSharedTarget">
                        <Users size={14} />
                        <span>
                          <b>Send to the room</b>
                          <small>
                            Every active agent receives the same shared
                            instruction.
                          </small>
                        </span>
                      </div>
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
                      placeholder={
                        activeCollaboration
                          ? "Add a follow-up instruction to the live room..."
                          : "Tell the room what you want the agents to solve together..."
                      }
                      disabled={
                        room.status !== "active" ||
                        room.members.every(
                          (member) => !member.active,
                        )
                      }
                    />

                    <button
                      className="primaryButton"
                      disabled={
                        busy ||
                        room.status !== "active" ||
                        !instruction.trim() ||
                        room.members.every(
                          (member) => !member.active,
                        )
                      }
                    >
                      <Send size={15} />
                      {activeCollaboration
                        ? "Send follow-up"
                        : "Start collaboration"}
                    </button>
                  </form>
                </div>

                <aside className="panel meetingRoomJobs">
                  <div className="meetingPanelHeader">
                    <div>
                      <h3>Executive tracking</h3>
                      <small>
                        Shared progress without assigning a worker
                        manually
                      </small>
                    </div>
                  </div>

                  <div className="meetingJobList">
                    {room.collaborations.length === 0 && (
                      <div className="meetingRoomHint compact">
                        <Users size={17} />
                        <p>
                          Send one instruction to start peer collaboration
                          across all active room members.
                        </p>
                      </div>
                    )}

                    {room.collaborations.map((collaboration) => (
                      <article
                        className={
                          "meetingJob " + collaboration.status
                        }
                        key={collaboration.id}
                      >
                        <header>
                          <span>
                            {collaborationStatusIcon(
                              collaboration.status,
                            )}
                            <b>Shared session</b>
                          </span>
                          <em>
                            {collaboration.status.replaceAll("_", " ")}
                          </em>
                        </header>

                        <p>{collaboration.prompt}</p>

                        <div className="meetingJobProgress">
                          <span>
                            <small>ROUND</small>
                            {collaboration.current_round || "starting"}
                          </span>
                          <span>
                            <small>ACTIVE PEERS</small>
                            {
                              collaboration.participants.filter(
                                (participant) =>
                                  participant.status !== "kicked",
                              ).length
                            }
                          </span>
                        </div>

                        <div className="meetingPeerStatuses">
                          {collaboration.participants.map(
                            (participant) => (
                              <span
                                key={participant.agent_id}
                                className={
                                  participant.status === "kicked"
                                    ? "kicked"
                                    : ""
                                }
                              >
                                <b>{participant.agent_name}</b>
                                <small>
                                  {participant.status.replaceAll(
                                    "_",
                                    " ",
                                  )}
                                </small>
                              </span>
                            ),
                          )}
                        </div>

                        <div className="meetingJobActions">
                          {collaboration.status ===
                            "waiting_approval" && (
                            <button
                              className="primaryButton"
                              disabled={busy}
                              onClick={() =>
                                void approveDelete(collaboration)
                              }
                            >
                              Approve delete & Continue
                            </button>
                          )}

                          {ACTIVE_COLLABORATION_STATUSES.has(
                            collaboration.status,
                          ) && (
                            <button
                              className="dangerButton"
                              disabled={
                                busy ||
                                collaboration.status === "stopping"
                              }
                              onClick={() =>
                                void stopCollaboration(collaboration)
                              }
                            >
                              <CircleStop size={14} />
                              {collaboration.status === "stopping"
                                ? "Stopping..."
                                : "Stop session"}
                            </button>
                          )}
                        </div>
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
