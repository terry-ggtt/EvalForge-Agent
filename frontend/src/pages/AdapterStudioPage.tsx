import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { registryId } from "../api/adapterStudio";
import { useRegistryCommand, useRegistryQuery } from "../hooks/useAdapterStudio";
import type { Profile } from "../types/adapterStudio";
import { JsonView, ReadState, RegistryList, studioButton, studioInput, studioSecondary, StudioPanel } from "../components/adapters/StudioComponents";
import { SampleImport, SampleWorkspace } from "../components/adapters/SampleWorkspace";
import { CandidatePanel, GenerationPanel, VersionPanel } from "../components/adapters/ReviewWorkspace";

/** @returns Adapter Studio connection boundary; token stays in memory and never enters URLs/browser storage. */
export function AdapterStudioPage() {
  const [draft, setDraft] = useState("");
  const [token, setToken] = useState("");
  /** @param event Explicit connection form. @returns Opens isolated credential session; no credential persistence. */
  function connect(event: FormEvent) {
    event.preventDefault();
    if (draft.trim()) { setToken(draft.trim()); setDraft(""); }
  }
  return <div className="space-y-6">
    <div><h2 className="text-2xl font-semibold">Adapter Studio</h2>
      <p className="mt-2 text-sm text-slate-600">Agent 样本 → Schema → AI 规则候选 → 确定性预览与验证 → 人工审核 → 固定版本</p></div>
    {!token ? <StudioPanel title="连接 Adapter Registry">
      <p className="text-sm">输入服务端配置的 Registry Bearer 凭据。仅保存在本页面内存；刷新、离开页面或断开后需重新输入。</p>
      <p className="text-xs text-slate-500">reader 可查看配置/版本，editor 可导入/生成/验证，publisher 可审核发布。权限由服务端判定。
        503 表示 Registry 未启用或未配置；401/403 请检查凭据或角色。</p>
      <form onSubmit={connect} className="flex flex-wrap gap-3">
        <label className="min-w-0 flex-1 text-sm">Registry 凭据<input aria-label="Registry 凭据" type="password"
          autoComplete="off" className={studioInput} value={draft}
          onChange={/** @param event Credential draft. @returns Updates memory only. */ event => setDraft(event.target.value)} /></label>
        <button className={studioButton} disabled={!draft.trim()}>连接 Registry</button>
      </form>
    </StudioPanel> : <>
      <button type="button" className={studioSecondary}
        onClick={/** @returns Discards current token, queries and sensitive UI selections. */ () => setToken("")}>断开并清除本页凭据</button>
      <StudioSession token={token} />
    </>}
  </div>;
}

/** @param props In-memory credential. @returns Private Query cache; unmount aborts reads and discards sensitive snapshots. */
function StudioSession({ token }: { token: string }) {
  const [client] = useState(
    /** @returns Dedicated cache, never shared with public Evaluation/Run pages. */
    () => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } } }));
  useEffect(
    /** @returns Cleanup for session-only queries; running POSTs remain durably discoverable on reconnect. */
    () => () => { void client.cancelQueries(); client.clear(); }, [client]);
  return <QueryClientProvider client={client}><StudioProfiles token={token} /></QueryClientProvider>;
}

/** @param props Authorized session. @returns Profile discovery/creation and keyed profile workspace. */
function StudioProfiles({ token }: { token: string }) {
  const [profileId, setProfileId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const create = useRegistryCommand<Profile>(token, "/profiles",
    /** @param row Persisted profile. @returns Selects profile and clears completed draft. */
    row => { setProfileId(row.profile_id); setName(""); setDescription(""); });
  /** @param event Explicit create form. @returns Creates profile metadata; never stores Agent endpoint secrets. */
  function submit(event: FormEvent) {
    event.preventDefault(); create.mutate({ name: name.trim(), description });
  }
  return <div className="space-y-6">
    <StudioPanel title="1. Adapter Profile">
      <RegistryList token={token} path="/profiles" idKey="profile_id" selected={profileId} onSelect={setProfileId} />
      <details className="space-y-3"><summary className="cursor-pointer text-sm">创建 Adapter Profile</summary>
        <form onSubmit={submit} className="space-y-3">
          <label className="block text-sm">配置名称<input aria-label="配置名称" required maxLength={200} className={studioInput} value={name}
            onChange={/** @param event Profile name. @returns Updates local draft. */ event => setName(event.target.value)} /></label>
          <label className="block text-sm">Agent / 数据格式说明<textarea aria-label="Agent 说明" maxLength={2000} rows={3} className={studioInput} value={description}
            onChange={/** @param event Non-secret description. @returns Updates profile draft. */ event => setDescription(event.target.value)} /></label>
          <p className="text-xs text-slate-500">此处配置映射资料。Agent HTTP 地址和认证继续由原有服务端配置管理，请勿在说明中填入密钥。</p>
          <button className={studioButton} disabled={!name.trim() || create.isPending}>创建 Profile</button>
        </form>
      </details>
      <ReadState pending={create.isPending} error={create.error} />
    </StudioPanel>
    {profileId && <ProfileWorkspace key={profileId} token={token} profileId={profileId} />}
  </div>;
}

/** @param props Profile scope. @returns Independent persisted discovery and selected evidence/review/version panels. */
function ProfileWorkspace({ token, profileId }: { token: string; profileId: string }) {
  const [sampleId, setSampleId] = useState("");
  const [generationId, setGenerationId] = useState("");
  const [candidateId, setCandidateId] = useState("");
  const [version, setVersion] = useState("");
  const base = `/profiles/${registryId(profileId)}`;
  const profile = useRegistryQuery<Profile>(token, base);
  return <div className="space-y-6">
    <ReadState pending={profile.isPending} error={profile.error} />
    {profile.data && <StudioPanel title={profile.data.name}>
      <p className="text-sm">{profile.data.description}</p>
      <p className="break-all text-xs">{profileId}</p>
      <JsonView label="Trace Validation Profile（实际服务端契约）" data={profile.data.trace_profile_json} />
    </StudioPanel>}
    <SampleImport token={token} profileId={profileId} onSample={setSampleId} />
    <StudioPanel title="已保存样本批次"><RegistryList token={token} path={`${base}/samples`} idKey="sample_id" selected={sampleId} onSelect={setSampleId} /></StudioPanel>
    {sampleId && <SampleWorkspace key={sampleId} token={token} profileId={profileId} sampleId={sampleId}
      onGeneration={setGenerationId} onCandidate={setCandidateId} />}
    <StudioPanel title="生成任务历史"><RegistryList token={token} path={`${base}/generations`} idKey="generation_id" selected={generationId} onSelect={setGenerationId} /></StudioPanel>
    {generationId && <GenerationPanel key={generationId} token={token} generationId={generationId} onCandidate={setCandidateId} />}
    <StudioPanel title="候选 Mapping"><RegistryList token={token} path={`${base}/candidates`} idKey="candidate_id" selected={candidateId} onSelect={setCandidateId} /></StudioPanel>
    {candidateId && <CandidatePanel key={candidateId} token={token} profileId={profileId} candidateId={candidateId} />}
    <StudioPanel title="已发布版本历史"><RegistryList token={token} path={`${base}/versions`} idKey="version" selected={version} onSelect={setVersion} /></StudioPanel>
    {version && <VersionPanel key={version} token={token} profileId={profileId} version={version} />}
  </div>;
}
