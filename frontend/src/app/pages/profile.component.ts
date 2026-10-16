import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';
import { ApiService, CandidatePreference, CandidateProfile, ProfileDocument, ProfileFact } from '../services/api.service';
import { RealtimeService } from '../services/realtime.service';

@Component({
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <section class="page">
      <div class="page-head">
        <div>
          <p class="eyebrow">Candidate intelligence</p>
          <h1>The system should know the whole story.</h1>
          <p class="page-intro">Build a truthful, living model of your experience, capabilities, goals, constraints, and preferences.</p>
        </div>
        <div class="action-row"><button class="btn-primary" type="button" *ngIf="profile && !profile.onboarding_completed_at" (click)="resumeOnboarding()">✦ Continue guided setup</button><button class="btn-secondary" type="button" (click)="load()">↻ Refresh</button></div>
      </div>

      <div class="summary-strip">
        <div><span>Profile confidence</span><strong>{{ profile?.completeness || 0 }}%</strong></div>
        <div><span>Profile facts</span><strong>{{ facts.length }}</strong></div>
        <div><span>Verified</span><strong>{{ verifiedCount() }}</strong></div>
        <div><span>Source documents</span><strong>{{ documents.length }}</strong></div>
      </div>

      <div class="tabs" role="tablist" aria-label="Profile sections">
        <button type="button" role="tab" [class.active]="activeTab === 'overview'" [attr.aria-selected]="activeTab === 'overview'" (click)="activeTab = 'overview'">Search brief</button>
        <button type="button" role="tab" [class.active]="activeTab === 'facts'" [attr.aria-selected]="activeTab === 'facts'" (click)="activeTab = 'facts'">Profile facts <span>{{ facts.length }}</span></button>
        <button type="button" role="tab" [class.active]="activeTab === 'preferences'" [attr.aria-selected]="activeTab === 'preferences'" (click)="activeTab = 'preferences'">Preferences <span>{{ preferences.length }}</span></button>
        <button type="button" role="tab" [class.active]="activeTab === 'sources'" [attr.aria-selected]="activeTab === 'sources'" (click)="activeTab = 'sources'">Source material <span>{{ documents.length }}</span></button>
      </div>
      <p class="feedback-banner" *ngIf="message">{{ message }}</p>

      <section class="panel profile-brief" *ngIf="activeTab === 'overview' && profile">
        <div class="panel-head"><div><h2>Your search brief</h2><p>These explicit choices drive eligibility, ranking, and the concierge’s recommendations.</p></div><span class="confidence-badge">{{ profile.completeness }}% complete</span></div>
        <div class="edit-grid">
          <label>Professional headline<input [(ngModel)]="profile.headline" name="headline" placeholder="Senior platform engineer building dependable AI products"></label>
          <label>Current location<input [(ngModel)]="profile.location" name="profileLocation" placeholder="Toronto, Canada"></label>
          <label>Target roles <span class="field-hint">Comma separated</span><input [(ngModel)]="targetRolesText" name="targetRoles" placeholder="Staff Engineer, Engineering Lead"></label>
          <label>Target industries <span class="field-hint">Comma separated</span><input [(ngModel)]="targetIndustriesText" name="targetIndustries" placeholder="Developer tools, AI platforms"></label>
          <label>Authorized countries <span class="field-hint">Comma separated</span><input [(ngModel)]="authorizedCountriesText" name="authorizedCountries" placeholder="Canada"></label>
          <label>Work modes <span class="field-hint">Comma separated</span><input [(ngModel)]="workModesText" name="workModes" placeholder="remote, hybrid"></label>
          <label>Employment types <span class="field-hint">Comma separated</span><input [(ngModel)]="employmentTypesText" name="employmentTypes" placeholder="full-time, contract"></label>
          <label>Minimum compensation<input type="number" [(ngModel)]="profile.minimum_compensation" name="minimumCompensation" placeholder="150000"></label>
          <label>Currency<select [(ngModel)]="profile.compensation_currency" name="compensationCurrency"><option>CAD</option><option>USD</option><option>EUR</option><option>GBP</option></select></label>
          <label class="match-threshold-control">Minimum evidence fit
            <input type="range" min="1" max="99" step="1" [(ngModel)]="profile.minimum_match_score" name="minimumMatchScore">
            <span><strong>{{ profile.minimum_match_score }}</strong> raw = <strong>{{ normalizedThreshold() }}</strong> calibrated</span>
            <small>Roles at or above this raw score are good enough for Forth to prepare. Calibrated scores make this decision point 80.</small>
          </label>
        </div>
        <label>Professional summary<textarea rows="6" [(ngModel)]="profile.professional_summary" name="professionalSummary" placeholder="Describe what you are great at, the work you enjoy, and what you want next."></textarea></label>
        <label>Default material instructions<textarea rows="5" maxlength="6000" [(ngModel)]="profile.generation_instructions" name="generationInstructions" placeholder="Use a minimal layout, accent #2f5f9f, concise bullets, and a warm, direct cover letter."></textarea></label>
        <p class="field-hint">Used for every new resume and cover letter. An opportunity can replace these defaults. Supported layouts: modern, classic, minimal; spacing: compact, balanced, spacious; paper: Letter or A4. Use a six-digit hex color for an exact accent. Existing versions stay unchanged.</p>
        <div class="action-row"><button class="btn-primary" type="button" (click)="saveProfile()" [disabled]="savingProfile"><span class="spinner" *ngIf="savingProfile" aria-hidden="true"></span>{{ savingProfile ? 'Saving…' : 'Save search brief' }}</button><span class="muted">Changes immediately affect future scoring.</span></div>
      </section>

      <section class="panel" *ngIf="activeTab === 'preferences'">
        <div class="panel-head"><div><h2>Preferences and boundaries</h2><p>Make intent explicit: must-have, strong preference, flexible, or avoid.</p></div></div>
        <div class="preference-form"><input [(ngModel)]="newPreference.label" name="preferenceLabel" placeholder="e.g. Hands-on technical work"><select [(ngModel)]="newPreference.category" name="preferenceCategory"><option value="role">Role</option><option value="work_mode">Work mode</option><option value="industry">Industry</option><option value="culture">Culture</option><option value="company">Company</option></select><select [(ngModel)]="newPreference.importance" name="preferenceImportance"><option value="must">Must have</option><option value="strong">Strong</option><option value="flexible">Flexible</option><option value="avoid">Avoid</option></select><button class="btn-primary" type="button" (click)="addPreference()">Add</button></div>
        <div class="preference-list"><article *ngFor="let preference of preferences"><span class="preference-level" [class.avoid]="preference.importance === 'avoid'">{{ preference.importance }}</span><div><strong>{{ preference.label }}</strong><small>{{ preference.category }}</small></div><button class="icon-button" type="button" aria-label="Remove preference" (click)="removePreference(preference)">×</button></article></div>
      </section>

      <section class="panel" *ngIf="activeTab === 'facts'">
        <div class="panel-head">
          <div>
            <h2>Career evidence</h2>
            <p>Review extracted details and verify anything you want Forth to prioritize.</p>
          </div>
          <div class="search-field"><span>⌕</span><input class="compact-input" aria-label="Search facts" placeholder="Search facts" [(ngModel)]="factSearch" (input)="loadFacts()"></div>
        </div>
        <div class="fact-grid">
          <article class="fact-card" *ngFor="let fact of facts">
            <ng-container *ngIf="editingFactId === fact.id; else factView">
              <label>
                Type
                <select [(ngModel)]="factDraft.fact_type" [name]="'factType' + fact.id">
                  <option *ngFor="let type of factTypes" [value]="type">{{ type }}</option>
                </select>
              </label>
              <label>
                Title
                <input [(ngModel)]="factDraft.title" [name]="'factTitle' + fact.id">
              </label>
              <label>
                Statement
                <textarea rows="5" [(ngModel)]="factDraft.statement" [name]="'factStatement' + fact.id"></textarea>
              </label>
              <label>
                Normalized value
                <input [(ngModel)]="factDraft.normalized_value" [name]="'factNormalized' + fact.id">
              </label>
              <div class="edit-grid compact-edit-grid">
                <label>
                  Confidence
                  <select [(ngModel)]="factDraft.confidence" [name]="'factConfidence' + fact.id">
                    <option *ngFor="let confidence of confidenceOptions" [value]="confidence">{{ confidence }}</option>
                  </select>
                </label>
                <label class="checkbox-label">
                  <input type="checkbox" [(ngModel)]="factDraft.verified_by_user" [name]="'factVerified' + fact.id">
                  Verified
                </label>
              </div>
              <div class="action-row">
                <button class="btn-primary" type="button" (click)="saveFact(fact)">Save</button>
                <button class="btn-secondary" type="button" (click)="cancelEdit()">Cancel</button>
              </div>
            </ng-container>

            <ng-template #factView>
              <div class="card-line">
                <span class="status-chip">{{ fact.fact_type }}</span>
                <span class="status-chip" [class.good]="fact.verified_by_user">{{ fact.verified_by_user ? 'verified' : fact.confidence }}</span>
              </div>
              <h3>{{ fact.title }}</h3>
              <p>{{ fact.statement }}</p>
              <small *ngIf="fact.source_document_title">From {{ fact.source_document_title }}</small>
              <div class="action-row">
                <button class="btn-mini" type="button" *ngIf="!fact.verified_by_user" (click)="verify(fact)">Verify</button>
                <button class="btn-mini" type="button" (click)="editFact(fact)">Edit</button>
                <button class="btn-mini btn-danger" type="button" (click)="deleteFact(fact)">Delete</button>
              </div>
            </ng-template>
          </article>
        </div>
        <div class="empty-state" *ngIf="!facts.length">
          <span class="empty-icon">◎</span>
          <h3>No profile facts yet</h3>
          <p>Add source material and Forth will extract reusable career evidence.</p>
          <button class="btn-primary" type="button" (click)="activeTab = 'sources'">Add source material</button>
        </div>
      </section>

      <div class="two-col profile-source-grid" *ngIf="activeTab === 'sources'">
        <section class="panel">
          <div class="panel-head compact-heading">
            <div><span class="section-icon">＋</span><h2>Add source material</h2></div>
          </div>
          <p class="section-copy">Upload a resume or paste notes, reviews, and project details.</p>
          <form class="stack" (ngSubmit)="createDocument()">
            <div class="edit-grid">
              <label>Type
                <select name="kind" [(ngModel)]="kind">
                  <option value="resume">Resume</option><option value="note">Note</option><option value="conversation">Conversation</option><option value="project">Project</option><option value="review">Review</option>
                </select>
              </label>
              <label>Title<input name="title" [(ngModel)]="title" placeholder="e.g. 2026 master resume"></label>
            </div>
            <label class="file-drop">Upload a file<input type="file" (change)="onFile($event)"><span>PDF, DOCX, or plain text</span></label>
            <label>Or paste text<textarea name="rawText" rows="9" [(ngModel)]="rawText" placeholder="Paste resume content, accomplishments, feedback, or project notes…"></textarea></label>
            <div class="action-row form-actions"><button class="btn-primary" type="submit" [disabled]="extracting || (!rawText.trim() && !file)"><span class="spinner" *ngIf="extracting" aria-hidden="true"></span>{{ extracting ? 'Extracting facts…' : 'Extract profile facts' }}</button></div>
          </form>
        </section>

        <section class="panel">
          <div class="panel-head"><div><h2>Source documents</h2><p>Your ingestion history and current processing status.</p></div></div>
          <div class="document-list">
            <div class="list-row" *ngFor="let document of documents">
              <span class="document-icon">{{ document.kind === 'resume' ? 'CV' : 'TXT' }}</span>
              <div class="list-row-main"><strong>{{ document.title }}</strong><p>{{ document.kind }} · {{ document.status_message }}</p></div>
              <span class="status-chip" [class.good]="document.status === 'ready'">{{ document.status }}</span>
            </div>
          </div>
          <div class="empty-state small" *ngIf="!documents.length"><span class="empty-icon">□</span><h3>No source documents</h3><p>Your uploaded material will appear here.</p></div>
        </section>
      </div>
    </section>
  `,
})
export class ProfileComponent implements OnInit, OnDestroy {
  profile?: CandidateProfile;
  preferences: CandidatePreference[] = [];
  documents: ProfileDocument[] = [];
  facts: ProfileFact[] = [];
  factTypes = ['skill', 'achievement', 'role', 'project', 'metric', 'preference', 'constraint', 'education'];
  confidenceOptions = ['low', 'medium', 'high'];
  kind = 'resume';
  title = 'Canonical Resume';
  rawText = '';
  factSearch = '';
  message = '';
  savingProfile = false;
  extracting = false;
  activeTab: 'overview' | 'facts' | 'preferences' | 'sources' = 'overview';
  targetRolesText = '';
  targetIndustriesText = '';
  authorizedCountriesText = '';
  workModesText = '';
  employmentTypesText = '';
  newPreference: Partial<CandidatePreference> = { category: 'role', importance: 'strong', label: '', value: {}, verified_by_user: true };
  editingFactId: number | null = null;
  factDraft: Partial<ProfileFact> = {};
  file?: File;
  private realtimeSub?: Subscription;

  constructor(private api: ApiService, private route: ActivatedRoute, private realtime: RealtimeService) {}

  ngOnInit(): void {
    if (this.route.snapshot.queryParamMap.get('tab') === 'sources') this.activeTab = 'sources';
    this.load();
    this.realtimeSub = this.realtime.events$.subscribe((event) => {
      if (event.type === 'profile_ingestion_started') {
        this.extracting = true;
        this.message = 'Reading your source and extracting reusable evidence…';
      }
      if (event.type === 'profile_ingestion_finished') {
        this.extracting = false;
        this.message = event.status === 'failed'
          ? `Profile extraction failed: ${event.error || 'review the source and try again.'}`
          : `Profile source ready. ${event.created_facts || 0} facts added.`;
      }
      if (['profile_ingestion_finished', 'profile_fact_updated', 'profile_fact_deleted'].includes(event.type)) {
        this.load();
      }
      if (event.type === 'candidate_onboarding_updated') this.load();
    });
  }

  ngOnDestroy(): void {
    this.realtimeSub?.unsubscribe();
  }

  load(): void {
    this.api.candidateProfile().subscribe((profile) => {
      this.profile = profile;
      this.targetRolesText = profile.target_roles.join(', ');
      this.targetIndustriesText = profile.target_industries.join(', ');
      this.authorizedCountriesText = profile.authorized_countries.join(', ');
      this.workModesText = profile.work_modes.join(', ');
      this.employmentTypesText = profile.employment_types.join(', ');
    });
    this.api.preferences().subscribe((page) => this.preferences = page.results);
    this.api.documents().subscribe((page) => this.documents = page.results);
    this.loadFacts();
  }

  loadFacts(): void {
    const params: Record<string, string> = this.factSearch ? { search: this.factSearch } : {};
    this.api.facts(params).subscribe((page) => this.facts = page.results);
  }

  verifiedCount(): number {
    return this.facts.filter((fact) => fact.verified_by_user).length;
  }

  values(text: string): string[] { return text.split(',').map((value) => value.trim()).filter(Boolean); }

  normalizedThreshold(): number { return 80; }

  resumeOnboarding(): void {
    sessionStorage.removeItem('forth_onboarding_dismissed');
    window.location.reload();
  }

  saveProfile(): void {
    if (!this.profile) return;
    this.savingProfile = true;
    const payload = {
      base_updated_at: this.profile.updated_at,
      generation_instructions: this.profile.generation_instructions,
      headline: this.profile.headline,
      professional_summary: this.profile.professional_summary,
      location: this.profile.location,
      minimum_compensation: this.profile.minimum_compensation,
      compensation_currency: this.profile.compensation_currency,
      minimum_match_score: this.profile.minimum_match_score,
      target_roles: this.values(this.targetRolesText),
      target_industries: this.values(this.targetIndustriesText),
      authorized_countries: this.values(this.authorizedCountriesText),
      work_modes: this.values(this.workModesText).map((value) => value.toLowerCase()),
      employment_types: this.values(this.employmentTypesText).map((value) => value.toLowerCase()),
    };
    this.api.updateCandidateProfile(payload).subscribe({
      next: (profile) => { this.profile = profile; this.message = 'Search brief saved.'; this.savingProfile = false; },
      error: (response) => {
        this.message = response?.status === 409
          ? 'Your Profile Steward saved newer answers while this page was open. I kept those answers and refreshed the page.'
          : 'Could not save the search brief.';
        this.savingProfile = false;
        if (response?.status === 409) this.load();
      },
    });
  }

  addPreference(): void {
    if (!String(this.newPreference.label || '').trim()) return;
    this.api.createPreference(this.newPreference).subscribe((preference) => {
      this.preferences.push(preference);
      this.newPreference = { category: 'role', importance: 'strong', label: '', value: {}, verified_by_user: true };
    });
  }

  removePreference(preference: CandidatePreference): void {
    this.api.deletePreference(preference.id).subscribe(() => this.preferences = this.preferences.filter((item) => item.id !== preference.id));
  }

  onFile(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.file = input.files?.[0];
    if (this.file && !this.title) {
      this.title = this.file.name;
    }
  }

  createDocument(): void {
    if (this.extracting || (!this.rawText.trim() && !this.file)) return;
    const payload = new FormData();
    payload.set('kind', this.kind);
    payload.set('title', this.title || 'Profile source');
    payload.set('raw_text', this.rawText);
    if (this.file) {
      payload.set('upload', this.file);
    }
    this.extracting = true;
    this.message = 'Uploading source material…';
    this.api.createDocument(payload).subscribe({
      next: () => {
        this.rawText = '';
        this.file = undefined;
        this.load();
      },
      error: () => { this.extracting = false; this.message = 'Could not ingest document.'; },
    });
  }

  verify(fact: ProfileFact): void {
    this.api.verifyFact(fact.id).subscribe((updated) => {
      fact.verified_by_user = updated.verified_by_user;
    });
  }

  editFact(fact: ProfileFact): void {
    this.editingFactId = fact.id;
    this.factDraft = { ...fact };
  }

  cancelEdit(): void {
    this.editingFactId = null;
    this.factDraft = {};
  }

  saveFact(fact: ProfileFact): void {
    const payload: Partial<ProfileFact> = {
      fact_type: String(this.factDraft.fact_type || fact.fact_type),
      title: String(this.factDraft.title || '').trim(),
      statement: String(this.factDraft.statement || '').trim(),
      normalized_value: String(this.factDraft.normalized_value || '').trim(),
      confidence: String(this.factDraft.confidence || fact.confidence),
      verified_by_user: Boolean(this.factDraft.verified_by_user),
    };
    if (!payload.title || !payload.statement) {
      this.message = 'Title and statement are required.';
      return;
    }
    this.api.updateFact(fact.id, payload).subscribe({
      next: (updated) => {
        Object.assign(fact, updated);
        this.message = 'Profile fact saved.';
        this.cancelEdit();
      },
      error: () => this.message = 'Could not save profile fact.',
    });
  }

  deleteFact(fact: ProfileFact): void {
    if (!confirm(`Delete "${fact.title}"?`)) {
      return;
    }
    this.api.deleteFact(fact.id).subscribe({
      next: () => {
        this.facts = this.facts.filter((item) => item.id !== fact.id);
        this.message = 'Profile fact deleted.';
        if (this.editingFactId === fact.id) {
          this.cancelEdit();
        }
      },
      error: () => this.message = 'Could not delete profile fact.',
    });
  }
}
