import React from "react";
import { TaskForm } from "../components/TaskForm";
import { Timeline } from "../components/Timeline";
import { ApprovalGate } from "../components/ApprovalGate";
import { TestResults } from "../components/TestResults";
import { ReviewOutcome } from "../components/ReviewOutcome";
import { FinalResult } from "../components/FinalResult";
import { useTaskExecution } from "../context/TaskContext";

export const HomePage: React.FC = () => {
  const {
    taskId,
    status,
    events,
    pendingPatch,
    coderSummary,
    testResult,
    reviewResult,
    finalResult,
    error,
    isLoading,
    isSubmittingApproval,
    handleStartTask,
    handleApprove,
    handleReject,
  } = useTaskExecution();

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
      <div className="lg:col-span-7 space-y-6">
        {!taskId ? (
          <TaskForm onSubmit={handleStartTask} isLoading={isLoading} />
        ) : (
          <>
            {status === "awaiting_approval" && (
              <ApprovalGate
                coderSummary={coderSummary}
                pendingPatch={pendingPatch}
                onApprove={handleApprove}
                onReject={handleReject}
                isSubmitting={isSubmittingApproval}
              />
            )}

            <TestResults testResult={testResult} />
            <ReviewOutcome review={reviewResult} />
            <FinalResult result={finalResult} error={error} />
          </>
        )}

        {error && status !== "completed" && !finalResult && (
          <div className="bg-rose-950/40 border border-rose-800 text-rose-300 p-4 rounded-xl text-xs">
            <span className="font-semibold">Error: </span>
            {error}
          </div>
        )}
      </div>

      <div className="lg:col-span-5">
        <div className="sticky top-24">
          <Timeline events={events} />
        </div>
      </div>
    </div>
  );
};
