import { useState } from "react";
import type { ReactNode } from "react";
import { JobError } from "../jobs/JobComponents";
import { useRegistryQuery } from "../../hooks/useAdapterStudio";
import type { ListRow, MappingSpec, ValidationRecord } from "../../types/adapterStudio";
import { mappingRows } from "../../utils/adapterStudio";

export const studioInput = "w-full rounded-lg border border-slate-300 bg-white p-2 text-sm";
export const studioButton = "rounded-lg bg-slate-900 px-3 py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-40";
export const studioSecondary = "rounded-lg border border-slate-300 px-3 py-2 text-sm disabled:opacity-40";

/** @param props Titled content. @returns Existing slate/white card style with semantic heading. */
export function StudioPanel({ title, children }: { title: string; children: ReactNode }) {
  return <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
    <h3 className="font-semibold">{title}</h3>{children}
  </section>;
}

/** @param props Sensitive local/server JSON and disclosure label. @returns Escaped, collapsed JSON, never HTML. */
export function JsonView({ label, data }: { label: string; data: unknown }) {
  return <details className="min-w-0 rounded-lg border border-slate-200 p-3">
    <summary className="cursor-pointer text-sm font-medium">{label}</summary>
    <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(data, null, 2)}</pre>
  </details>;
}

/** @param props Snapshot loading/failure. @returns Existing shared error or accessible loading status. */
export function ReadState({ pending, error }: { pending: boolean; error: unknown }) {
  return <>{pending && <p role="status">正在加载…</p>}{error != null && <JobError error={error} />}</>;
}

/** @param props Authorized route, row ID field and explicit selection handler.
 * @returns Paginated metadata discovery; never bulk-loads raw samples or reports.
 */
export function RegistryList({ token, path, idKey, selected, onSelect }: {
  token: string; path: string; idKey: keyof ListRow; selected?: string; onSelect: (id: string) => void;
}) {
  const [offset, setOffset] = useState(0);
  const query = useRegistryQuery<ListRow[]>(token, `${path}?limit=10&offset=${offset}`);
  return <div className="space-y-2">
    <ReadState pending={query.isPending} error={query.error} />
    <div className="flex flex-wrap gap-2">
      {query.data?.map(
        /** @param row Metadata entry. @returns Explicit selection button with status. */
        row => { const id = String(row[idKey]); return <button type="button" key={id}
          aria-pressed={selected === id} className={selected === id ? studioButton : studioSecondary}
          onClick={/** @returns Selects only this entry. */ () => onSelect(id)}>
          {row.name ?? (idKey === "version" ? `v${id}` : id)}
          {row.status ? ` · ${row.status}` : ""}{row.eligible !== undefined ? ` · ${row.eligible ? "可审核" : "阻断"}` : ""}
        </button>; })}
    </div>
    {query.data?.length === 0 && <p className="text-sm text-slate-500">本页暂无记录。</p>}
    <div className="flex items-center gap-3">
      <button type="button" className={studioSecondary} disabled={offset === 0}
        onClick={/** @returns Moves back one server page. */ () => setOffset(Math.max(0, offset - 10))}>上一页</button>
      <span className="text-xs">第 {offset / 10 + 1} 页</span>
      <button type="button" className={studioSecondary} disabled={query.data?.length !== 10}
        onClick={/** @returns Moves forward one server page. */ () => setOffset(offset + 10)}>下一页</button>
      <button type="button" className={studioSecondary} disabled={query.isFetching}
        onClick={/** @returns Refreshes persisted metadata. */ () => { void query.refetch(); }}>刷新</button>
    </div>
  </div>;
}

/** @param props Persisted DSL. @returns Source/operation/target/missing-value relationships, no inferred evidence. */
export function MappingTable({ mapping }: { mapping: MappingSpec }) {
  return <div className="overflow-x-auto"><table className="w-full text-left text-xs">
    <caption className="pb-2 text-left">Source Field → Target Field（事件字段相对事件根）</caption>
    <thead><tr>{["作用域", "Source / 操作", "Target", "类型 / 缺失 / null"].map(
      /** @param text Column title. @returns Header. */ text => <th className="p-2" key={text}>{text}</th>)}</tr></thead>
    <tbody>{mappingRows(mapping).map(
      /** @param row Declaration. @param index Stable spec order. @returns One exact mapping row. */
      (row, index) => <tr className="border-t border-slate-100" key={index}>
        <td className="p-2">{row.scope}</td>
        <td className="break-all p-2">{row.operation.path ?? row.operation.paths?.join(" + ")}<br />{row.operation.op}</td>
        <td className="break-all p-2">{row.target}</td>
        <td className="p-2">{row.value_type} / {row.on_missing} / {row.on_null}</td>
      </tr>)}</tbody>
  </table>{mapping.trace && <p className="mt-3 text-xs">事件列表：{mapping.trace.events_path}；分类路径：{mapping.trace.type_path}</p>}</div>;
}

/** @param props Server validation snapshot. @returns All three layers, semantic unknowns and publication blockers. */
export function ValidationView({ record }: { record: ValidationRecord }) {
  return <div className="space-y-3">
    <p className={record.eligible ? "text-green-700" : "text-amber-800"} role="status">
      {record.eligible ? "验证允许进入人工审核；尚未发布。" : "发布被阻断：请处理下列错误或待确认语义。"}
    </p>
    <p className="break-all text-xs">验证 ID：{record.validation_id}<br />证据摘要：{record.evidence_digest}</p>
    {record.reports_json.map(
      /** @param report Server report. @param index Sample order. @returns Per-sample factual validation. */
      (report, index) => <div key={index} className="space-y-2 rounded-lg border border-slate-200 p-3 text-sm">
        <p>样本 {index + 1}：L1 {report.l1} · L2 {report.l2} · L3 {report.l3}</p>
        {(["errors", "warnings", "unverified"] as const).map(
          /** @param kind Severity. @returns Explicit issues; unverified requires independent evidence. */
          kind => <div key={kind}><strong>{kind === "unverified" ? "待人工确认（Unverified）" : kind}</strong>
            <ul className="ml-5 list-disc">{report[kind].map(
              /** @param issue Safe server finding. @param i Report order. @returns Escaped finding text. */
              (issue, i) => <li key={i}>{issue.code}：{issue.message}{issue.path ? ` · ${issue.path}` : ""}</li>)}</ul></div>)}
        <JsonView label="发布阻断规则与已验证字段" data={{ blockers: report.release_blockers, golden_fields_verified: report.golden_fields_verified }} />
      </div>)}
  </div>;
}
