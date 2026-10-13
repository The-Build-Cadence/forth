import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';
import { ApiService, JobPosting, ProfileImprovementProposal } from '../services/api.service';
import { RealtimeService } from '../services/realtime.service';
import { MatchRadarComponent } from '../components/match-radar.component';

@Component({
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, MatchRadarComponent],
  template: `
    <section class="page">
      <div class="page-head">
        <div>
          <p class="eyebrow">Opportunity inbox</p>
          <h1>Decide where your effort belongs.</h1>
          <p class="page-intro">Every role is filtered for eligibility, decomposed into fit signals, and backed by your profile evidence.</p>
        </div>
        <button class="btn-primary" type="button" (click)="activeTab = 'import'">＋ Import a job</button>
      </div>

      <div class="tabs" role="tablist" aria-label="Match sections">
        <button type="button" role="tab" [class.active]="activeTab === 'matches'" [attr.aria-selected]="activeTab === 'matches'" (click)="activeTab = 'matches'">Your matches <span>{{ jobs.length }}</span></button>
        <button type="button" role="tab" [class.active]="activeTab === 'import'" [attr.aria-selected]="activeTab === 'import'" (click)="activeTab = 'import'">Import job</button>
      </div>
      <p class="feedback-banner" *ngIf="message">{{ message }}</p>

      <section class="panel import-panel" *ngIf="activeTab === 'import'">
        <div class="panel-head"><div><h2>Add a job description</h2><p>Paste the complete posting. We’ll structure it and score it against your profile.</p></div></div>
        <label>Job URL <span class="optional">Optional</span><input name="sourceUrl" [(ngModel)]="sourceUrl" placeholder="https://company.example/jobs/123"></label>
        <label>Job description<textarea name="jobText" rows="13" [(ngModel)]="jobText" placeholder="Paste the full job description here…"></textarea></label>
        <div class="action-row form-actions">
          <button class="btn-primary" type="button" (click)="importJob()" [disabled]="!jobText.trim() || importing"><span class="spinner" *ngIf="importing" aria-hidden="true"></span>{{ importing ? 'Extracting and ranking…' : 'Extract and rank' }}</button>
          <button class="btn-secondary" type="button" (click)="activeTab = 'matches'" [disabled]="importing">Cancel</button>
        </div>
      </section>

      <div class="workspace-grid" *ngIf="activeTab === 'matches'">
        <section class="panel matches-list-panel">
          <div class="panel-head">
            <div><h2>Recent opportunities</h2><p>{{ totalJobs }} roles · newest discoveries first</p></div>
            <div class="filter-row">
              <div class="search-field"><span>⌕</span><input class="compact-input" aria-label="Search jobs" placeholder="Search" [(ngModel)]="search" (keyup.enter)="load()"></div>
              <select class="compact-input" [(ngModel)]="minScore" (change)="load()">
                <option value="">Any score</option>
                <option value="50">50+</option>
                <option value="70">70+</option>
                <option value="85">85+</option>
              </select>
            </div>
          </div>
          <button
            class="job-row"
            type="button"
            *ngFor="let job of jobs"
            [class.selected]="selected?.id === job.id"
            (click)="select(job)">
            <span>
              <strong>{{ job.title }}</strong>
              <small>{{ job.company || 'Unknown company' }} · {{ job.location || job.remote_policy }}</small>
              <span class="job-meta-line"><i [class.pass]="job.match?.hard_filter_status === 'pass'"></i>{{ job.match?.hard_filter_status || 'uncertain' }} eligibility · {{ job.freshness_status || 'fresh' }}</span>
              <span class="job-meta-line">Imported {{ job.discovered_at | date:'medium' }}</span>
              <span class="job-application-state" [class.linked]="job.application">{{ job.application ? 'In pipeline · ' + applicationStatus(job.application.status) : 'Not in pipeline yet' }}</span>
            </span>
            <span class="fit-score" [class.high]="job.match?.meets_profile_threshold"><b>{{ job.match?.normalized_score || 0 }}</b><small>calibrated · {{ job.match?.score || 0 }} raw</small></span>
          </button>
          <div class="empty-state small" *ngIf="!jobs.length"><span class="empty-icon">◇</span><h3>No matching jobs yet</h3><p>Import a job description to get your first fit score.</p><button class="btn-primary" type="button" (click)="activeTab = 'import'">Import a job</button></div>
          <nav class="pagination compact-pagination" *ngIf="pageCount > 1" aria-label="Opportunity pages"><button class="btn-secondary" type="button" (click)="goToPage(currentPage - 1)" [disabled]="currentPage === 1">← Newer</button><span>{{ currentPage }} / {{ pageCount }}</span><button class="btn-secondary" type="button" (click)="goToPage(currentPage + 1)" [disabled]="currentPage === pageCount">Older →</button></nav>
        </section>

        <section class="panel detail-panel" *ngIf="selected; else emptyState">
          <div class="panel-head">
            <div>
              <h2>{{ selected.title }}</h2>
              <p>{{ selected.company || 'Unknown company' }} · {{ selected.location || 'Location unknown' }}</p>
            </div>
            <span class="fit-badge" [class.good]="selected.match?.meets_profile_threshold">{{ selected.match?.normalized_score || 0 }}<small>calibrated · {{ selected.match?.score || 0 }} raw</small></span>
          </div>

          <div class="card-line">
            <span class="status-chip">{{ selected.remote_policy }}</span>
            <span class="status-chip">{{ selected.match?.confidence || 'unscored' }}</span>
            <span class="status-chip">{{ selected.seniority || 'seniority unknown' }}</span>
            <span class="status-chip" [class.good]="selected.match?.hard_filter_status === 'pass'">{{ selected.match?.hard_filter_status || 'uncertain' }} eligibility</span>
            <span class="status-chip" [class.good]="selected.match?.meets_profile_threshold">{{ selected.match?.meets_profile_threshold ? 'ready to prepare' : 'below your threshold' }} · raw target {{ selected.match?.profile_minimum_score || 50 }}</span>
            <span class="status-chip" [class.good]="!!selected.application">{{ selected.application ? 'Pipeline · ' + applicationStatus(selected.application.status) : 'Not in pipeline yet' }}</span>
          </div>

          <div class="insight-callout"><span>✦</span><div><strong>Match summary</strong><p>{{ selected.match?.explanation_json?.summary || 'No match summary yet.' }}</p></div></div>

          <h3>Why this score</h3>
          <app-match-radar [signals]="selected.match?.signals" [jobTitle]="selected.title" />

          <div class="two-col detail-columns">
            <div><h3>Covered skills</h3><div class="chip-row"><span class="status-chip good" *ngFor="let skill of selected.match?.explanation_json?.covered_skills || []">{{ skill }}</span><span class="muted" *ngIf="!(selected.match?.explanation_json?.covered_skills || []).length">No covered skills identified.</span></div></div>
            <div><h3>Visible gaps</h3><div class="chip-row"><span class="status-chip warn" *ngFor="let gap of selected.match?.missing_requirements || []">{{ gap }}</span><span class="muted" *ngIf="!(selected.match?.missing_requirements || []).length">No obvious skill gaps.</span></div></div>
          </div>

          <div class="inferred-capabilities" *ngIf="(selected.match?.explanation_json?.inferred_capabilities || []).length">
            <h3>Implicit coverage</h3>
            <p>These capabilities receive partial credit from verified framework evidence. Strengthening can make them clearer, but never adds a claim that is not supported.</p>
            <div class="chip-row"><span class="status-chip" *ngFor="let item of selected.match?.explanation_json?.inferred_capabilities || []">{{ item.capability }} · {{ item.credit }}</span></div>
          </div>

          <h3>Evidence</h3>
          <div class="list-row" *ngFor="let fact of selected.match?.supporting_facts || []">
            <div>
              <strong>{{ fact.title }}</strong>
              <p>{{ fact.statement }}</p>
            </div>
          </div>

          <div class="profile-strengthener">
            <div><strong>Close safe wording gaps in required capabilities</strong><p>Forth prioritizes verified evidence for this role’s requirements and can clarify implicit framework knowledge without inventing experience. Nothing changes until you review it.</p></div>
            <button class="btn-secondary" type="button" (click)="proposeImprovements(selected)" [disabled]="proposingJobId === selected.id || applyingImprovements">
              <span class="spinner" *ngIf="proposingJobId === selected.id || applyingImprovements" aria-hidden="true"></span>{{ proposingJobId === selected.id ? 'Reviewing evidence…' : applyingImprovements ? 'Rescoring opportunities…' : '✦ Strengthen profile' }}
            </button>
          </div>

          <div class="action-row">
            <button class="btn-primary" type="button" (click)="prepare(selected)" [disabled]="preparingJobId === selected.id"><span class="spinner" *ngIf="preparingJobId === selected.id" aria-hidden="true"></span>{{ preparingJobId === selected.id ? 'Starting specialist…' : 'Approve to prepare →' }}</button>
            <button class="btn-secondary" type="button" (click)="regenerateMaterials(selected)" [disabled]="regeneratingJobId === selected.id"><span class="spinner" *ngIf="regeneratingJobId === selected.id" aria-hidden="true"></span>{{ regeneratingJobId === selected.id ? 'Regenerating…' : '↻ Regenerate materials' }}</button>
            <a class="btn-secondary" *ngIf="selected.application" [routerLink]="['/pipeline']" [queryParams]="{ application: selected.application.id }">Open application · {{ applicationStatus(selected.application.status) }} →</a>
            <button class="btn-secondary" *ngIf="!selected.application" type="button" (click)="createApplication(selected)" [disabled]="savingJobId === selected.id"><span class="spinner" *ngIf="savingJobId === selected.id" aria-hidden="true"></span>{{ savingJobId === selected.id ? 'Saving…' : 'Save to pipeline' }}</button>
            <button class="btn-secondary" type="button" (click)="recompute(selected)" [disabled]="recomputingJobId === selected.id"><span class="spinner" *ngIf="recomputingJobId === selected.id" aria-hidden="true"></span>{{ recomputingJobId === selected.id ? 'Recomputing…' : 'Recompute' }}</button>
          </div>
        </section>

        <ng-template #emptyState>
          <section class="panel detail-panel empty-state">
            <span class="empty-icon">◇</span><h2>Select an opportunity</h2>
            <p>Choose a role from the list to inspect its score, evidence, and gaps.</p>
          </section>
        </ng-template>
      </div>

      <div class="modal-backdrop" *ngIf="improvementProposal" (click)="closeImprovementModal()">
        <section class="improvement-modal" role="dialog" aria-modal="true" aria-labelledby="improvement-title" (click)="$event.stopPropagation()">
          <div class="modal-head">
            <div><p class="eyebrow">Profile strengthening agent</p><h2 id="improvement-title">Review suggested changes</h2><p>These edits reword verified evidence for {{ improvementProposal.job_title }}. They do not add new experience.</p></div>
            <button class="icon-button" type="button" aria-label="Close" (click)="closeImprovementModal()">×</button>
          </div>

          <div class="improvement-empty" *ngIf="!improvementProposal.suggestions.length">
            <span>✓</span><h3>No safe wording changes found</h3><p>Your verified profile evidence is already expressed clearly for this opportunity.</p>
          </div>

          <div class="improvement-list" *ngIf="improvementProposal.suggestions.length">
            <article *ngFor="let suggestion of improvementProposal.suggestions" [class.rejected]="!acceptedSuggestionIds.has(suggestion.id)">
              <label class="suggestion-choice">
                <input type="checkbox" [checked]="acceptedSuggestionIds.has(suggestion.id)" (change)="toggleSuggestion(suggestion.id)">
                <span>{{ acceptedSuggestionIds.has(suggestion.id) ? 'Accept this change' : 'Reject this change' }}</span>
              </label>
              <h3>{{ suggestion.fact_title }}</h3>
              <div class="wording-comparison">
                <div><small>CURRENT</small><p>{{ suggestion.current_statement }}</p></div>
                <div class="proposed"><small>PROPOSED</small><p>{{ suggestion.proposed_statement }}</p></div>
              </div>
              <p class="suggestion-rationale">{{ suggestion.rationale }}</p>
              <div class="chip-row"><span class="status-chip" *ngFor="let requirement of suggestion.target_requirements">{{ requirement }}</span></div>
            </article>
          </div>

          <div class="modal-actions">
            <button class="btn-secondary" type="button" (click)="rejectProposal()" [disabled]="applyingImprovements">Reject all</button>
            <button class="btn-primary" type="button" (click)="applyImprovements()" [disabled]="applyingImprovements || !acceptedSuggestionIds.size">
              <span class="spinner" *ngIf="applyingImprovements" aria-hidden="true"></span>{{ applyingImprovements ? 'Applying and rescoring…' : 'Apply selected changes' }}
            </button>
          </div>
        </section>
      </div>
    </section>
  `,
})
export class MatchesComponent implements OnInit, OnDestroy {
  jobs: JobPosting[] = [];
  totalJobs = 0;
  currentPage = 1;
  readonly pageSize = 40;
  selected?: JobPosting;
  jobText = '';
  sourceUrl = '';
  search = '';
  minScore = '';
  message = '';
  activeTab: 'matches' | 'import' = 'matches';
  importing = false;
  recomputingJobId: number | null = null;
  preparingJobId: number | null = null;
  regeneratingJobId: number | null = null;
  savingJobId: number | null = null;
  proposingJobId: number | null = null;
  improvementProposal?: ProfileImprovementProposal;
  acceptedSuggestionIds = new Set<string>();
  applyingImprovements = false;
  private eventSub?: Subscription;

  constructor(private api: ApiService, private realtime: RealtimeService) {}

  ngOnInit(): void {
    this.load();
    this.eventSub = this.realtime.events$.subscribe((event) => {
      if (event.type === 'match_recomputed') {
        if (this.recomputingJobId === event.job_id) this.recomputingJobId = null;
        this.message = 'Fit analysis updated.';
        this.load();
      }
      if (event.type === 'match_recompute_failed' && this.recomputingJobId === event.job_id) {
        this.recomputingJobId = null;
        this.message = 'Could not recompute this match.';
      }
      if (event.type === 'matches_recomputed' && this.applyingImprovements) {
        this.applyingImprovements = false;
        this.improvementProposal = undefined;
        this.message = `Profile updated and ${event.count || 'all'} opportunities rescored.`;
        this.load();
      }
      if (event.type === 'materials_regenerated' && this.regeneratingJobId === event.job_id) {
        this.regeneratingJobId = null;
        this.message = `Fresh resume and cover letter version ${event.cover_letter_version || ''} are ready in Resume Studio.`;
      }
      if (event.type === 'materials_regeneration_failed' && this.regeneratingJobId === event.job_id) {
        this.regeneratingJobId = null;
        this.message = 'Could not regenerate the application materials.';
      }
    });
  }

  ngOnDestroy(): void { this.eventSub?.unsubscribe(); }

  load(): void {
    const params: Record<string, string> = {};
    if (this.search) params['search'] = this.search;
    if (this.minScore) params['min_score'] = this.minScore;
    params['page'] = String(this.currentPage);
    this.api.jobs(params).subscribe((page) => {
      this.jobs = page.results;
      this.totalJobs = page.count;
      if (this.selected) {
        const current = this.jobs.find((job) => job.id === this.selected?.id);
        if (current) this.select(current);
        else this.selected = undefined;
      } else if (this.jobs.length) {
        this.select(this.jobs[0]);
      }
    });
  }

  get pageCount(): number { return Math.max(1, Math.ceil(this.totalJobs / this.pageSize)); }
  goToPage(page: number): void { if (page >= 1 && page <= this.pageCount && page !== this.currentPage) { this.currentPage = page; this.selected = undefined; this.load(); } }

  select(job: JobPosting): void {
    this.selected = job;
    this.api.job(job.id).subscribe({
      next: (detail) => {
        if (this.selected?.id === detail.id) this.selected = detail;
      },
      error: () => { this.message = 'Could not load the full opportunity details.'; },
    });
  }

  applicationStatus(status: string): string {
    return status.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  importJob(): void {
    if (this.importing) return;
    this.importing = true;
    this.message = 'Extracting the posting and ranking it against your evidence…';
    this.api.importJob({ text: this.jobText, source_url: this.sourceUrl }).subscribe({
      next: (job) => {
        this.message = 'Job imported.';
        this.jobText = '';
        this.sourceUrl = '';
        this.load();
        this.selected = job;
        this.activeTab = 'matches';
        this.importing = false;
      },
      error: () => { this.message = 'Import failed. Check the posting text and try again.'; this.importing = false; },
    });
  }

  recompute(job: JobPosting): void {
    if (this.recomputingJobId) return;
    this.recomputingJobId = job.id;
    this.api.recomputeJobMatch(job.id).subscribe({
      next: () => this.message = 'Fit analysis is running in the background.',
      error: () => { this.recomputingJobId = null; this.message = 'Could not recompute this match.'; },
    });
  }

  proposeImprovements(job: JobPosting): void {
    if (this.proposingJobId || this.applyingImprovements) return;
    this.proposingJobId = job.id;
    this.message = 'The profile agent is comparing your verified evidence with this role.';
    this.api.proposeProfileImprovements(job.id).subscribe({
      next: (proposal) => {
        this.proposingJobId = null;
        this.improvementProposal = proposal;
        this.acceptedSuggestionIds = new Set(proposal.suggestions.map((suggestion) => suggestion.id));
        this.message = proposal.suggestions.length ? 'Review the proposed profile changes.' : 'No safe wording changes were found.';
      },
      error: () => { this.proposingJobId = null; this.message = 'Could not generate profile improvements.'; },
    });
  }

  toggleSuggestion(id: string): void {
    const next = new Set(this.acceptedSuggestionIds);
    next.has(id) ? next.delete(id) : next.add(id);
    this.acceptedSuggestionIds = next;
  }

  closeImprovementModal(): void {
    if (!this.applyingImprovements) this.improvementProposal = undefined;
  }

  rejectProposal(): void {
    if (!this.improvementProposal || this.applyingImprovements) return;
    this.applyingImprovements = true;
    this.api.applyProfileImprovements(this.improvementProposal.job, this.improvementProposal.id, []).subscribe({
      next: () => {
        this.applyingImprovements = false;
        this.improvementProposal = undefined;
        this.message = 'Profile suggestions rejected. No evidence was changed.';
      },
      error: () => { this.applyingImprovements = false; this.message = 'Could not record your decision.'; },
    });
  }

  applyImprovements(): void {
    if (!this.improvementProposal || this.applyingImprovements || !this.acceptedSuggestionIds.size) return;
    this.applyingImprovements = true;
    const proposal = this.improvementProposal;
    this.api.applyProfileImprovements(proposal.job, proposal.id, [...this.acceptedSuggestionIds]).subscribe({
      next: (result) => {
        this.message = 'Profile changes applied. Recalculating every opportunity with fresh embeddings…';
        this.improvementProposal = undefined;
        if (result.rescore_mode === 'sync' || result.rescore_mode === 'not_needed') {
          this.applyingImprovements = false;
          this.load();
        }
      },
      error: (error) => {
        this.applyingImprovements = false;
        this.message = error?.error?.detail || 'Could not apply the selected changes.';
      },
    });
  }

  tailor(job: JobPosting): void {
    this.message = 'Generating tailored resume.';
    this.api.tailorResume(job.id).subscribe({
      next: () => this.message = 'Your AI-designed resume is ready. Open Resume Studio to review it.',
      error: () => this.message = 'Resume tailoring failed.',
    });
  }

  prepare(job: JobPosting): void {
    if (this.preparingJobId) return;
    this.preparingJobId = job.id;
    this.message = 'Starting the preparation workflow.';
    this.api.requestPreparation(job.id).subscribe({
      next: () => { this.preparingJobId = null; this.message = 'Approval requested. Open Concierge to review it.'; },
      error: () => { this.preparingJobId = null; this.message = 'Could not start the preparation workflow.'; },
    });
  }

  regenerateMaterials(job: JobPosting): void {
    if (this.regeneratingJobId) return;
    this.regeneratingJobId = job.id;
    this.message = 'Generating a fresh resume and cover letter from your latest profile evidence…';
    this.api.regenerateApplicationMaterials(job.id).subscribe({
      next: (result) => {
        if (result.mode === 'sync') {
          this.regeneratingJobId = null;
          this.message = `Fresh resume and cover letter version ${result.cover_letter_version || ''} are ready in Resume Studio.`;
        }
      },
      error: () => {
        this.regeneratingJobId = null;
        this.message = 'Could not regenerate the application materials.';
      },
    });
  }

  createApplication(job: JobPosting): void {
    if (this.savingJobId) return;
    this.savingJobId = job.id;
    this.api.createApplication(job.id).subscribe({
      next: () => { this.savingJobId = null; this.message = 'Application created in pipeline.'; this.load(); },
      error: () => { this.savingJobId = null; this.message = 'Could not create application.'; },
    });
  }
}
