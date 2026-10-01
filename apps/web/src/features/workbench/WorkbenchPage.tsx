import {
  ChangeEvent,
  FormEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Bot,
  ChevronDown,
  ChevronRight,
  Download,
  ExternalLink,
  File,
  FileCode2,
  Folder,
  FolderOpen,
  FolderPlus,
  Play,
  RefreshCw,
  Save,
  Send,
  TerminalSquare,
  Trash2,
  Upload,
} from "lucide-react";

import {
  api,
  BackgroundJob,
  MainAgentMessage,
  ManagedProcess,
  Project,
  ProjectFileEntry,
} from "../../services/api";

type Props = {
  project: Project | null;
  backgroundJobs: BackgroundJob[];
};

type TreeState = Record<string, ProjectFileEntry[]>;

function parentPath(path: string) {
  const parts = path.split(/[\\/]/).filter(Boolean);
  parts.pop();
  return parts.join("/") || ".";
}

function joinPath(parent: string, name: string) {
  return parent === "." ? name : parent.replace(/[\\/]$/, "") + "/" + name;
}

function downloadBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export default function WorkbenchPage({
  project,
  backgroundJobs,
}: Props) {
  const [tree, setTree] = useState<TreeState>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set(["."]));
  const [selected, setSelected] = useState<ProjectFileEntry | null>(null);
  const [content, setContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [chat, setChat] = useState<MainAgentMessage[]>([]);
  const [message, setMessage] = useState("");
  const [processes, setProcesses] = useState<ManagedProcess[]>([]);
  const [selectedProcess, setSelectedProcess] = useState("");
  const [terminalOutput, setTerminalOutput] = useState("");
  const [previewUrl, setPreviewUrl] = useState("");
  const uploadRef = useRef<HTMLInputElement | null>(null);
  const chatRef = useRef<HTMLDivElement | null>(null);

  const dirty = selected?.type === "file" && content !== savedContent;

  async function loadDirectory(path: string, force = false) {
    if (!project) return;
    if (!force && tree[path]) return;
    const rows = await api.projectFiles(project.id, path);
    setTree((current) => ({ ...current, [path]: rows }));
  }

  async function refreshWorkspace() {
    if (!project) return;
    setBusy(true);
    setStatus("");
    try {
      const root = await api.projectFiles(project.id, ".");
      const [messages, running] = await Promise.all([
        api.mainAgentMessages(project.id),
        api.managedProcesses(project.id),
      ]);
      setTree({ ".": root });
      setExpanded(new Set(["."]));
      setChat(messages);
      setProcesses(running);
      if (selected?.type === "file") {
        const fresh = await api.projectFile(project.id, selected.path);
        setContent(fresh.content);
        setSavedContent(fresh.content);
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    setTree({});
    setExpanded(new Set(["."]));
    setSelected(null);
    setContent("");
    setSavedContent("");
    setPreviewUrl("");
    if (project) void refreshWorkspace();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id]);

  useEffect(() => {
    if (!project) return;
    const timer = window.setInterval(async () => {
      try {
        const [messages, running] = await Promise.all([
          api.mainAgentMessages(project.id),
          api.managedProcesses(project.id),
        ]);
        setChat(messages);
        setProcesses(running);
      } catch {
        // Workbench remains usable if background polling is temporarily unavailable.
      }
    }, 2200);
    return () => window.clearInterval(timer);
  }, [project?.id]);

  useEffect(() => {
    const node = chatRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [chat.length]);

  useEffect(() => {
    if (!selectedProcess || !project) {
      setTerminalOutput("");
      return;
    }
    let cancelled = false;
    const load = async () => {
      try {
        const result = await api.processOutput(project.id, selectedProcess);
        if (!cancelled) setTerminalOutput(result.output);
      } catch (error) {
        if (!cancelled) {
          setTerminalOutput(
            error instanceof Error ? error.message : String(error),
          );
        }
      }
    };
    void load();
    const timer = window.setInterval(load, 1800);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [project?.id, selectedProcess]);

  const activeJobs = useMemo(
    () =>
      backgroundJobs.filter((job) =>
        ["queued", "running", "waiting_approval", "stopping"].includes(
          job.status,
        ),
      ),
    [backgroundJobs],
  );

  async function toggleDirectory(entry: ProjectFileEntry) {
    const next = new Set(expanded);
    if (next.has(entry.path)) {
      next.delete(entry.path);
      setExpanded(next);
      return;
    }
    setBusy(true);
    try {
      await loadDirectory(entry.path);
      next.add(entry.path);
      setExpanded(next);
    } finally {
      setBusy(false);
    }
  }

  async function openEntry(entry: ProjectFileEntry) {
    setSelected(entry);
    setStatus("");
    if (!project || entry.type !== "file") return;
    setBusy(true);
    try {
      const result = await api.projectFile(project.id, entry.path);
      setContent(result.content);
      setSavedContent(result.content);
    } catch (error) {
      setContent("");
      setSavedContent("");
      setStatus(
        "This file cannot be opened as editable text. You can still download it. " +
          (error instanceof Error ? error.message : String(error)),
      );
    } finally {
      setBusy(false);
    }
  }

  async function saveFile() {
    if (!project || !selected || selected.type !== "file") return;
    setBusy(true);
    try {
      await api.saveProjectFile(project.id, selected.path, content);
      setSavedContent(content);
      setStatus("Saved " + selected.path);
      await loadDirectory(parentPath(selected.path), true);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function createFile() {
    if (!project) return;
    const base =
      selected?.type === "directory"
        ? selected.path
        : selected
          ? parentPath(selected.path)
          : ".";
    const name = window.prompt("New file name");
    if (!name?.trim()) return;
    const path = joinPath(base, name.trim());
    setBusy(true);
    try {
      await api.saveProjectFile(project.id, path, "");
      await loadDirectory(base, true);
      await openEntry({
        name: name.trim(),
        path,
        type: "file",
        size: 0,
      });
    } finally {
      setBusy(false);
    }
  }

  async function createFolder() {
    if (!project) return;
    const base =
      selected?.type === "directory"
        ? selected.path
        : selected
          ? parentPath(selected.path)
          : ".";
    const name = window.prompt("New folder name");
    if (!name?.trim()) return;
    setBusy(true);
    try {
      await api.createProjectDirectory(
        project.id,
        joinPath(base, name.trim()),
      );
      await loadDirectory(base, true);
    } finally {
      setBusy(false);
    }
  }

  async function renameSelected() {
    if (!project || !selected) return;
    const name = window.prompt("Rename to", selected.name);
    if (!name?.trim() || name.trim() === selected.name) return;
    const destination = joinPath(parentPath(selected.path), name.trim());
    setBusy(true);
    try {
      await api.moveProjectPath(project.id, selected.path, destination);
      const oldParent = parentPath(selected.path);
      setSelected({
        ...selected,
        name: name.trim(),
        path: destination,
      });
      await loadDirectory(oldParent, true);
      setStatus("Renamed to " + destination);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function deleteSelected() {
    if (!project || !selected) return;
    if (
      !window.confirm(
        "Delete " +
          selected.path +
          "? Non-empty folders must be emptied first.",
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      const parent = parentPath(selected.path);
      await api.deleteProjectPath(project.id, selected.path);
      setSelected(null);
      setContent("");
      setSavedContent("");
      await loadDirectory(parent, true);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function downloadSelected() {
    if (!project || !selected || selected.type !== "file") return;
    try {
      const result = await api.downloadProjectFile(
        project.id,
        selected.path,
      );
      downloadBlob(result, selected.name);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  async function exportProject() {
    if (!project) return;
    setBusy(true);
    try {
      const result = await api.exportProject(project.id);
      downloadBlob(
        result,
        project.name.replace(/[^a-z0-9_-]+/gi, "-") + ".zip",
      );
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function uploadFile(event: ChangeEvent<HTMLInputElement>) {
    if (!project || !event.target.files?.length) return;
    const file = event.target.files[0];
    const base =
      selected?.type === "directory"
        ? selected.path
        : selected
          ? parentPath(selected.path)
          : ".";
    setBusy(true);
    try {
      await api.uploadProjectFile(
        project.id,
        joinPath(base, file.name),
        await file.arrayBuffer(),
      );
      await loadDirectory(base, true);
      setStatus("Uploaded " + file.name);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      event.target.value = "";
      setBusy(false);
    }
  }

  async function sendChat(event: FormEvent) {
    event.preventDefault();
    if (!project || !message.trim() || busy) return;
    const text = message.trim();
    setMessage("");
    setBusy(true);
    try {
      await api.chatMainAgent(
        project.id,
        selected
          ? text +
            "\n\nWorkbench selection: " +
            selected.path
          : text,
        true,
        false,
        true,
        false,
      );
      setChat(await api.mainAgentMessages(project.id));
      await loadDirectory(".", true);
    } catch (error) {
      setMessage(text);
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  function renderDirectory(path: string, depth = 0): React.ReactNode {
    const rows = tree[path] || [];
    return rows.map((entry) => {
      const open =
        entry.type === "directory" && expanded.has(entry.path);
      return (
        <div key={entry.path}>
          <button
            className={
              "workbenchTreeRow " +
              (selected?.path === entry.path ? "active" : "")
            }
            style={{ paddingLeft: 10 + depth * 16 }}
            onClick={() =>
              entry.type === "directory"
                ? void toggleDirectory(entry)
                : void openEntry(entry)
            }
          >
            <span className="workbenchChevron">
              {entry.type === "directory" ? (
                open ? <ChevronDown /> : <ChevronRight />
              ) : null}
            </span>
            {entry.type === "directory" ? (
              open ? <FolderOpen /> : <Folder />
            ) : (
              <File />
            )}
            <span>{entry.name}</span>
            {entry.type === "file" && entry.size !== null && (
              <small>{Math.max(1, Math.round(entry.size / 1024))} KB</small>
            )}
          </button>
          {open && renderDirectory(entry.path, depth + 1)}
        </div>
      );
    });
  }

  if (!project) {
    return (
      <section className="panel workbenchEmpty">
        <FolderOpen />
        <h3>Select or create a project</h3>
        <p>The Workbench operates on the project's real workspace path.</p>
      </section>
    );
  }

  return (
    <section className="workbenchPage">
      <div className="workbenchToolbar">
        <div>
          <strong>{project.name}</strong>
          <code>{project.workspace_path}</code>
        </div>
        <div className="workbenchToolbarActions">
          <button onClick={createFile} disabled={busy}>
            <FileCode2 /> New file
          </button>
          <button onClick={createFolder} disabled={busy}>
            <FolderPlus /> New folder
          </button>
          <button onClick={() => uploadRef.current?.click()} disabled={busy}>
            <Upload /> Upload
          </button>
          <input
            ref={uploadRef}
            type="file"
            hidden
            onChange={uploadFile}
          />
          <button onClick={refreshWorkspace} disabled={busy}>
            <RefreshCw /> Refresh
          </button>
          <button className="primaryButton" onClick={exportProject} disabled={busy}>
            <Download /> Export ZIP
          </button>
        </div>
      </div>

      <div className="workbenchGrid">
        <aside className="panel workbenchExplorer">
          <div className="workbenchPanelTitle">
            <FolderOpen />
            <span>Explorer</span>
          </div>
          <div className="workbenchTree">{renderDirectory(".")}</div>
          {selected && (
            <div className="workbenchSelectionActions">
              <button onClick={renameSelected}>Rename</button>
              {selected.type === "file" && (
                <button onClick={downloadSelected}>
                  <Download /> Download
                </button>
              )}
              <button className="dangerText" onClick={deleteSelected}>
                <Trash2 /> Delete
              </button>
            </div>
          )}
        </aside>

        <main className="panel workbenchEditor">
          <div className="workbenchEditorHeader">
            <div>
              <span>EDITOR</span>
              <strong>{selected?.path || "Select a file"}</strong>
            </div>
            {selected?.type === "file" && (
              <button
                className="primaryButton"
                onClick={saveFile}
                disabled={!dirty || busy}
              >
                <Save /> {dirty ? "Save" : "Saved"}
              </button>
            )}
          </div>
          {selected?.type === "file" ? (
            <textarea
              className="workbenchCodeEditor"
              value={content}
              onChange={(event) => setContent(event.target.value)}
              spellCheck={false}
            />
          ) : (
            <div className="workbenchEditorBlank">
              <FileCode2 />
              <strong>Project editor</strong>
              <span>Select a text file from Explorer to edit it.</span>
            </div>
          )}
        </main>

        <aside className="panel workbenchAgentPanel">
          <div className="workbenchPanelTitle">
            <Bot />
            <span>Agent Man</span>
          </div>
          <div className="workbenchChat" ref={chatRef}>
            {chat.length === 0 && (
              <div className="workbenchChatEmpty">
                Ask Agent Man to work on this project or the selected file.
              </div>
            )}
            {chat.map((item) => (
              <article key={item.id} className={"workbenchChatMessage " + item.role}>
                <small>{item.role === "user" ? "YOU" : "AGENT MAN"}</small>
                <p>{item.content}</p>
              </article>
            ))}
          </div>
          <form className="workbenchChatComposer" onSubmit={sendChat}>
            {selected && <small>CONTEXT · {selected.path}</small>}
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder="Ask Agent Man to change, inspect, test, or explain..."
            />
            <button className="primaryButton" disabled={busy || !message.trim()}>
              <Send /> Send
            </button>
          </form>
          <div className="workbenchAgentActivity">
            <strong>ACTIVE AGENTS</strong>
            {activeJobs.length === 0 ? (
              <span>No agent work in progress.</span>
            ) : (
              activeJobs.slice(0, 4).map((job) => (
                <article key={job.id}>
                  <b>{job.agent_name}</b>
                  <small>{job.current_action || job.task}</small>
                  <em>{job.current_tool || job.current_phase || job.status}</em>
                </article>
              ))
            )}
          </div>
        </aside>
      </div>

      <div className="workbenchBottomGrid">
        <section className="panel workbenchTerminal">
          <div className="workbenchPanelTitle">
            <TerminalSquare />
            <span>Terminal / Processes</span>
            <select
              value={selectedProcess}
              onChange={(event) => setSelectedProcess(event.target.value)}
            >
              <option value="">Select process</option>
              {processes.map((process) => (
                <option key={process.id} value={process.id}>
                  {process.command} · {process.status}
                </option>
              ))}
            </select>
          </div>
          <pre>
            {selectedProcess
              ? terminalOutput || "No output yet."
              : "Start a project process through Agent Man to inspect its output here."}
          </pre>
        </section>

        <section className="panel workbenchPreview">
          <div className="workbenchPanelTitle">
            <Play />
            <span>Live Preview</span>
            <input
              value={previewUrl}
              onChange={(event) => setPreviewUrl(event.target.value)}
              placeholder="http://localhost:5173"
            />
            {previewUrl && (
              <a href={previewUrl} target="_blank" rel="noreferrer">
                <ExternalLink />
              </a>
            )}
          </div>
          {previewUrl ? (
            <iframe title="Project preview" src={previewUrl} />
          ) : (
            <div className="workbenchPreviewBlank">
              Enter the running app URL to preview it inside the Workbench.
            </div>
          )}
        </section>
      </div>

      {status && <div className="connectionStatus">{status}</div>}
    </section>
  );
}
