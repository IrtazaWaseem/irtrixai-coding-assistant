import React, { useCallback, useEffect, useRef, useState } from "react";
import Editor from "@monaco-editor/react";
import {
  AlertCircle,
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  Code2,
  File,
  FileCode,
  Folder,
  FolderOpen,
  FolderTree,
  Loader2,
  RotateCw,
  Save,
} from "lucide-react";
import {
  getWorkspaceFile,
  getWorkspaceTree,
  saveWorkspaceFile,
} from "../services/api";
import { FileNode, WorkspaceTreeResponse } from "../types";

interface CodeWorkspaceProps {
  workspaceId: string | null;
}

const formatBytes = (bytes?: number) => {
  if (bytes === undefined || bytes === null) return "";
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
};

const getLanguageFromPath = (path: string): string => {
  const ext = path.split(".").pop()?.toLowerCase() || "";
  const name = path.split("/").pop()?.toLowerCase() || "";

  if (name === "dockerfile" || name.startsWith("dockerfile."))
    return "dockerfile";
  if (name === "makefile") return "makefile";

  switch (ext) {
    case "py":
    case "pyi":
      return "python";
    case "ts":
    case "tsx":
      return "typescript";
    case "js":
    case "jsx":
    case "mjs":
    case "cjs":
      return "javascript";
    case "json":
      return "json";
    case "html":
    case "htm":
      return "html";
    case "css":
    case "scss":
    case "less":
      return "css";
    case "md":
    case "markdown":
      return "markdown";
    case "yaml":
    case "yml":
      return "yaml";
    case "toml":
    case "ini":
      return "ini";
    case "sh":
    case "bash":
    case "zsh":
      return "shell";
    case "sql":
      return "sql";
    case "rs":
      return "rust";
    case "go":
      return "go";
    case "java":
      return "java";
    case "c":
    case "h":
    case "cpp":
    case "hpp":
      return "cpp";
    case "xml":
    case "svg":
      return "xml";
    default:
      return "plaintext";
  }
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
            ? "bg-zinc-800 text-zinc-100 border border-zinc-700/80 font-semibold"
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
          <span className="text-[10px] text-zinc-600 font-mono shrink-0 ml-1.5">
            {formatBytes(node.size)}
          </span>
        )}
      </div>

      {isDirectory && isOpen && node.children && (
        <div className="pl-3 border-l border-zinc-800/80 ml-2 mt-0.5 space-y-0.5">
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

export const CodeWorkspace: React.FC<CodeWorkspaceProps> = ({
  workspaceId,
}) => {
  const [treeData, setTreeData] = useState<WorkspaceTreeResponse | null>(null);
  const [isLoadingTree, setIsLoadingTree] = useState(false);
  const [treeError, setTreeError] = useState<string | null>(null);

  const [activeFilePath, setActiveFilePath] = useState<string | null>(null);
  const [editorContent, setEditorContent] = useState<string>("");
  const [originalContent, setOriginalContent] = useState<string>("");
  const [isLoadingFile, setIsLoadingFile] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);

  const [isDirty, setIsDirty] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const lastLoadedWsRef = useRef<string | null>(null);

  // Reset editor state when switching workspaces
  useEffect(() => {
    if (lastLoadedWsRef.current !== workspaceId) {
      setActiveFilePath(null);
      setEditorContent("");
      setOriginalContent("");
      setIsDirty(false);
      setFileError(null);
      setSaveError(null);
      setSaveSuccess(false);
      lastLoadedWsRef.current = workspaceId;
    }
  }, [workspaceId]);

  const loadTree = useCallback(async () => {
    if (!workspaceId) {
      setTreeData(null);
      return;
    }
    setIsLoadingTree(true);
    setTreeError(null);
    try {
      const res = await getWorkspaceTree(workspaceId, 4);
      setTreeData(res);
    } catch (err: any) {
      setTreeError(err.message || "Failed to load directory tree.");
    } finally {
      setIsLoadingTree(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    loadTree();
  }, [loadTree]);

  const handleSelectNode = async (node: FileNode) => {
    if (node.type === "directory" || !workspaceId) return;
    if (node.path === activeFilePath) return;

    setActiveFilePath(node.path);
    setIsLoadingFile(true);
    setFileError(null);
    setSaveError(null);
    setSaveSuccess(false);

    try {
      const res = await getWorkspaceFile(workspaceId, node.path);
      setEditorContent(res.content);
      setOriginalContent(res.content);
      setIsDirty(false);
    } catch (err: any) {
      setFileError(err.message || `Failed to read ${node.path}`);
      setEditorContent("");
      setOriginalContent("");
      setIsDirty(false);
    } finally {
      setIsLoadingFile(false);
    }
  };

  const handleSave = useCallback(async () => {
    if (!workspaceId || !activeFilePath || !isDirty || isSaving) return;

    setIsSaving(true);
    setSaveError(null);
    setSaveSuccess(false);

    try {
      await saveWorkspaceFile(workspaceId, activeFilePath, editorContent);
      setOriginalContent(editorContent);
      setIsDirty(false);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2500);
    } catch (err: any) {
      setSaveError(err.message || "Failed to save file.");
    } finally {
      setIsSaving(false);
    }
  }, [workspaceId, activeFilePath, isDirty, isSaving, editorContent]);

  const handleEditorMount = (editor: any, monaco: any) => {
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      handleSave();
    });
  };

  if (!workspaceId) {
    return (
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-8 text-center text-zinc-500 font-mono text-xs flex flex-col items-center justify-center min-h-[460px] space-y-2">
        <FolderTree className="w-8 h-8 text-zinc-700 mb-1" />
        <p className="text-zinc-400 font-medium">No Workspace Selected</p>
        <p className="text-zinc-600 text-[11px]">
          Select or register a workspace above to browse and edit project files.
        </p>
      </div>
    );
  }

  const activeLanguage = activeFilePath
    ? getLanguageFromPath(activeFilePath)
    : "plaintext";

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden shadow-xl flex flex-col min-h-[560px]">
      {/* Workspace Header Toolbar */}
      <div className="bg-zinc-950 px-4 py-2.5 border-b border-zinc-800 flex items-center justify-between text-xs font-mono">
        <div className="flex items-center gap-2 min-w-0">
          <Code2 className="w-4 h-4 text-emerald-400 shrink-0" />
          {activeFilePath ? (
            <span className="text-zinc-200 font-semibold truncate">
              {activeFilePath}
            </span>
          ) : (
            <span className="text-zinc-500 italic">Select a file to edit</span>
          )}

          {isDirty && (
            <span className="flex items-center gap-1 text-[11px] text-amber-400 font-semibold ml-2">
              ● Unsaved changes
            </span>
          )}

          {saveSuccess && (
            <span className="flex items-center gap-1 text-[11px] text-emerald-400 font-semibold ml-2">
              <Check className="w-3.5 h-3.5" /> Saved
            </span>
          )}

          {saveError && (
            <span className="flex items-center gap-1 text-[11px] text-rose-400 font-semibold ml-2">
              <AlertCircle className="w-3.5 h-3.5" /> {saveError}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {activeFilePath && (
            <button
              onClick={handleSave}
              disabled={!isDirty || isSaving}
              className="flex items-center gap-1 px-3 py-1 rounded text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm"
              title="Save File (Ctrl+S / Cmd+S)"
            >
              {isSaving ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Saving...</span>
                </>
              ) : (
                <>
                  <Save className="w-3.5 h-3.5" />
                  <span>Save</span>
                </>
              )}
            </button>
          )}

          <button
            onClick={() => loadTree()}
            className="p-1.5 rounded text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60 transition-colors"
            title="Refresh workspace tree"
          >
            <RotateCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Main Two-Pane Editor Layout */}
      <div className="grid grid-cols-1 md:grid-cols-12 flex-1 min-h-[500px]">
        {/* Left: Filesystem Tree Pane */}
        <div className="md:col-span-4 lg:col-span-3 border-r border-zinc-800/80 p-3 bg-zinc-950/40 flex flex-col space-y-2 overflow-y-auto max-h-[620px]">
          <div className="flex items-center justify-between text-[11px] font-mono text-zinc-500 border-b border-zinc-800/60 pb-1.5 px-1">
            <span className="uppercase tracking-wider font-semibold">
              Workspace Files
            </span>
            {treeData && <span>{treeData.total_entries}</span>}
          </div>

          {isLoadingTree ? (
            <div className="p-8 text-center text-xs text-zinc-500 font-mono flex items-center justify-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin text-cyan-400" />
              <span>Scanning tree...</span>
            </div>
          ) : treeError ? (
            <div className="p-3 bg-zinc-950/80 border border-amber-900/40 rounded text-xs text-amber-400/90 font-mono space-y-1">
              <div className="flex items-center gap-1.5 font-semibold">
                <AlertTriangle className="w-3.5 h-3.5" /> Error loading tree
              </div>
              <p className="text-[11px] text-zinc-400">{treeError}</p>
            </div>
          ) : treeData && treeData.tree.length > 0 ? (
            <div className="space-y-0.5">
              {treeData.tree.map((node) => (
                <TreeNodeItem
                  key={node.path}
                  node={node}
                  selectedPath={activeFilePath}
                  onSelect={handleSelectNode}
                />
              ))}
            </div>
          ) : (
            <div className="p-8 text-center text-xs text-zinc-600 font-mono">
              Workspace directory is empty.
            </div>
          )}
        </div>

        {/* Right: Monaco Editor Pane */}
        <div className="md:col-span-8 lg:col-span-9 bg-zinc-950 flex flex-col min-h-[500px]">
          {isLoadingFile ? (
            <div className="flex-1 flex flex-col items-center justify-center text-xs font-mono text-zinc-500 space-y-2">
              <Loader2 className="w-5 h-5 animate-spin text-indigo-400" />
              <span>Reading {activeFilePath}...</span>
            </div>
          ) : fileError ? (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center space-y-3 font-mono">
              <AlertCircle className="w-8 h-8 text-rose-400" />
              <div className="text-sm font-semibold text-zinc-200">
                Unable to Open File
              </div>
              <p className="text-xs text-rose-300/90 max-w-md bg-rose-950/30 p-3 rounded-lg border border-rose-900/60">
                {fileError}
              </p>
              <p className="text-[11px] text-zinc-500">
                Binary, protected, or oversized files cannot be displayed in the
                editor surface.
              </p>
            </div>
          ) : activeFilePath ? (
            <div className="flex-1 flex flex-col h-full min-h-[500px]">
              <Editor
                height="100%"
                language={activeLanguage}
                theme="vs-dark"
                value={editorContent}
                onChange={(val) => {
                  const updated = val ?? "";
                  setEditorContent(updated);
                  setIsDirty(updated !== originalContent);
                }}
                onMount={handleEditorMount}
                options={{
                  fontSize: 13,
                  fontFamily:
                    "JetBrains Mono, Menlo, Monaco, Consolas, 'Courier New', monospace",
                  lineNumbers: "on",
                  minimap: { enabled: false },
                  scrollBeyondLastLine: false,
                  automaticLayout: true,
                  tabSize: 4,
                  wordWrap: "on",
                  readOnly: isSaving,
                }}
              />
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-zinc-600 text-xs font-mono p-8 text-center space-y-2">
              <Code2 className="w-10 h-10 text-zinc-800" />
              <p className="text-zinc-400 font-medium">Monaco Code Editor</p>
              <p className="text-zinc-600 text-[11px]">
                Click on any text file in the workspace tree to view, edit, and
                save changes.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
