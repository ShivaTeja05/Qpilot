import { SendHorizontal } from "lucide-react";
import { forwardRef, useState, type KeyboardEvent } from "react";
import { Button, Kbd, Textarea } from "@/ui";
import { MAX_QUESTION } from "./askApi";

/**
 * The question box. Enter sends, Shift+Enter starts a new line, ↑ (at the start of the box)
 * recalls earlier questions and ↓ walks back to the newest and then to what you were typing.
 */
export const Composer = forwardRef<
  HTMLTextAreaElement,
  {
    /** Sends a question; the box is cleared when it returns true. */
    onSend: (question: string) => boolean;
    /** Earlier questions, most recent first. */
    recall: string[];
    disabled?: boolean;
    /** Why sending is not possible right now (shown under the box). */
    disabledReason?: string;
  }
>(function Composer({ onSend, recall, disabled, disabledReason }, ref) {
  const [value, setValue] = useState("");
  // -1: typing a new question; otherwise the index into `recall` being shown.
  const [index, setIndex] = useState(-1);
  const [draft, setDraft] = useState("");

  const send = () => {
    const question = value.trim();
    if (!question || disabled) return;
    if (onSend(question)) {
      setValue("");
      setDraft("");
      setIndex(-1);
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.nativeEvent.isComposing) return;
    const box = e.currentTarget;
    if (e.key === "Enter" && !e.shiftKey && !e.altKey) {
      e.preventDefault();
      send();
      return;
    }
    const atStart = box.selectionStart === 0 && box.selectionEnd === 0;
    const atEnd = box.selectionStart === box.value.length && box.selectionEnd === box.value.length;
    if (
      e.key === "ArrowUp" &&
      (atStart || value === "" || index >= 0) &&
      index < recall.length - 1
    ) {
      e.preventDefault();
      if (index === -1) setDraft(value);
      const next = index + 1;
      setIndex(next);
      setValue(recall[next] ?? "");
      return;
    }
    if (e.key === "ArrowDown" && index >= 0 && atEnd) {
      e.preventDefault();
      const next = index - 1;
      setIndex(next);
      setValue(next === -1 ? draft : (recall[next] ?? ""));
    }
  };

  const empty = value.trim() === "";
  return (
    <form
      className="flex flex-col gap-1.5"
      onSubmit={(e) => {
        e.preventDefault();
        send();
      }}
    >
      <label htmlFor="ask-question" className="sr-only">
        Your question about this study
      </label>
      <div className="flex items-end gap-2">
        <div className="min-w-0 flex-1">
          <Textarea
            id="ask-question"
            ref={ref}
            rows={2}
            maxLength={MAX_QUESTION}
            showCount
            value={value}
            placeholder="Ask about a gene, a choice or the study"
            aria-describedby="ask-keys"
            className="max-h-40 min-h-[4.25rem] resize-none"
            onChange={(e) => {
              setValue(e.target.value);
              if (index !== -1) setIndex(-1);
            }}
            onKeyDown={onKeyDown}
          />
        </div>
        <Button
          type="submit"
          variant="primary"
          disabled={disabled || empty}
          icon={<SendHorizontal />}
          className="mb-px"
        >
          Ask
        </Button>
      </div>
      <p id="ask-keys" className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-xs text-faint">
        {disabled && disabledReason ? (
          <span className="text-muted">{disabledReason}</span>
        ) : (
          <>
            <Kbd>Enter</Kbd> sends · <Kbd>Shift</Kbd>+<Kbd>Enter</Kbd> new line
            {recall.length ? (
              <>
                {" "}
                · <Kbd>↑</Kbd> earlier questions
              </>
            ) : null}
          </>
        )}
      </p>
    </form>
  );
});
