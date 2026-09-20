import React, { useEffect, useState } from "react";
import {
  AlertCircle,
  Cpu,
  FolderPlus,
  HardDrive,
  Plus,
  RotateCw,
} from "lucide-react";
import { createWorkspace, getProviders, getWorkspaces } from "../services/api";
import { ProviderOption, WorkspaceResponse } from "../types";

interface TaskFormProps {
  onSubmit: (
    workspaceId: string,
    prompt: string,
    provider?: string,
    model?: string,
  ) => Promise<void>;
  isLoading: boolean;
}

export const TaskForm: React.FC<TaskFormProps> = ({ onSubmit, isLoading }) => {
  const [workspaces, setWorkspaces] = useState<WorkspaceResponse[]>([]);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string>("");
  const [prompt, setPrompt] = useState("");

  // Provider & Model State
  const [providers, setProviders] = useState<ProviderOption[]>([]);
  const [selectedProviderId, setSelectedProviderId] = useState<string>("");
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [isLoadingProviders, setIsLoadingProviders] = useState(true);

  const [isLoadingWorkspaces, setIsLoadingWorkspaces] = useState(true);
  const [workspaceLoadError, setWorkspaceLoadError] = useState<string | null>(
    null,
  );

  // Inline "Add Workspace" state
  const [showAddForm, setShowAddForm] = useState(false);
  const [newWsName, setNewWsName] = useState("");
  const [newWsPath, setNewWsPath] = useState("");
  const [isRegistering, setIsRegistering] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const loadData = async () => {
    setIsLoadingWorkspaces(true);
    setIsLoadingProviders(true);
    setWorkspaceLoadError(null);

    try {
      const [wsList, provData] = await Promise.all([
        getWorkspaces(),
        getProviders(),
      ]);

      setWorkspaces(wsList);
      if (wsList.length > 0) {
        setSelectedWorkspaceId(wsList[0].id);
      }

      setProviders(provData.providers);
      const defaultProv =
        provData.providers.find((p) => p.id === provData.default_provider) ||
        provData.providers.find((p) => p.available) ||
        provData.providers[0];

      if (defaultProv) {
        setSelectedProviderId(defaultProv.id);
        setSelectedModel(defaultProv.default_model);
      }
    } catch (err: any) {
      setWorkspaceLoadError(err.message || "Failed to load initial data.");
    } finally {
      setIsLoadingWorkspaces(false);
      setIsLoadingProviders(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleRegisterWorkspace = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newWsName.trim() || !newWsPath.trim()) return;

    setIsRegistering(true);
    setAddError(null);
    try {
      const created = await createWorkspace(newWsName.trim(), newWsPath.trim());
      setNewWsName("");
      setNewWsPath("");
      setShowAddForm(false);
      const updatedList = await getWorkspaces();
      setWorkspaces(updatedList);
      setSelectedWorkspaceId(created.id);
    } catch (err: any) {
      setAddError(err.message || "Workspace registration failed.");
    } finally {
      setIsRegistering(false);
    }
  };

  const selectedProviderObj = providers.find(
    (p) => p.id === selectedProviderId,
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (
      !selectedWorkspaceId ||
      !prompt.trim() ||
      !selectedProviderObj?.available ||
      !selectedModel.trim() ||
      isLoading
    ) {
      return;
    }
    await onSubmit(
      selectedWorkspaceId,
      prompt,
      selectedProviderId,
      selectedModel,
    );
  };

  const selectedWorkspace = workspaces.find(
    (w) => w.id === selectedWorkspaceId,
  );

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 shadow-xl space-y-4">
      <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">
          New Coding Task
        </h2>
        <button
          type="button"
          onClick={() => setShowAddForm(!showAddForm)}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium text-emerald-400 hover:text-emerald-300 bg-emerald-950/40 hover:bg-emerald-900/50 border border-emerald-800/60 transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>Add Workspace</span>
        </button>
      </div>

      {/* Inline Registration Sub-form */}
      {showAddForm && (
        <form
          onSubmit={handleRegisterWorkspace}
          className="p-4 bg-zinc-950/80 border border-zinc-800 rounded-lg space-y-3"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-zinc-200 flex items-center gap-1.5">
              <FolderPlus className="w-4 h-4 text-emerald-400" />
              Register Workspace Directory
            </span>
            <button
              type="button"
              onClick={() => setShowAddForm(false)}
              className="text-xs text-zinc-500 hover:text-zinc-300"
            >
              Cancel
            </button>
          </div>

          {addError && (
            <div className="p-2.5 bg-rose-950/40 border border-rose-800 rounded text-rose-300 text-xs">
              {addError}
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] font-mono text-zinc-400 mb-1">
                Workspace Name
              </label>
              <input
                type="text"
                placeholder="e.g. backend-service"
                required
                value={newWsName}
                onChange={(e) => setNewWsName(e.target.value)}
                className="w-full px-3 py-1.5 bg-zinc-900 border border-zinc-800 rounded text-xs text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-emerald-500 font-mono"
              />
            </div>
            <div>
              <label className="block text-[11px] font-mono text-zinc-400 mb-1">
                Absolute Host Root Path
              </label>
              <input
                type="text"
                placeholder="e.g. D:\projects\my-app"
                required
                value={newWsPath}
                onChange={(e) => setNewWsPath(e.target.value)}
                className="w-full px-3 py-1.5 bg-zinc-900 border border-zinc-800 rounded text-xs text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-emerald-500 font-mono"
              />
            </div>
          </div>

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={isRegistering || !newWsName.trim() || !newWsPath.trim()}
              className="px-3.5 py-1.5 rounded bg-emerald-400 hover:bg-emerald-300 text-emerald-950 text-xs font-semibold disabled:opacity-50 transition-colors"
            >
              {isRegistering ? "Registering..." : "Save and Select"}
            </button>
          </div>
        </form>
      )}

      {/* Main Task Form */}
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Runtime LLM Provider & Model Selection */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label
              htmlFor="provider-select"
              className="block text-xs font-medium text-zinc-400 mb-1.5"
            >
              LLM Provider
            </label>
            <div className="relative">
              <select
                id="provider-select"
                disabled={isLoading || isLoadingProviders}
                value={selectedProviderId}
                onChange={(e) => {
                  const newProvId = e.target.value;
                  setSelectedProviderId(newProvId);
                  const found = providers.find((p) => p.id === newProvId);
                  if (found) {
                    setSelectedModel(found.default_model);
                  }
                }}
                className="w-full px-3.5 py-2 text-sm bg-zinc-950 border border-zinc-800 rounded-lg text-zinc-200 focus:outline-none focus:border-indigo-500 font-mono transition-colors disabled:opacity-50 appearance-none pr-8 cursor-pointer"
              >
                {providers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}{" "}
                    {!p.available
                      ? `(Unavailable — ${p.reason || "Not configured"})`
                      : ""}
                  </option>
                ))}
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2.5 text-zinc-500">
                ▼
              </div>
            </div>

            {selectedProviderObj && !selectedProviderObj.available && (
              <div className="mt-1 flex items-center gap-1.5 text-[11px] font-mono text-amber-400/90">
                <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                <span>Unavailable: {selectedProviderObj.reason}</span>
              </div>
            )}
          </div>

          <div>
            <label
              htmlFor="model-select"
              className="block text-xs font-medium text-zinc-400 mb-1.5"
            >
              Model Identifier
            </label>
            <div className="relative">
              <select
                id="model-select"
                disabled={
                  isLoading ||
                  isLoadingProviders ||
                  !selectedProviderObj?.available
                }
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                className="w-full px-3.5 py-2 text-sm bg-zinc-950 border border-zinc-800 rounded-lg text-zinc-200 focus:outline-none focus:border-indigo-500 font-mono transition-colors disabled:opacity-50 appearance-none pr-8 cursor-pointer"
              >
                {selectedProviderObj?.models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2.5 text-zinc-500">
                ▼
              </div>
            </div>
            {selectedModel && (
              <div className="flex items-center gap-1 text-[11px] font-mono text-zinc-500 mt-1 px-1">
                <Cpu className="w-3 h-3 text-cyan-400 shrink-0" />
                <span className="truncate">Active model: {selectedModel}</span>
              </div>
            )}
          </div>
        </div>

        {/* Workspace Selector */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label
              htmlFor="workspace-select"
              className="block text-xs font-medium text-zinc-400"
            >
              Registered Workspace
            </label>
            {workspaceLoadError && (
              <button
                type="button"
                onClick={() => loadData()}
                className="text-[11px] text-amber-400 hover:text-amber-300 flex items-center gap-1"
              >
                <RotateCw className="w-3 h-3" /> Retry
              </button>
            )}
          </div>

          {isLoadingWorkspaces ? (
            <div className="w-full px-3.5 py-2 text-xs bg-zinc-950 border border-zinc-800 rounded-lg text-zinc-500 font-mono flex items-center gap-2">
              <RotateCw className="w-3.5 h-3.5 animate-spin text-cyan-400" />
              Loading workspaces...
            </div>
          ) : workspaces.length === 0 ? (
            <div className="p-3 bg-zinc-950/60 border border-amber-900/40 rounded-lg text-xs text-amber-400/90 flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>
                No registered workspaces found. Use "+ Add Workspace" above to
                register one.
              </span>
            </div>
          ) : (
            <div className="space-y-1.5">
              <div className="relative">
                <select
                  id="workspace-select"
                  disabled={isLoading}
                  value={selectedWorkspaceId}
                  onChange={(e) => setSelectedWorkspaceId(e.target.value)}
                  className="w-full px-3.5 py-2 text-sm bg-zinc-950 border border-zinc-800 rounded-lg text-zinc-200 focus:outline-none focus:border-indigo-500 font-mono transition-colors disabled:opacity-50 appearance-none pr-8 cursor-pointer"
                >
                  {workspaces.map((ws) => (
                    <option key={ws.id} value={ws.id}>
                      {ws.name} ({ws.root_path})
                    </option>
                  ))}
                </select>
                <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2.5 text-zinc-500">
                  ▼
                </div>
              </div>

              {selectedWorkspace && (
                <div className="flex items-center gap-1.5 text-[11px] font-mono text-zinc-500 px-1 truncate">
                  <HardDrive className="w-3 h-3 text-cyan-400 shrink-0" />
                  <span className="truncate">
                    {selectedWorkspace.root_path}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Task Prompt */}
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
            disabled={
              isLoading ||
              !selectedWorkspaceId ||
              !prompt.trim() ||
              !selectedProviderObj?.available ||
              !selectedModel.trim()
            }
            className="px-5 py-2 text-sm font-medium rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-indigo-600/20 flex items-center space-x-2"
          >
            {isLoading ? (
              <>
                <RotateCw className="animate-spin h-4 w-4 text-white" />
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
