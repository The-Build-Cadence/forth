import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface Paged<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface ProfileDocument {
  id: number;
  kind: string;
  title: string;
  upload: string;
  raw_text: string;
  status: string;
  status_message: string;
  created_at: string;
  updated_at: string;
}

export interface ProfileFact {
  id: number;
  fact_type: string;
  title: string;
  statement: string;
  normalized_value: string;
  confidence: string;
  source_document_title: string;
  verified_by_user: boolean;
  lifecycle: string;
  evidence_quote: string;
  strength: string;
  user_notes: string;
}

export interface ResumeContact {
  phone: string;
  email: string;
  linkedin_url: string;
  include_phone: boolean;
  include_email: boolean;
  include_linkedin: boolean;
}

export interface CandidateProfile {
  id: number;
  headline: string;
  professional_summary: string;
  target_roles: string[];
  target_industries: string[];
  location: string;
  resume_contact?: Partial<ResumeContact>;
  generation_instructions: string;
  authorized_countries: string[];
  work_modes: string[];
  employment_types: string[];
  minimum_compensation: number | null;
  compensation_currency: string;
  minimum_match_score: number;
  excluded_companies: string[];
  completeness: number;
  onboarding_state: any;
  onboarding_completed_at: string | null;
  updated_at: string;
}

export interface OnboardingSnapshot {
  needs_onboarding: boolean;
  step: { id: string; title: string; prompt: string; question?: OnboardingQuestion | null };
  progress: number;
  readiness: { score: number; ready: boolean; checks: Record<string, boolean>; missing: string[] };
  assessment: { confidence: number; gate: number; ready: boolean; missing: string[]; rationale: string };
  stats: { documents: number; facts: number; skills: number; achievements: number; preferences: number };
  suggested_summary: string;
  profile: CandidateProfile;
  resume: { id: number; name: string; status: string; message: string; analysis: any } | null;
  interview: { turn: number; history: any[]; unresolved_ambiguities: number };
}

export interface OnboardingQuestion {
  id: string;
  target: string;
  kind: 'text' | 'textarea' | 'tags' | 'single_choice' | 'multi_choice' | 'number' | 'confirm';
  title: string;
  prompt: string;
  why: string;
  placeholder: string;
  prefill: string;
  options: string[];
  suggestions: string[];
  suggestion_reason: string;
  required: boolean;
  fact_id: number;
  evidence: string;
}

export interface CandidatePreference {
  id: number;
  category: string;
  label: string;
  value: any;
  importance: string;
  verified_by_user: boolean;
  rationale: string;
}

export interface JobSource {
  id: number;
  kind: string;
  name: string;
  config: any;
  enabled: boolean;
  last_status: string;
  last_message: string;
  job_count: number;
}

export interface SourceRun {
  id: number; source: number; source_name: string; status: string; started_at: string | null; completed_at: string | null;
  discovered_count: number; imported_count: number; updated_count: number; error_count: number; log: any[]; created_at: string;
}

export interface JobMatch {
  id: number;
  job: number;
  score: number;
  normalized_score: number;
  profile_minimum_score: number;
  meets_profile_threshold: boolean;
  confidence: string;
  explanation_json: any;
  missing_requirements: string[];
  supporting_facts: any[];
  hard_filter_status: string;
  signals: MatchSignal[];
}

export interface MatchSignal {
  id: number;
  kind: string;
  label: string;
  score: number;
  weight: number;
  explanation: string;
  evidence: any[];
}

export interface ProfileImprovementSuggestion {
  id: string;
  fact_id: number;
  fact_title: string;
  current_statement: string;
  proposed_statement: string;
  rationale: string;
  target_requirements: string[];
}

export interface ProfileImprovementProposal {
  id: number;
  job: number;
  job_title: string;
  company: string;
  status: string;
  source_score: number;
  suggestions: ProfileImprovementSuggestion[];
  decision: any;
  applied_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobPosting {
  materials_status?: string;
  materials_started_at?: string | null;
  has_materials?: boolean;
  generation_instructions?: string | null;
  id: number;
  title: string;
  company: string;
  location: string;
  remote_policy: string;
  seniority: string;
  compensation: string;
  description_text: string;
  extracted_json: any;
  source_url: string;
  application_url: string;
  status: string;
  freshness_status: string;
  last_seen_at: string | null;
  posted_at: string | null;
  discovered_at: string;
  requirements: any[];
  versions: any[];
  match?: JobMatch;
  application?: { id: number; status: string; updated_at: string } | null;
}

export interface Resume {
  id: number;
  kind: string;
  title: string;
  content_markdown: string;
  content_json: any;
  parent_resume: number | null;
  target_job: number | null;
  target_job_title: string;
  validation: any;
  approved: boolean;
  created_at: string;
  updated_at: string;
}

export interface CoverLetter {
  id: number;
  title: string;
  target_job: number;
  target_job_title: string;
  content_markdown: string;
  content_json: any;
  validation: any;
  approved: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface Artifact {
  id: number;
  kind: string;
  title: string;
  file_url: string;
  mime_type: string;
  metadata: any;
  approved: boolean;
}

export interface ApprovalRequest {
  id: number;
  run: number | null;
  kind: string;
  title: string;
  prompt: string;
  payload: any;
  status: string;
  response: any;
  created_at: string;
}

export interface AgentRun {
  id: number;
  thread: number | null;
  agent: string;
  objective: string;
  status: string;
  output: any;
  error: string;
  steps: any[];
}

export interface ConversationMessage {
  id: number;
  role: string;
  content: string;
  metadata: any;
  created_at: string;
}

export interface ConversationThread {
  id: number;
  title: string;
  status: string;
  messages: ConversationMessage[];
  created_at: string;
  updated_at: string;
}

export interface ApplicationRecord {
  id: number;
  job: number;
  job_detail: JobPosting;
  application_form_url: string;
  status: string;
  resume: number | null;
  resume_title: string;
  artifact_count?: number;
  resume_detail: Resume | null;
  cover_letters: CoverLetter[];
  applied_at: string | null;
  follow_up_at: string | null;
  outcome: string;
  notes: string;
  contact_name: string;
  contact_email: string;
  created_at: string;
  updated_at: string;
  events: any[];
  artifacts: any[];
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  constructor(private http: HttpClient) {}

  dashboard(): Observable<any> {
    return this.http.get(`${environment.apiBaseUrl}/dashboard/`);
  }

  today(): Observable<any> {
    return this.http.get(`${environment.apiBaseUrl}/today/`);
  }

  documents(): Observable<Paged<ProfileDocument>> {
    return this.http.get<Paged<ProfileDocument>>(`${environment.apiBaseUrl}/profile/documents/`);
  }

  candidateProfile(): Observable<CandidateProfile> {
    return this.http.get<CandidateProfile>(`${environment.apiBaseUrl}/profile/`);
  }

  updateCandidateProfile(payload: Partial<CandidateProfile>): Observable<CandidateProfile> {
    return this.http.patch<CandidateProfile>(`${environment.apiBaseUrl}/profile/`, payload);
  }

  onboarding(): Observable<OnboardingSnapshot> {
    return this.http.get<OnboardingSnapshot>(`${environment.apiBaseUrl}/profile/onboarding/`);
  }

  answerOnboarding(step: string, answers: Record<string, any> = {}): Observable<OnboardingSnapshot> {
    return this.http.post<OnboardingSnapshot>(`${environment.apiBaseUrl}/profile/onboarding/`, { step, answers });
  }

  preferences(): Observable<Paged<CandidatePreference>> {
    return this.http.get<Paged<CandidatePreference>>(`${environment.apiBaseUrl}/profile/preferences/`);
  }

  createPreference(payload: Partial<CandidatePreference>): Observable<CandidatePreference> {
    return this.http.post<CandidatePreference>(`${environment.apiBaseUrl}/profile/preferences/`, payload);
  }

  updatePreference(id: number, payload: Partial<CandidatePreference>): Observable<CandidatePreference> {
    return this.http.patch<CandidatePreference>(`${environment.apiBaseUrl}/profile/preferences/${id}/`, payload);
  }

  deletePreference(id: number): Observable<void> {
    return this.http.delete<void>(`${environment.apiBaseUrl}/profile/preferences/${id}/`);
  }

  createDocument(payload: FormData): Observable<ProfileDocument> {
    return this.http.post<ProfileDocument>(`${environment.apiBaseUrl}/profile/documents/`, payload);
  }

  facts(params: Record<string, string> = {}): Observable<Paged<ProfileFact>> {
    return this.http.get<Paged<ProfileFact>>(`${environment.apiBaseUrl}/profile/facts/`, { params: new HttpParams({ fromObject: params }) });
  }

  verifyFact(id: number): Observable<ProfileFact> {
    return this.http.post<ProfileFact>(`${environment.apiBaseUrl}/profile/facts/${id}/verify/`, {});
  }

  updateFact(id: number, payload: Partial<ProfileFact>): Observable<ProfileFact> {
    return this.http.patch<ProfileFact>(`${environment.apiBaseUrl}/profile/facts/${id}/`, payload);
  }

  deleteFact(id: number): Observable<void> {
    return this.http.delete<void>(`${environment.apiBaseUrl}/profile/facts/${id}/`);
  }

  sources(): Observable<Paged<JobSource>> {
    return this.http.get<Paged<JobSource>>(`${environment.apiBaseUrl}/sources/`);
  }

  createSource(payload: Partial<JobSource>): Observable<JobSource> {
    return this.http.post<JobSource>(`${environment.apiBaseUrl}/sources/`, payload);
  }

  updateSource(id: number, payload: Partial<JobSource>): Observable<JobSource> {
    return this.http.patch<JobSource>(`${environment.apiBaseUrl}/sources/${id}/`, payload);
  }

  runSource(id: number): Observable<any> {
    return this.http.post<any>(`${environment.apiBaseUrl}/sources/${id}/run/`, {});
  }

  sourceRuns(): Observable<Paged<SourceRun>> {
    return this.http.get<Paged<SourceRun>>(`${environment.apiBaseUrl}/source-runs/`);
  }

  sourceRun(id: number): Observable<SourceRun> {
    return this.http.get<SourceRun>(`${environment.apiBaseUrl}/source-runs/${id}/`);
  }

  jobs(params: Record<string, string> = {}): Observable<Paged<JobPosting>> {
    return this.http.get<Paged<JobPosting>>(`${environment.apiBaseUrl}/jobs/`, { params: new HttpParams({ fromObject: params }) });
  }

  job(id: number): Observable<JobPosting> {
    return this.http.get<JobPosting>(`${environment.apiBaseUrl}/jobs/${id}/`);
  }

  updateJob(id: number, payload: Partial<JobPosting>): Observable<JobPosting> {
    return this.http.patch<JobPosting>(`${environment.apiBaseUrl}/jobs/${id}/`, payload);
  }

  importJob(payload: { text: string; source_url?: string; source?: number | null }): Observable<JobPosting> {
    return this.http.post<JobPosting>(`${environment.apiBaseUrl}/jobs/import_job/`, payload);
  }

  recomputeJobMatch(id: number): Observable<any> {
    return this.http.post(`${environment.apiBaseUrl}/jobs/${id}/recompute_match/`, {});
  }

  proposeProfileImprovements(jobId: number): Observable<ProfileImprovementProposal> {
    return this.http.post<ProfileImprovementProposal>(`${environment.apiBaseUrl}/jobs/${jobId}/profile_improvements/`, {});
  }

  applyProfileImprovements(jobId: number, proposalId: number, acceptedSuggestionIds: string[]): Observable<any> {
    return this.http.post(`${environment.apiBaseUrl}/jobs/${jobId}/apply_profile_improvements/`, {
      proposal_id: proposalId,
      accepted_suggestion_ids: acceptedSuggestionIds,
    });
  }

  createApplication(jobId: number): Observable<ApplicationRecord> {
    return this.http.post<ApplicationRecord>(`${environment.apiBaseUrl}/jobs/${jobId}/create_application/`, {});
  }

  requestPreparation(jobId: number): Observable<AgentRun> {
    return this.http.post<AgentRun>(`${environment.apiBaseUrl}/jobs/${jobId}/request_preparation/`, {});
  }

  regenerateApplicationMaterials(jobId: number): Observable<any> {
    return this.http.post(`${environment.apiBaseUrl}/jobs/${jobId}/regenerate_materials/`, {});
  }

  resumes(params: Record<string, string> = {}): Observable<Paged<Resume>> {
    return this.http.get<Paged<Resume>>(`${environment.apiBaseUrl}/resumes/`, { params: new HttpParams({ fromObject: params }) });
  }

  createResume(payload: Partial<Resume>): Observable<Resume> {
    return this.http.post<Resume>(`${environment.apiBaseUrl}/resumes/`, payload);
  }

  tailorResume(job: number, canonical_resume?: number | null): Observable<Resume> {
    return this.http.post<Resume>(`${environment.apiBaseUrl}/resumes/tailor/`, { job, canonical_resume });
  }

  approveResume(id: number, acceptRisk = false): Observable<Resume> {
    return this.http.post<Resume>(`${environment.apiBaseUrl}/resumes/${id}/approve/`, { accept_risk: acceptRisk });
  }

  coverLetters(params: Record<string, string> = {}): Observable<Paged<CoverLetter>> {
    return this.http.get<Paged<CoverLetter>>(`${environment.apiBaseUrl}/cover-letters/`, { params: new HttpParams({ fromObject: params }) });
  }

  approveCoverLetter(id: number, acceptRisk = false): Observable<CoverLetter> {
    return this.http.post<CoverLetter>(`${environment.apiBaseUrl}/cover-letters/${id}/approve/`, { accept_risk: acceptRisk });
  }

  exportResumeMarkdown(id: number): Observable<Blob> {
    return this.http.get(`${environment.apiBaseUrl}/resumes/${id}/export_markdown/`, { responseType: 'blob' });
  }

  exportResumePdf(id: number): Observable<Blob> {
    return this.http.post(`${environment.apiBaseUrl}/resumes/${id}/export_pdf/`, {}, { responseType: 'blob' });
  }

  exportCoverLetterMarkdown(id: number): Observable<Blob> {
    return this.http.get(`${environment.apiBaseUrl}/cover-letters/${id}/export_markdown/`, { responseType: 'blob' });
  }

  exportCoverLetterPdf(id: number): Observable<Blob> {
    return this.http.post(`${environment.apiBaseUrl}/cover-letters/${id}/export_pdf/`, {}, { responseType: 'blob' });
  }

  applications(params: Record<string, string> = {}): Observable<Paged<ApplicationRecord>> {
    return this.http.get<Paged<ApplicationRecord>>(`${environment.apiBaseUrl}/applications/`, { params: new HttpParams({ fromObject: params }) });
  }

  application(id: number): Observable<ApplicationRecord> {
    return this.http.get<ApplicationRecord>(`${environment.apiBaseUrl}/applications/${id}/`);
  }

  updateApplication(id: number, payload: Partial<ApplicationRecord>): Observable<ApplicationRecord> {
    return this.http.patch<ApplicationRecord>(`${environment.apiBaseUrl}/applications/${id}/`, payload);
  }

  requestRender(applicationId: number): Observable<ApprovalRequest> {
    return this.http.post<ApprovalRequest>(`${environment.apiBaseUrl}/applications/${applicationId}/request_render/`, {});
  }

  artifacts(params: Record<string, string> = {}): Observable<Paged<Artifact>> {
    return this.http.get<Paged<Artifact>>(`${environment.apiBaseUrl}/artifacts/`, { params: new HttpParams({ fromObject: params }) });
  }

  downloadArtifact(id: number): Observable<Blob> {
    return this.http.get(`${environment.apiBaseUrl}/artifacts/${id}/download/`, { responseType: 'blob' });
  }

  approvals(status = ''): Observable<Paged<ApprovalRequest>> {
    const params = status ? new HttpParams().set('status', status) : undefined;
    return this.http.get<Paged<ApprovalRequest>>(`${environment.apiBaseUrl}/approvals/`, { params });
  }

  decideApproval(id: number, approved: boolean, response: any = {}): Observable<ApprovalRequest> {
    return this.http.post<ApprovalRequest>(`${environment.apiBaseUrl}/approvals/${id}/decide/`, { approved, response });
  }

  conversations(): Observable<Paged<ConversationThread>> {
    return this.http.get<Paged<ConversationThread>>(`${environment.apiBaseUrl}/conversations/`);
  }

  createConversation(): Observable<ConversationThread> {
    return this.http.post<ConversationThread>(`${environment.apiBaseUrl}/conversations/`, { title: 'Forth concierge', status: 'active', context: {} });
  }

  conversation(id: number): Observable<ConversationThread> {
    return this.http.get<ConversationThread>(`${environment.apiBaseUrl}/conversations/${id}/`);
  }

  sendMessage(threadId: number, content: string, context: { job_id?: number } = {}): Observable<AgentRun> {
    return this.http.post<AgentRun>(`${environment.apiBaseUrl}/conversations/${threadId}/send/`, { content, context });
  }
}
