import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { EMPTY, Subject, catchError, finalize, switchMap, takeUntil } from 'rxjs';
import { ApiService, ApplicationRecord, Artifact, JobPosting } from '../services/api.service';
import { applicationStage, applicationStageLabel, applicationStages, localDateTime } from '../services/application-journey';
import { MatchesComponent } from './matches.component';
import { ResumeLabComponent } from './resume-lab.component';

@Component({
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, MatchesComponent, ResumeLabComponent],
  templateUrl: './job-workspace.component.html',
  styleUrl: './job-workspace.component.css',
})
export class JobWorkspaceComponent implements OnInit, OnDestroy {
  @ViewChild(ResumeLabComponent) documents?: ResumeLabComponent;
  job?: JobPosting;
  application?: ApplicationRecord;
  tab = 'overview';
  readonly tabs = [{key: 'overview', label: 'Job & fit'}, {key: 'documents', label: 'Documents'}, {key: 'form', label: 'Employer form'}, {key: 'tracking', label: 'Tracking'}];
  readonly stages = applicationStages;
  stageLabel = applicationStageLabel;
  stageDraft = 'saved';
  followUpDraft = '';
  appliedDraft = '';
  instructions = '';
  overrideInstructions = false;
  instructionsDirty = false;
  dirty = false;
  saving = false;
  loading = true;
  error = '';
  message = '';
  newQuestion = '';
  submissionOpen = false;
  employerOpened = false;
  private destroyed$ = new Subject<void>();
  private poll?: ReturnType<typeof setTimeout>;

  constructor(private api: ApiService, private route: ActivatedRoute, private router: Router) {}

  ngOnInit(): void {
    this.route.queryParamMap.pipe(takeUntil(this.destroyed$)).subscribe(params => {
      const tab = params.get('tab');
      this.tab = this.tabs.some(item => item.key === tab) ? tab! : 'overview';
    });
    this.route.paramMap.pipe(switchMap(params => {
      clearTimeout(this.poll);
      this.job = undefined; this.application = undefined; this.loading = true; this.error = '';
      this.message = ''; this.dirty = false; this.instructionsDirty = false; this.employerOpened = false;
      this.submissionOpen = false;
      return this.api.job(Number(params.get('id'))).pipe(catchError(() => {
        this.error = 'This job could not be loaded. It may have been removed or you may not have access.';
        this.loading = false;
        return EMPTY;
      }));
    }), takeUntil(this.destroyed$)).subscribe(job => {
      this.job = job;
      this.overrideInstructions = job.generation_instructions != null;
      this.instructions = job.generation_instructions || '';
      this.loadApplication();
      this.schedulePoll();
    });
  }

  ngOnDestroy(): void { clearTimeout(this.poll); this.destroyed$.next(); this.destroyed$.complete(); }
  canLeave(): boolean { return !(this.dirty || this.instructionsDirty || this.documents?.designDirty) || window.confirm('Leave without saving your changes?'); }
  get busy(): boolean { return this.saving || this.loading || this.job?.document_status === 'generating'; }
  get primaryDisabled(): boolean {
    if (this.saving || this.loading) return true;
    if (this.submitted || this.stage === 'archived') return false;
    return this.job?.document_status === 'generating' || this.instructionsDirty;
  }
  get stage(): string { return applicationStage(this.application?.status || 'saved'); }
  get submitted(): boolean { return !!this.application?.applied_at || ['applied', 'recruiter_screen', 'offer'].includes(this.stage); }
  get employerUrl(): string {
    const url = this.application?.application_form_url || this.job?.application_url || this.job?.source_url || '';
    return /^https?:\/\//i.test(url) ? url : '';
  }
  get documentLabel(): string {
    return ({not_created: 'Not created', generating: 'Generating', needs_review: 'Needs review', reviewed: 'Reviewed', failed: 'Generation failed'})[this.job?.document_status || 'not_created'];
  }
  get nextAction(): string {
    if (!this.application) return 'Save job';
    if (this.stage === 'archived' || this.submitted) return 'Update progress';
    if (this.job?.document_status === 'generating') return 'Preparing documents…';
    if (this.job?.document_status === 'failed') return 'Retry document preparation';
    if (!this.job?.document_status || this.job.document_status === 'not_created') return 'Prepare documents';
    if (this.job?.document_status !== 'reviewed') return 'Review documents';
    return this.employerOpened ? 'Mark as applied' : this.employerUrl ? 'Apply on employer site ↗' : 'Add employer form link';
  }
  get followUpDue(): boolean { return !!this.application?.follow_up_at && Date.parse(this.application.follow_up_at) <= Date.now() && this.stage !== 'archived'; }

  changeTab(tab: string): void {
    if (this.documents?.designDirty && !window.confirm('Leave this document without saving the design?')) return;
    void this.router.navigate([], {relativeTo: this.route, queryParams: {tab}, queryParamsHandling: 'merge'});
  }

  act(): void {
    if (this.primaryDisabled) return;
    if (!this.application) { this.saveJob(); return; }
    if (this.stage === 'archived' || this.submitted) { this.changeTab('tracking'); return; }
    if (['not_created', 'failed'].includes(this.job?.document_status || 'not_created')) { this.prepare(); return; }
    if (this.job?.document_status !== 'reviewed') { this.changeTab('documents'); return; }
    if (this.employerOpened) { this.openSubmission(); return; }
    this.changeTab('form');
  }

  saveJob(): void {
    if (!this.job || this.busy) return;
    this.saving = true;
    this.api.createApplication(this.job.id).pipe(finalize(() => this.saving = false), takeUntil(this.destroyed$)).subscribe({
      next: application => { this.acceptApplication(application); this.message = 'Job saved. You can prepare documents whenever you are ready.'; },
      error: () => this.message = 'Could not save this job. Please try again.',
    });
  }

  prepare(): void {
    if (!this.job || this.busy || this.instructionsDirty) return;
    if (this.documents?.designDirty) { this.message = 'Save your document design before generating new versions.'; return; }
    this.saving = true;
    this.api.regenerateApplicationMaterials(this.job.id).pipe(finalize(() => this.saving = false), takeUntil(this.destroyed$)).subscribe({
      next: () => { this.message = 'Preparing your resume and cover letter. You can leave this page and return later.'; this.refresh(); this.changeTab('documents'); },
      error: error => this.message = error?.error?.detail || 'Preparation could not start. Please try again.',
    });
  }

  refresh(): void {
    if (!this.job) return;
    const id = this.job.id;
    this.api.job(id).pipe(takeUntil(this.destroyed$)).subscribe({next: job => {
      if (this.job?.id !== id) return;
      const finished = this.job.document_status === 'generating' && job.document_status !== 'generating';
      this.job = job;
      if (finished) {
        if (!this.documents?.designDirty) this.documents?.loadMaterials(job.document_status !== 'failed');
        this.message = job.document_status === 'failed' ? 'Generation failed. Previous documents are still available; you can retry.'
          : this.documents?.designDirty ? 'New drafts are ready. Save your current design, then refresh the document list to review the new versions.'
          : 'Your drafts are ready. Review both documents before using them.';
      }
      if (!this.dirty) this.loadApplication();
      this.schedulePoll();
    }, error: () => { this.message = 'Could not refresh progress. Retrying shortly.'; this.schedulePoll(); }});
  }

  private schedulePoll(): void {
    clearTimeout(this.poll);
    if (this.job?.document_status === 'generating') this.poll = setTimeout(() => this.refresh(), 4000);
  }

  private loadApplication(): void {
    const id = this.job?.application?.id;
    if (!id) { this.loading = false; return; }
    this.api.application(id).pipe(takeUntil(this.destroyed$)).subscribe({
      next: application => { if (application.job === this.job?.id && !this.dirty) this.acceptApplication(application); this.loading = false; },
      error: () => { this.loading = false; this.error = 'Could not load your saved application. Reload this page to try again.'; },
    });
  }

  private acceptApplication(application: ApplicationRecord): void {
    this.application = application;
    this.stageDraft = applicationStage(application.status);
    this.followUpDraft = localDateTime(application.follow_up_at);
    if (this.job) this.job.application = {id: application.id, status: application.status, updated_at: application.updated_at};
  }

  openSubmission(): void { this.appliedDraft = localDateTime(new Date().toISOString()); this.submissionOpen = true; }

  recordSubmission(): void {
    if (!this.job || this.saving || !this.appliedDraft) return;
    const applied = new Date(this.appliedDraft);
    if (!Number.isFinite(applied.getTime()) || applied.getTime() > Date.now()) { this.message = 'Choose a valid submission date that is not in the future.'; return; }
    if (this.dirty) { this.message = 'Save your tracking or answer changes before recording submission.'; return; }
    this.saving = true;
    this.api.createApplication(this.job.id).pipe(
      switchMap(application => this.api.updateApplication(application.id, {status: 'applied', applied_at: applied.toISOString()})),
      finalize(() => this.saving = false), takeUntil(this.destroyed$),
    ).subscribe({next: application => { this.acceptApplication(application); this.submissionOpen = false; this.message = 'Submission recorded. Set a follow-up reminder in Tracking.'; this.changeTab('tracking'); }, error: () => this.message = 'Could not record submission. Please try again.'});
  }

  saveTracking(): void {
    if (!this.application || this.saving) return;
    const status = this.stageDraft === this.stage ? this.application.status : this.stageDraft;
    if (status === 'applied' && !this.application.applied_at) { this.message = 'Use “Mark as applied” to record when you submitted.'; this.openSubmission(); return; }
    const followUp = this.followUpDraft ? new Date(this.followUpDraft) : null;
    if (followUp && !Number.isFinite(followUp.getTime())) { this.message = 'Enter a valid follow-up date.'; return; }
    this.saving = true;
    this.api.updateApplication(this.application.id, {
      ...(this.stageDraft !== this.stage ? {status} : {}), notes: this.application.notes, outcome: this.application.outcome,
      contact_name: this.application.contact_name, contact_email: this.application.contact_email,
      application_form_url: this.application.application_form_url,
      form_fields: this.application.form_fields || [], follow_up_at: followUp?.toISOString() || null,
    }).pipe(finalize(() => this.saving = false), takeUntil(this.destroyed$)).subscribe({
      next: application => { this.dirty = false; this.acceptApplication(application); this.message = 'Changes saved.'; },
      error: error => this.message = error?.error?.detail || 'Could not save changes. Check the form link, contact email and answer lengths.',
    });
  }

  saveInstructions(): void {
    if (!this.job || this.saving) return;
    this.saving = true;
    this.api.updateJob(this.job.id, {generation_instructions: this.overrideInstructions ? this.instructions : null}).pipe(finalize(() => this.saving = false), takeUntil(this.destroyed$)).subscribe({
      next: job => { this.job = job; this.instructionsDirty = false; this.message = 'Writing preferences saved for the next generation.'; },
      error: () => this.message = 'Could not save writing preferences.',
    });
  }

  addQuestion(): void {
    if (!this.application || !this.newQuestion.trim()) return;
    this.application.form_fields = [...(this.application.form_fields || []), {id: crypto.randomUUID(), label: this.newQuestion.trim(), type: 'textarea', required: false, options: [], max_length: null, answer: ''}];
    this.newQuestion = ''; this.dirty = true;
  }

  draftAnswers(): void {
    if (!this.application || this.saving) return;
    if (this.dirty) { this.message = 'Save your changes before drafting answers.'; return; }
    this.saving = true;
    this.api.prepareAnswers(this.application.id).pipe(finalize(() => this.saving = false), takeUntil(this.destroyed$)).subscribe({
      next: application => { this.acceptApplication(application); this.message = application.form_fields?.length ? 'Draft answers are ready for review. Copy them to the employer’s form when ready.' : 'No public form questions found. You can add questions manually.'; },
      error: () => this.message = 'Could not draft answers. Your existing answers are safe.',
    });
  }

  downloadArtifact(artifact: Artifact): void {
    this.api.downloadArtifact(artifact.id).pipe(takeUntil(this.destroyed$)).subscribe({next: blob => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${artifact.title.replace(/[^a-z0-9]+/gi, '-')}.${artifact.mime_type === 'application/pdf' ? 'pdf' : 'html'}`;
      link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    }, error: () => this.message = 'Could not download this file. Please try again.'});
  }
}
