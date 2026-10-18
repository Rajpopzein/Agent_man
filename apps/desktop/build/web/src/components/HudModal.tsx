import { ReactNode } from "react";
import { X } from "lucide-react";

type Props = {
  open: boolean;
  title: string;
  eyebrow?: string;
  children: ReactNode;
  onClose: () => void;
  footer?: ReactNode;
  tone?: "default" | "danger";
};

export default function HudModal({
  open,
  title,
  eyebrow = "AGENT MAN / DIALOG",
  children,
  onClose,
  footer,
  tone = "default",
}: Props) {
  if (!open) return null;

  return (
    <div
      className="hudModalBackdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className={"hudModal " + (tone === "danger" ? "danger" : "")}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header className="hudModalHeader">
          <div>
            <span>{eyebrow}</span>
            <h2>{title}</h2>
          </div>
          <button className="iconButton" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </header>

        <div className="hudModalBody">{children}</div>

        {footer && <footer className="hudModalFooter">{footer}</footer>}
      </section>
    </div>
  );
}
