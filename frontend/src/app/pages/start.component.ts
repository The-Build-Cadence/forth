import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { Subject, takeUntil } from 'rxjs';
import { ApiService } from '../services/api.service';

@Component({
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  template: `
    <section class="page setup-page">
      <header class="setup-heading"><p class="eyebrow">A little context. A useful next step.</p><h1>Let’s get your search moving.</h1><p>Start with what you know. You can add more experience and refine your preferences anytime.</p></header>
      <p class="error" role="alert" *ngIf="error">{{ error }}</p>
      <div class="panel setup-card" *ngIf="loading"><p role="status">Loading your saved progress…</p></div>
      <button *ngIf="loadFailed" class="btn-secondary" (click)="load()">Try again</button>
      <ng-container *ngIf="snapshot && !loading">
        <ol class="setup-progress" aria-label="Setup progress"><li [attr.aria-current]="step === 1 ? 'step' : null">1 · Your starting point</li><li [attr.aria-current]="step === 2 ? 'step' : null">2 · Your experience</li><li [attr.aria-current]="step === 3 ? 'step' : null">3 · Your preferences</li></ol>
        <section class="panel setup-card" *ngIf="step === 1">
          <h2>What would you like to do first?</h2><p>Both paths use your experience to help you make a confident next move.</p>
          <div class="setup-paths"><button class="setup-choice" (click)="choose('discover')"><span class="eyebrow">Explore opportunities</span><strong>Find jobs for me <span aria-hidden="true">→</span></strong><span>Get matches based on your roles, location and work preferences.</span></button><button class="setup-choice" (click)="choose('apply')"><span class="eyebrow">Have a role in mind?</span><strong>Help me apply to a job <span aria-hidden="true">→</span></strong><span>Add a posting, understand the fit and prepare your application.</span></button></div>
          <p class="field-hint">You can switch paths anytime. Forth never submits an application for you.</p>
        </section>
        <section class="panel setup-card" *ngIf="step === 2">
          <p class="eyebrow">Your experience</p><h2>Start with your resume</h2><p>We’ll use it to understand your experience. You’ll review uncertain details before using them in an application.</p>
          <div *ngIf="snapshot.document" class="setup-document" role="status"><strong>{{ snapshot.document.name }}</strong><p>{{ documentStatus }}</p><button *ngIf="snapshot.document.status === 'failed'" class="btn-secondary" (click)="retryDocument()" [disabled]="busy">Try reading it again</button></div>
          <label class="setup-upload">Choose a resume<input type="file" accept=".pdf,.doc,.docx,.html,.htm,.odt,.rtf,.txt,.md" (change)="selectFile($event)"><small>PDF, Word or text · up to 15 MB</small></label>
          <details><summary>Paste resume text instead</summary><label>Resume text<textarea rows="6" [(ngModel)]="resumeText" placeholder="Paste your resume here"></textarea></label></details>
          <p class="field-hint">Your resume is stored in your account and processed by Forth’s AI providers. <a routerLink="/privacy">How your information is used</a></p>
          <div class="setup-actions"><button class="btn-secondary" (click)="step = 1" [disabled]="busy">Back</button><button class="btn-primary" (click)="upload()" [disabled]="busy || (!file && !resumeText.trim())">{{ busy ? 'Saving…' : 'Save resume & continue' }}</button><button class="text-button" (click)="step = 3" [disabled]="busy">{{ snapshot.document ? 'Continue with saved resume' : 'Start without a resume' }}</button></div>
          <p class="field-hint" *ngIf="!snapshot.document">Without a resume, you can explore jobs now and add your experience before preparing documents.</p>
        </section>
        <form class="panel setup-card" *ngIf="step === 3" (ngSubmit)="finish()">
          <p class="eyebrow">Your preferences</p><h2>What does your next role look like?</h2><p>Confirm these details. We won’t change your preferences to fill your results.</p>
          <label>Target roles<input name="roles" [(ngModel)]="roles" required maxlength="500" placeholder="e.g. Product designer, UX designer"><small>Separate up to five roles with commas.</small></label>
          <label>Where would you like to work?<input name="location" [(ngModel)]="location" required maxlength="220" placeholder="e.g. Toronto, Canada"><small>Include a country, even for remote work.</small></label>
          <fieldset class="setup-modes"><legend>Work preferences · choose all that fit</legend><label *ngFor="let mode of modes"><input type="checkbox" [checked]="workModes.includes(mode.value)" (change)="toggleMode(mode.value)">{{ mode.label }}</label></fieldset>
          <label>Countries where you can work <span class="optional">Optional</span><input name="countries" [(ngModel)]="countries" maxlength="500" placeholder="e.g. Canada"><small>Separate countries with commas. Leave blank if you’re unsure; eligibility will need confirmation.</small></label>
          <label class="setup-toggle" *ngIf="intent === 'discover' && snapshot.discovery_available"><input name="daily" type="checkbox" [(ngModel)]="daily">Keep finding new matches daily</label>
          <p class="field-hint" *ngIf="intent === 'discover'">{{ snapshot.discovery_available ? 'We’ll start your first search when you continue. You can pause daily searches in Job search settings.' : 'Automatic search is temporarily unavailable. Save your preferences and add a job description to get started.' }}</p>
          <div class="setup-actions"><button class="btn-secondary" type="button" (click)="step = 2" [disabled]="busy">Back</button><button class="btn-primary" type="submit" [disabled]="busy || !canFinish">{{ busy ? 'Saving your preferences…' : intent === 'apply' ? 'Continue to my job' : snapshot.discovery_available ? 'Find my first matches' : 'Save & add a job' }}</button></div>
        </form>
        <button class="text-button setup-later" (click)="finishLater()" [disabled]="busy">Save & finish later</button>
      </ng-container>
    </section>
  `,
})
export class StartComponent implements OnInit, OnDestroy {
  snapshot: any; step = 1; intent: 'discover' | 'apply' = 'discover';
  roles = ''; location = ''; countries = ''; workModes: string[] = []; daily = false;
  modes = [{ value: 'remote', label: 'Remote' }, { value: 'hybrid', label: 'Hybrid' }, { value: 'onsite', label: 'On-site' }];
  file?: File; resumeText = ''; loading = true; busy = false; error = ''; loadFailed = false;
  private destroy$ = new Subject<void>(); private poll?: ReturnType<typeof setTimeout>;
  constructor(private api: ApiService, private router: Router) {}
  ngOnInit(): void { this.load(); }
  ngOnDestroy(): void { this.destroy$.next(); this.destroy$.complete(); if (this.poll) clearTimeout(this.poll); }
  load(): void {
    this.loading = true; this.loadFailed = false; this.error = '';
    this.api.searchSetup().pipe(takeUntil(this.destroy$)).subscribe({ next: data => {
      this.snapshot = data; this.loading = false;
      const p = data.profile; this.roles = p.target_roles.join(', '); this.location = p.location; this.countries = p.authorized_countries.join(', '); this.workModes = [...p.work_modes]; this.daily = !!p.onboarding_state.daily;
      this.intent = p.onboarding_state.intent || 'discover';
      if (p.onboarding_completed_at) this.step = 3; else if (data.document) this.step = 2;
      const draft = p.onboarding_state.setup_draft;
      if (draft) { this.step = draft.step; this.intent = draft.intent; this.roles = draft.roles; this.location = draft.location; this.countries = draft.countries; this.workModes = draft.work_modes; this.daily = draft.daily; }
      this.watchDocument();
    }, error: () => { this.loading = false; this.loadFailed = true; this.error = 'Could not load your saved progress. Please try again.'; } });
  }
  choose(intent: 'discover' | 'apply'): void { this.intent = intent; this.step = 2; }
  toggleMode(value: string): void { this.workModes = this.workModes.includes(value) ? this.workModes.filter(v => v !== value) : [...this.workModes, value]; }
  get canFinish(): boolean { return !!this.roles.trim() && this.roles.split(',').filter(v => v.trim()).length <= 5 && !!this.location.trim() && this.workModes.length > 0; }
  get documentStatus(): string { return this.snapshot?.document?.status === 'ready' ? 'Resume saved and ready. You can refine your profile later.' : this.snapshot?.document?.status === 'failed' ? 'We couldn’t read this file. Retry, replace it or paste its text.' : 'Reading your resume. You can continue while we work.'; }
  selectFile(event: Event): void {
    const file = (event.target as HTMLInputElement).files?.[0]; this.error = ''; this.file = undefined;
    if (!file) return;
    if (!/\.(pdf|docx?|html?|odt|rtf|txt|md)$/i.test(file.name) || file.size > 15 * 1024 * 1024) { this.error = 'Choose a supported resume file smaller than 15 MB.'; return; }
    this.file = file;
  }
  upload(): void {
    if (this.busy || (!this.file && !this.resumeText.trim())) return;
    const form = new FormData(); form.set('kind', 'resume'); form.set('title', this.file?.name || 'My resume'); form.set('raw_text', this.resumeText); if (this.file) form.set('upload', this.file);
    this.busy = true; this.error = '';
    this.api.createDocument(form).pipe(takeUntil(this.destroy$)).subscribe({ next: doc => { this.snapshot.document = { ...doc, name: doc.title }; this.busy = false; this.file = undefined; this.resumeText = ''; this.step = 3; this.watchDocument(); }, error: () => { this.busy = false; this.error = 'Could not save your resume. Try again or paste the text.'; } });
  }
  retryDocument(): void {
    this.busy = true;
    this.api.ingestDocument(this.snapshot.document.id).pipe(takeUntil(this.destroy$)).subscribe({next: () => { this.busy = false; this.snapshot.document.status = 'queued'; this.watchDocument(); }, error: () => { this.busy = false; this.error = 'Could not retry. Please upload the file again.'; }});
  }
  private watchDocument(): void {
    if (this.poll) clearTimeout(this.poll);
    if (!this.snapshot.document || ['ready', 'failed'].includes(this.snapshot.document.status)) return;
    this.poll = setTimeout(() => this.api.searchSetup().pipe(takeUntil(this.destroy$)).subscribe({ next: data => { this.snapshot.document = data.document; this.watchDocument(); }, error: () => { this.error = 'Resume status is unavailable. Your saved file is safe; reload to check again.'; } }), 3000);
  }
  finishLater(): void {
    if (this.busy) return; this.busy = true; this.error = '';
    this.api.saveSetupDraft({intent: this.intent, step: this.step, roles: this.roles, location: this.location, countries: this.countries, work_modes: this.workModes, daily: this.daily}).pipe(takeUntil(this.destroy$)).subscribe({next: () => this.router.navigate(['/dashboard']), error: () => { this.busy = false; this.error = 'Could not save your progress. Please try again before leaving.'; }});
  }
  finish(): void {
    if (!this.canFinish || this.busy) return;
    this.busy = true; this.error = '';
    const split = (s: string) => s.split(',').map(v => v.trim()).filter(Boolean);
    this.api.saveSearchSetup({ intent: this.intent, target_roles: split(this.roles), location: this.location.trim(), work_modes: this.workModes, authorized_countries: split(this.countries), daily: this.daily }).pipe(takeUntil(this.destroy$)).subscribe({ next: () => {
      if (this.intent === 'apply' || !this.snapshot.discovery_available) { this.router.navigate(['/matches'], {queryParams: {tab: 'import'}}); return; }
      this.api.startDiscovery().pipe(takeUntil(this.destroy$)).subscribe({next: () => this.router.navigate(['/dashboard']), error: response => { this.busy = false; this.error = response?.error?.detail || 'Your preferences are saved. Search could not start; please try again.'; }});
    }, error: response => { this.busy = false; this.error = response?.error?.detail || 'Check your preferences and try again. Use up to five roles and ten countries.'; } });
  }
}
