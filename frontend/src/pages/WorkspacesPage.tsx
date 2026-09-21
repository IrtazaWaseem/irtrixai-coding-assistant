import React, { useEffect, useState } from "react";
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  File,
  FileCode,
  Folder,
  FolderOpen,
  FolderPlus,
  FolderTree,
  HardDrive,
  Plus,
  RotateCw,
  Search,
} from "lucide-react";
import { useTaskExecution } from "../context/TaskContext";
import {
  createWorkspace,
  getWorkspaces,
  getWorkspaceTree,
} from "../services/api";
import { FileNode, WorkspaceResponse, WorkspaceTreeResponse } from "../types";

const formatBytes = (bytes?: number) => {
  if (bytes === undefined || bytes === null) return "";
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
};

const TreeNodeItem: React.FC<{
  node: FileNode;
  selectedPath: string | null;
  onSelect: (node: FileNode) => void;
}> = ({ node, selectedPath, onSelect }) => {
  const [isOpen, setIsOpen] = useState(true);
  const isDirectory = node.type === "directory";
  const isSelected = selectedPath === node.path;

  return (
    <div className="select-none text-xs">
      <div
        onClick={() => {
          if (isDirectory) setIsOpen(!isOpen);
          onSelect(node);
        }}
        className={`flex items-center gap-1.5 py-1 px-2 rounded-md cursor-pointer transition-colors font-mono ${
          isSelected
            ? "bg-zinc-800 text-zinc-100 border border-zinc-700/80"
            : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40"
        }`}
      >
        {isDirectory ? (
          <>
            {isOpen ? (
              <ChevronDown className="w-3 h-3 text-zinc-500 shrink-0" />
            ) : (
              <ChevronRight className="w-3 h-3 text-zinc-500 shrink-0" />
            )}
            {isOpen ? (
              <FolderOpen className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
            ) : (
              <Folder className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
            )}
          </>
        ) : (
          <>
            <span className="w-3 shrink-0" />
            {node.name.endsWith(".py") ||
            node.name.endsWith(".ts") ||
            node.name.endsWith(".tsx") ||
            node.name.endsWith(".json") ? (
              <FileCode className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
            ) : (
              <File className="w-3.5 h-3.5 text-zinc-500 shrink-0" />
            )}
          </>
        )}
        <span className="truncate flex-1">{node.name}</span>
        {node.size !== undefined && (
          <span className="text-[10px] text-zinc-600 font-mono shrink-0 ml-2">
            {formatBytes(node.size)}
          </span>
        )}
      </div>

      {isDirectory && isOpen && node.children && (
        <div className="pl-3.5 border-l border-zinc-800/80 ml-2 mt-0.5 space-y-0.5">
          {node.children.map((child) => (
            <TreeNodeItem
              key={child.path}
              node={child}
              selectedPath={selectedPath}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export const WorkspacesPage: React.FC = () => {
  const { setActiveWorkspaceId } = useTaskExecution();

  const [workspaces, setWorkspaces] = useState<WorkspaceResponse[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] =
    useState<WorkspaceResponse | null>(null);
  const [treeData, setTreeData] = useState<WorkspaceTreeResponse | null>(null);
  const [selectedNode, setSelectedNode] = useState<FileNode | null>(null);

  const [isLoadingWorkspaces, setIsLoadingWorkspaces] = useState(true);
  const [isLoadingTree, setIsLoadingTree] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [treeError, setTreeError] = useState<string | null>(null);

  // Search Filter
  const [filterQuery, setFilterQuery] = useState("");

  // Registration Form
  const [showRegisterForm, setShowRegisterForm] = useState(false);
  const [wsName, setWsName] = useState("");
  const [wsPath, setWsPath] = useState("");
  const [isRegistering, setIsRegistering] = useState(false);

  const loadWorkspaces = async () => {
    setIsLoadingWorkspaces(true);
    setPageError(null);
    try {
      const list = await getWorkspaces();
      setWorkspaces(list);
      if (list.length > 0 && !selectedWorkspace) {
        setSelectedWorkspace(list[0]);
        setActiveWorkspaceId(list[0].id);
      }
    } catch (err: any) {
      setPageError(err.message || "Failed to load workspaces.");
    } finally {
      setIsLoadingWorkspaces(false);
    }
  };

  const loadTree = async (workspaceId: string) => {
    setIsLoadingTree(true);
    setTreeError(null);
    setTreeData(null);
    setSelectedNode(null);
    try {
      const res = await getWorkspaceTree(workspaceId, 3);
      setTreeData(res);
    } catch (err: any) {
      setTreeError(
        err.message || "Workspace directory is inaccessible on disk.",
      );
    } finally {
      setIsLoadingTree(false);
    }
  };

  useEffect(() => {
    loadWorkspaces();
  }, []);

  useEffect(() => {
    if (selectedWorkspace) {
      loadTree(selectedWorkspace.id);
    }
  }, [selectedWorkspace]);

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!wsName.trim() || !wsPath.trim()) return;
    setIsRegistering(true);
    setPageError(null);
    try {
      const created = await createWorkspace(wsName.trim(), wsPath.trim());
      setWorkspaces((prev) => [created, ...prev]);
      setSelectedWorkspace(created);
      setActiveWorkspaceId(created.id);
      setWsName("");
      setWsPath("");
      setShowRegisterForm(false);
    } catch (err: any) {
      setPageError(err.message || "Workspace registration rejected.");
    } finally {
      setIsRegistering(false);
    }
  };

  const filteredWorkspaces = workspaces.filter(
    (ws) =>
      ws.name.toLowerCase().includes(filterQuery.toLowerCase()) ||
      ws.root_path.toLowerCase().includes(filterQuery.toLowerCase()),
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-zinc-100">Workspaces</h1>
          <p className="text-xs text-zinc-400 mt-0.5">
            Registered project roots and sandboxed filesystem trees.
          </p>
        </div>
        <button
          onClick={() => setShowRegisterForm(!showRegisterForm)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-emerald-950 bg-emerald-400 hover:bg-emerald-300 transition-colors shadow-sm"
        >
          <Plus className="w-3.5 h-3.5 text-emerald-950" />
          <span>Register Workspace</span>
        </button>
      </div>

      {pageError && (
        <div className="bg-rose-950/30 border border-rose-800/70 text-rose-300 p-4 rounded-xl text-xs flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
            <span className="font-mono">{pageError}</span>
          </div>
          <button
            onClick={() => setPageError(null)}
            className="underline hover:text-rose-200 ml-4 font-semibold"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Inline Registration Form */}
      {showRegisterForm && (
        <form
          onSubmit={handleRegister}
          className="p-4 bg-zinc-900 border border-zinc-800 rounded-xl space-y-3 shadow-lg"
        >
          <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-300 flex items-center gap-1.5 font-mono">
            <FolderPlus className="w-4 h-4 text-emerald-400" />
            <span>Register Host Workspace Directory</span>
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] font-mono text-zinc-400 mb-1">
                Workspace Name
              </label>
              <input
                type="text"
                placeholder="e.g. backend-service"
                value={wsName}
                onChange={(e) => setWsName(e.target.value)}
                className="w-full px-3 py-1.5 bg-zinc-950 border border-zinc-800 rounded-lg text-xs text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-emerald-500 font-mono"
              />
            </div>
            <div>
              <label className="block text-[11px] font-mono text-zinc-400 mb-1">
                Absolute Host Root Path
              </label>
              <input
                type="text"
                placeholder="e.g. D:\irtrixai-coding-assistant\backend"
                value={wsPath}
                onChange={(e) => setWsPath(e.target.value)}
                className="w-full px-3 py-1.5 bg-zinc-950 border border-zinc-800 rounded-lg text-xs text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-emerald-500 font-mono"
              />
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={() => setShowRegisterForm(false)}
              className="px-3 py-1 rounded text-xs text-zinc-400 hover:text-zinc-200"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isRegistering || !wsName || !wsPath}
              className="px-4 py-1 rounded-lg bg-emerald-400 hover:bg-emerald-300 text-xs font-semibold text-emerald-950 disabled:opacity-50 transition-colors"
            >
              {isRegistering ? "Registering..." : "Save Workspace"}
            </button>
          </div>
        </form>
      )}

      {/* Two-Pane Workspace Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Pane: Workspace List & Filter */}
        <div className="lg:col-span-4 bg-zinc-900 border border-zinc-800 rounded-xl p-4 space-y-3 shadow-lg">
          <div className="flex items-center justify-between text-xs text-zinc-400 border-b border-zinc-800 pb-2">
            <span className="font-semibold uppercase tracking-wider text-[10px] font-mono text-zinc-400">
              Registered Directories
            </span>
            <span className="font-mono text-zinc-500">{workspaces.length}</span>
          </div>

          {/* Search Filter */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-zinc-500 absolute left-2.5 top-2.5" />
            <input
              type="text"
              placeholder="Filter workspaces..."
              value={filterQuery}
              onChange={(e) => setFilterQuery(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 bg-zinc-950 border border-zinc-800 rounded-lg text-xs text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-emerald-500 font-mono"
            />
          </div>

          {isLoadingWorkspaces ? (
            <div className="p-8 text-center text-xs text-zinc-500 font-mono">
              Loading workspaces...
            </div>
          ) : filteredWorkspaces.length === 0 ? (
            <div className="p-8 text-center space-y-2">
              <FolderTree className="w-8 h-8 text-zinc-700 mx-auto" />
              <p className="text-xs text-zinc-400">
                {workspaces.length === 0
                  ? "No workspaces registered."
                  : "No matching workspaces."}
              </p>
            </div>
          ) : (
            <div className="space-y-1.5 max-h-[480px] overflow-y-auto pr-1">
              {filteredWorkspaces.map((ws) => {
                const isSelected = selectedWorkspace?.id === ws.id;
                return (
                  <button
                    key={ws.id}
                    onClick={() => {
                      setSelectedWorkspace(ws);
                      setActiveWorkspaceId(ws.id);
                    }}
                    className={`w-full text-left p-3 rounded-lg border transition-all ${
                      isSelected
                        ? "bg-zinc-800/80 border-emerald-500/50 text-zinc-100 shadow-sm"
                        : "bg-zinc-950/40 border-zinc-800/80 text-zinc-400 hover:bg-zinc-800/40 hover:text-zinc-200"
                    }`}
                  >
                    <div className="font-medium text-xs text-zinc-200 truncate flex items-center justify-between">
                      <span>{ws.name}</span>
                      {isSelected && (
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                      )}
                    </div>
                    <div className="font-mono text-[10px] text-zinc-500 truncate mt-1">
                      {ws.root_path}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Right Pane: Directory Tree */}
        <div className="lg:col-span-8 bg-zinc-900 border border-zinc-800 rounded-xl p-5 flex flex-col space-y-4 min-h-[480px] shadow-lg">
          {selectedWorkspace ? (
            <>
              <div className="border-b border-zinc-800 pb-3 flex items-center justify-between">
                <div className="min-w-0 pr-4">
                  <div className="flex items-center gap-2">
                    <HardDrive className="w-4 h-4 text-cyan-400 shrink-0" />
                    <h2 className="text-sm font-semibold text-zinc-100 truncate">
                      {selectedWorkspace.name}
                    </h2>
                  </div>
                  <p className="font-mono text-[11px] text-zinc-500 mt-1 truncate">
                    {selectedWorkspace.root_path}
                  </p>
                </div>
                {treeData && (
                  <span className="text-[11px] font-mono text-zinc-400 bg-zinc-950 px-2.5 py-1 rounded border border-zinc-800 shrink-0">
                    {treeData.total_entries} entries
                  </span>
                )}
              </div>

              {/* Directory Tree */}
              <div className="flex-1 overflow-y-auto max-h-[420px] pr-2">
                {isLoadingTree ? (
                  <div className="p-12 text-center text-xs text-zinc-500 font-mono flex items-center justify-center gap-2">
                    <RotateCw className="w-3.5 h-3.5 animate-spin text-cyan-400" />
                    <span>Scanning directory tree...</span>
                  </div>
                ) : treeError ? (
                  <div className="p-6 text-center space-y-2.5 bg-zinc-950/50 rounded-xl border border-zinc-800 my-4">
                    <AlertCircle className="w-5 h-5 text-amber-400 mx-auto" />
                    <div className="text-xs font-semibold text-zinc-200">
                      Filesystem Directory Inaccessible
                    </div>
                    <p className="text-[11px] text-zinc-500 font-mono break-all max-w-md mx-auto">
                      {selectedWorkspace.root_path}
                    </p>
                    <p className="text-[11px] text-zinc-400 max-w-sm mx-auto">
                      This directory path does not exist on your host system.
                      Select or register a valid local repository root.
                    </p>
                  </div>
                ) : treeData && treeData.tree.length > 0 ? (
                  <div className="space-y-0.5">
                    {treeData.tree.map((node) => (
                      <TreeNodeItem
                        key={node.path}
                        node={node}
                        selectedPath={selectedNode?.path || null}
                        onSelect={setSelectedNode}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="p-12 text-center text-xs text-zinc-500 font-mono">
                    Workspace directory is empty or contains only ignored paths.
                  </div>
                )}
              </div>

              {/* Selected Node Metadata */}
              {selectedNode && (
                <div className="border-t border-zinc-800 pt-3 bg-zinc-950/60 p-3 rounded-lg space-y-1.5 font-mono">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-zinc-300 font-medium truncate">
                      {selectedNode.path}
                    </span>
                    <span className="text-zinc-500 text-[11px]">
                      {formatBytes(selectedNode.size)}
                    </span>
                  </div>
                  {selectedNode.type === "file" && (
                    <div className="text-[10px] text-zinc-500 italic">
                      Direct file viewing is restricted to verified diff
                      reviews.
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-zinc-600 text-xs">
              <FolderTree className="w-10 h-10 mb-2 stroke-1 text-zinc-700" />
              <span>Select a workspace to view its filesystem structure</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
