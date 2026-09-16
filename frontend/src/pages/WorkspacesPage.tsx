import React from "react";
import { FolderTree } from "lucide-react";

export const WorkspacesPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-zinc-100">
          Workspaces & Repository Tree
        </h1>
        <p className="text-xs text-zinc-400 mt-1">
          Explore registered workspace directories, file trees, and
          security-validated paths.
        </p>
      </div>

      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 space-y-4">
        <div className="flex items-center gap-2 text-zinc-300 text-sm font-semibold">
          <FolderTree className="w-4 h-4 text-blue-400" />
          <span>Workspace Browser Foundation</span>
        </div>
        <p className="text-xs text-zinc-400 leading-relaxed max-w-2xl">
          Connects with{" "}
          <code className="text-zinc-200">
            GET /api/v1/workspaces/&#123;id&#125;/tree
          </code>{" "}
          and <code className="text-zinc-200">POST /api/v1/workspaces</code>.
        </p>
      </div>
    </div>
  );
};
