import React from "react";
import { ActivityEvent } from "../types";

interface TimelineProps {
  events: ActivityEvent[];
}

export const Timeline: React.FC<TimelineProps> = ({ events }) => {
  if (events.length === 0) {
    return (
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 text-center text-xs text-zinc-500">
        No execution events recorded yet.
      </div>
    );
  }

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 shadow-xl space-y-4">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">
        Agent Execution Activity
      </h2>

      <div className="relative pl-6 space-y-6 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-0.5 before:bg-zinc-800">
        {events.map((ev) => {
          let dotClass = "bg-zinc-600";
          if (ev.status === "success") dotClass = "bg-emerald-500";
          if (ev.status === "warning") dotClass = "bg-amber-500";
          if (ev.status === "error") dotClass = "bg-rose-500";
          if (ev.status === "info") dotClass = "bg-sky-500";

          return (
            <div key={ev.id} className="relative group">
              <span
                className={`absolute -left-6 top-1.5 w-2.5 h-2.5 rounded-full border-2 border-zinc-900 ${dotClass}`}
              />
              <div className="flex items-baseline justify-between">
                <h3 className="text-xs font-semibold text-zinc-200">
                  {ev.title}
                </h3>
                <span className="text-[10px] font-mono text-zinc-500">
                  {ev.timestamp}
                </span>
              </div>

              {ev.description && (
                <p className="text-xs text-zinc-400 mt-1 leading-relaxed">
                  {ev.description}
                </p>
              )}

              {ev.metadata?.tech_stack && (
                <div className="flex gap-1.5 mt-2 flex-wrap">
                  {ev.metadata.tech_stack.map((t: string) => (
                    <span
                      key={t}
                      className="text-[10px] bg-zinc-950 border border-zinc-800 px-2 py-0.5 rounded text-zinc-300 font-mono"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
