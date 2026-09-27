import {
  PointerEvent as ReactPointerEvent,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  GripHorizontal,
  TerminalSquare,
  Trash2,
  X,
} from "lucide-react";

export type CommandConsoleLine = {
  id: string;
  timestamp: string;
  source: string;
  status: string;
  message: string;
};

type Props = {
  open: boolean;
  lines: CommandConsoleLine[];
  onClose: () => void;
  onClear: () => void;
};

type Position = {
  x: number;
  y: number;
};

export default function CommandConsole({
  open,
  lines,
  onClose,
  onClear,
}: Props) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{
    active: boolean;
    offsetX: number;
    offsetY: number;
  }>({
    active: false,
    offsetX: 0,
    offsetY: 0,
  });
  const [position, setPosition] =
    useState<Position | null>(null);

  const visibleLines = useMemo(
    () => lines.slice(-250),
    [lines],
  );

  if (!open) return null;

  function beginDrag(
    event: ReactPointerEvent<HTMLDivElement>,
  ) {
    if (
      (event.target as HTMLElement).closest(
        "button",
      )
    ) {
      return;
    }

    const rect =
      panelRef.current?.getBoundingClientRect();
    if (!rect) return;

    dragRef.current = {
      active: true,
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
    };
    event.currentTarget.setPointerCapture(
      event.pointerId,
    );
    if (!position) {
      setPosition({
        x: rect.left,
        y: rect.top,
      });
    }
  }

  function drag(
    event: ReactPointerEvent<HTMLDivElement>,
  ) {
    if (!dragRef.current.active) return;

    const width =
      panelRef.current?.offsetWidth || 640;
    const height =
      panelRef.current?.offsetHeight || 420;
    const x = Math.max(
      8,
      Math.min(
        window.innerWidth - width - 8,
        event.clientX - dragRef.current.offsetX,
      ),
    );
    const y = Math.max(
      8,
      Math.min(
        window.innerHeight - height - 8,
        event.clientY - dragRef.current.offsetY,
      ),
    );
    setPosition({ x, y });
  }

  function endDrag(
    event: ReactPointerEvent<HTMLDivElement>,
  ) {
    dragRef.current.active = false;
    if (
      event.currentTarget.hasPointerCapture(
        event.pointerId,
      )
    ) {
      event.currentTarget.releasePointerCapture(
        event.pointerId,
      );
    }
  }

  return (
    <div
      ref={panelRef}
      className="commandConsole"
      style={
        position
          ? {
              left: position.x,
              top: position.y,
              right: "auto",
            }
          : undefined
      }
    >
      <div
        className="commandConsoleHeader"
        onPointerDown={beginDrag}
        onPointerMove={drag}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <div>
          <GripHorizontal size={14} />
          <TerminalSquare size={14} />
          <span>COMMAND CONSOLE</span>
          <small>LIVE RUNTIME</small>
        </div>
        <div className="commandConsoleActions">
          <button
            type="button"
            onClick={onClear}
            title="Clear console"
          >
            <Trash2 size={13} />
          </button>
          <button
            type="button"
            onClick={onClose}
            title="Close console"
          >
            <X size={14} />
          </button>
        </div>
      </div>

      <div
        className="commandConsoleBody"
        role="log"
        aria-live="polite"
      >
        {visibleLines.length === 0 ? (
          <div className="commandConsoleEmpty">
            <TerminalSquare size={20} />
            <span>
              Runtime events and command output will appear here.
            </span>
          </div>
        ) : (
          visibleLines.map((line) => (
            <div
              className={
                "commandConsoleLine status-" +
                line.status
              }
              key={line.id}
            >
              <time>
                {line.timestamp
                  ? new Date(
                      line.timestamp,
                    ).toLocaleTimeString()
                  : "—"}
              </time>
              <b>{line.source}</b>
              <pre>{line.message}</pre>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
