import React, { useState } from "react";

interface TaskFormProps {
  onSubmit: (workspacePath: string, prompt: string) => Promise<void>;
  isLoading: boolean;
}

export const TaskForm: React.FC<TaskFormProps> = ({ onSubmit, isLoading }) => {
  const [workspacePath, setWorkspacePath] = useState(
    "D:\\irtrixai-coding-assistant\\backend",
  );
  const [prompt, setPrompt] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!workspacePath.trim() || !prompt.trim() || isLoading) return;
    await onSubmit(workspacePath, prompt);
  };

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 shadow-xl">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-400 mb-4">
        New Coding Task
      </h2>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label
            htmlFor="workspace-path"
            className="block text-xs font-medium text-zinc-400 mb-1.5"
          >
            Workspace Absolute Path
          </label>
          <input
            id="workspace-path"
            type="text"
            required
            disabled={isLoading}
            value={workspacePath}
            onChange={(e) => setWorkspacePath(e.target.value)}
            placeholder="e.g. D:\projects\my-app"
            className="w-full px-3.5 py-2 text-sm bg-zinc-950 border border-zinc-800 rounded-lg text-zinc-200 placeholder-zinc-600 focus:outline-none focus:border-indigo-500 font-mono transition-colors disabled:opacity-50"
          />
        </div>

        <div>
          <label
            htmlFor="task-prompt"
            className="block text-xs font-medium text-zinc-400 mb-1.5"
          >
            Task Prompt & Implementation Instructions
          </label>
          <textarea
            id="task-prompt"
            required
            rows={4}
            disabled={isLoading}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="e.g. Implement multiply(a, b) in math_utils.py and add pytest tests."
            className="w-full px-3.5 py-2 text-sm bg-zinc-950 border border-zinc-800 rounded-lg text-zinc-200 placeholder-zinc-600 focus:outline-none focus:border-indigo-500 transition-colors disabled:opacity-50 resize-y"
          />
        </div>

        <div className="flex justify-end pt-2">
          <button
            type="submit"
            disabled={isLoading || !workspacePath.trim() || !prompt.trim()}
            className="px-5 py-2 text-sm font-medium rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-indigo-600/20 flex items-center space-x-2"
          >
            {isLoading ? (
              <>
                <svg
                  className="animate-spin h-4 w-4 text-white"
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                <span>Initializing Agent...</span>
              </>
            ) : (
              <span>Start Task</span>
            )}
          </button>
        </div>
      </form>
    </div>
  );
};
