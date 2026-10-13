import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router";
import { createEvaluationJob, evaluationJobKeys } from "../api/evaluationJobs";
import { JobError } from "../components/jobs/JobComponents";
import { buildEvaluationJobRequest, newCaseDraft } from "../utils/evaluationJobForm";
import type { CaseDraft, JobDraft } from "../utils/evaluationJobForm";
import type { EvaluationJobSnapshot } from "../hooks/useEvaluationJob";

const inputClass = "block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm";
const configFields = [
  ["name", "Job Name", true], ["dataset_version", "Dataset Version", true],
  ["agent_version", "Agent Version", true], ["model_name", "Model Name (optional)", false],
  ["prompt_version", "Prompt Version (optional)", false],
] as const;
const caseFields = [
  ["id", "Case ID", false], ["input_text", "Input", true],
  ["expected_output", "Expected Output (may be empty)", true],
  ["toolCalls", "Expected Tool Calls (JSON array or null)", true],
  ["metadata", "Case Metadata (JSON object)", true],
] as const;

/** @returns Validated async creation form using the actual TestCase contract and existing visual language. */
export function CreateEvaluationJobPage() {
  const navigate = useNavigate();
  const client = useQueryClient();
  const [draft, setDraft] = useState<JobDraft>({
    name: "", dataset_version: "", agent_version: "", model_name: "",
    prompt_version: "", metadata: "{}", cases: [newCaseDraft()],
  });
  const [validationError, setValidationError] = useState<Error | null>(null);
  const mutation = useMutation({
    mutationFn: createEvaluationJob,
    /** @param job Accepted job. @returns Seeds detail cache, invalidates list and navigates to real progress. */
    onSuccess: (job) => {
      client.setQueryData<EvaluationJobSnapshot>(evaluationJobKeys.detail(job.job_id), {
        job, progress: null, progressError: null,
      });
      void client.invalidateQueries({ queryKey: evaluationJobKeys.lists });
      navigate(`/evaluation-jobs/${encodeURIComponent(job.job_id)}`);
    },
  });

  /** @param key Stable case key. @param field Editable field. @param value Raw user text. @returns Updates one draft case. */
  function updateCase(key: string, field: keyof Omit<CaseDraft, "key">, value: string) {
    setDraft(
      /** @param current Latest form state. @returns Draft containing the edited case. */
      (current) => ({ ...current, cases: current.cases.map(
        /** @param item Existing draft. @returns Updated case or preserved sibling. */
        (item) => item.key === key ? { ...item, [field]: value } : item,
      ) }),
    );
  }

  /** @param event Form submission. @returns Prevents navigation, validates and submits once; displays errors inline. */
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mutation.isPending) return;
    setValidationError(null);
    mutation.reset();
    try { mutation.mutate(buildEvaluationJobRequest(draft)); }
    catch (error) { setValidationError(error instanceof Error ? error : new Error("Invalid evaluation configuration.")); }
  }

  return <div className="space-y-6">
    <div><Link to="/evaluation-jobs" className="text-sm text-slate-500 hover:underline">← Evaluation Jobs</Link>
      <h2 className="mt-2 text-2xl font-semibold">Create Evaluation Job</h2>
      <p className="mt-1 text-sm text-slate-500">Queue an evaluation for the configured backend agent. Version fields identify this experiment; they do not select an agent implementation.</p>
    </div>
    <form onSubmit={handleSubmit} className="space-y-6">
      <fieldset disabled={mutation.isPending} className="space-y-6 disabled:opacity-60">
        <section className="rounded-xl border border-slate-200 bg-white p-6">
          <h3 className="font-semibold">Job Configuration</h3>
          <div className="mt-5 grid gap-5 sm:grid-cols-2">
            {configFields.map(
              /** @param tuple Backend field, label and requirement. @returns Labeled configuration input. */
              ([field, label, required]) => <label key={field} className="space-y-2 text-sm font-medium">{label}
                <input required={required} value={draft[field]} onChange={
                  /** @param event Raw input. @returns Updates the named configuration field. */
                  (event) => setDraft({ ...draft, [field]: event.target.value })
                } className={inputClass} />
              </label>,
            )}
            <label className="space-y-2 text-sm font-medium">Job Metadata (JSON object)
              <textarea rows={3} value={draft.metadata} onChange={
                /** @param event JSON metadata text. @returns Updates job metadata draft. */
                (event) => setDraft({ ...draft, metadata: event.target.value })
              } className={inputClass} />
            </label>
          </div>
        </section>
        <section className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="font-semibold">Test Cases</h3>
            <button type="button" onClick={
              /** @returns Appends a blank case with a stable key. */
              () => setDraft({ ...draft, cases: [...draft.cases, newCaseDraft()] })
            } className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm">Add Case</button>
          </div>
          <p className="text-sm text-slate-500">Use unique case IDs. Input and expected output are preserved exactly. Tool calls use tool_name and arguments (a JSON object).</p>
          {draft.cases.map(
            /** @param item Case draft. @param index Visual position. @returns Editable canonical TestCase fields. */
            (item, index) => <div key={item.key} className="rounded-xl border border-slate-200 bg-white p-6">
              <div className="flex items-center justify-between gap-3"><h4 className="font-medium">Case {index + 1}</h4>
                <button type="button" disabled={draft.cases.length === 1} aria-label={`Remove case ${index + 1}`} onClick={
                  /** @returns Removes this draft while retaining at least one case. */
                  () => setDraft({ ...draft, cases: draft.cases.filter(
                    /** @param candidate Existing case. @returns Whether it should remain. */
                    (candidate) => candidate.key !== item.key,
                  ) })
                } className="text-sm text-red-700 disabled:opacity-40">Remove</button>
              </div>
              <div className="mt-5 space-y-4">{caseFields.map(
                /** @param tuple Case field and presentation. @returns Input appropriate for the backend type. */
                ([field, label, multiline]) => <div key={field} className="space-y-2 text-sm font-medium"><label htmlFor={`${item.key}-${field}`} className="block">{label}</label>
                  {multiline ? <textarea id={`${item.key}-${field}`} rows={3} required={field === "input_text"} value={item[field]} onChange={
                    /** @param event Case text or JSON. @returns Updates one case field. */
                    (event) => updateCase(item.key, field, event.target.value)
                  } className={inputClass} />
                    : <input id={`${item.key}-${field}`} required value={item[field]} onChange={
                      /** @param event Case identifier. @returns Updates the ID draft. */
                      (event) => updateCase(item.key, field, event.target.value)
                    } className={inputClass} />}
                </div>,
              )}</div>
            </div>,
          )}
        </section>
      </fieldset>
      {validationError && <JobError error={validationError} />}
      {mutation.isError && <JobError error={mutation.error} />}
      <div className="flex justify-end"><button type="submit" disabled={mutation.isPending} className="rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-medium text-white disabled:opacity-50">{mutation.isPending ? "Creating…" : "Create Job"}</button></div>
    </form>
  </div>;
}
