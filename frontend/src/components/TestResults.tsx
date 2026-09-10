import React from "react";
import { TestResultData } from "../types";

interface TestResultsProps {
  testResult: TestResultData | null;
}

export const TestResults: React.FC<TestResultsProps> = ({ testResult }) => {
  if (!testResult) return null;

  const isPassed = testResult.success === true;
  const commandStr = Array.isArray(testResult.command)
    ? testResult.command.join(" ")
    : testResult.command || "pytest";

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 shadow-xl space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">
          Sandbox Test Execution
        </h2>
        <span
          className={`text-xs px-2.5 py-0.5 rounded-full font-medium border ${
            isPassed
              ? "bg-emerald-950 text-emerald-400 border-emerald-800"
              : "bg-rose-950 text-rose-400 border-rose-800"
          }`}
        >
          {isPassed ? "Passed" : "Failed"}
        </span>
      </div>

      <div className="text-xs font-mono text-zinc-400 bg-zinc-950 p-2.5 rounded border border-zinc-800 flex justify-between">
        <span>Command: {commandStr}</span>
        {testResult.exit_code !== undefined &&
          testResult.exit_code !== null && (
            <span>Exit Code: {testResult.exit_code}</span>
          )}
      </div>

      {(testResult.stdout || testResult.output || testResult.stderr) && (
        <div className="bg-zinc-950 border border-zinc-800 rounded-lg p-3 max-h-48 overflow-auto">
          <pre className="text-xs font-mono text-zinc-300 whitespace-pre-wrap">
            {testResult.stdout || testResult.output || testResult.stderr}
          </pre>
        </div>
      )}
    </div>
  );
};
