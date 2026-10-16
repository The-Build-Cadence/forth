import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Subject, Subscription, takeUntil } from 'rxjs';
import { ApiService, JobSource, SourceRun } from '../services/api.service';
import { RealtimeService } from '../services/realtime.service';

@Component({
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <section class="page">
      <div class="page-head">
        <div>
          <p class="eyebrow">Discovery</p>
          <h1>A quiet, reliable discovery engine.</h1>
          <p class="page-intro">Search the open web from your role and location brief, learn from each pass, and keep a complete audit trail.</p>
        </div>
        <button class="btn-secondary" type="button" (click)="load()">↻ Refresh</button>
      </div>

      <section class="panel brave-panel">
        <div class="panel-head"><div><p class="eyebrow">Brave Search</p><h2>Set the discovery cadence</h2><p>Queries come from target roles and location unless you add focused variations.</p></div>
          <div class="button-row"><button class="btn-secondary" type="button" *ngIf="braveSource" (click)="run(braveSource)" [disabled]="isRunning(braveSource)">{{ isRunning(braveSource) ? 'Searching…' : 'Search now' }}</button><button class="btn-primary" type="button" (click)="createBrave()" [disabled]="saving"><span class="spinner" *ngIf="saving"></span>{{ braveSource ? 'Save schedule' : 'Activate web discovery' }}</button></div>
        </div>
        <div class="schedule-grid">
          <label>Repeat every
            <select [(ngModel)]="scheduleMinutes" name="scheduleMinutes"><option [ngValue]="60">hour</option><option [ngValue]="360">6 hours</option><option [ngValue]="720">12 hours</option><option [ngValue]="1440">day</option></select>
          </label>
          <label>Country code<input [(ngModel)]="braveCountry" name="braveCountry" maxlength="2"></label>
          <label>Jobs to save per run<input type="number" [(ngModel)]="maxCandidates" name="maxCandidates" min="1" max="20" step="1"><span class="field-hint">Up to 20 matching jobs. Each search query requests Brave’s maximum of 20 results; duplicates and unsuitable roles are still filtered out.</span></label>
          <label>Minimum discovery fit
            <div class="threshold-control"><input type="range" [(ngModel)]="minimumFitScore" name="minimumFitScore" min="20" max="90" step="5"><output>{{ minimumFitScore }}</output></div>
            <span class="field-hint">Requires a matching role, location and work mode. Equivalent titles receive equal credit; embeddings refine the score.</span>
          </label>
          <label class="wide">Focused query variations <span class="field-hint">one per line, optional</span><textarea rows="3" [(ngModel)]="braveQueries" name="braveQueries" placeholder="e.g. senior platform engineer Toronto jobs"></textarea><span class="field-hint">Results are deduplicated and ranked by embedding similarity and role keywords before anything is saved. Discovery uses no LLM completions.</span></label>
        </div>
        <p class="muted" *ngIf="braveSource">{{ braveSource.last_message || 'Ready for its first search.' }}</p>
      </section>

      <section class="panel run-visual" *ngIf="activeRun || latestRun">
        <div class="panel-head"><div><h2>{{ activeRun ? 'Discovery in progress' : 'Discovery run' }}</h2><p>{{ activeRun ? 'Follow each decision as it happens.' : runSummary(latestRun!) }}</p></div></div>
        <div class="flow-header"><p><span>Queries</span><b>{{ searchCount() }}</b></p><p><span>Direct pages</span><b>{{ (activeRun || latestRun)?.discovered_count || 0 }}</b></p><p><span>Qualified</span><b>{{ shortlistedCount() }}</b></p><p><span>Imported</span><b>{{ (activeRun || latestRun)?.imported_count || 0 }}</b></p></div>
        <p class="flow-status" aria-live="polite">{{ activeRun ? currentStep() : runSummary(latestRun!) }}</p>
        <ol class="stage-progress" aria-label="Discovery stages">
          <li *ngFor="let stage of stages; let i = index" [class.reached]="i <= stageIndex()" [attr.aria-current]="activeRun && i === stageIndex() ? 'step' : null">{{ stage }}</li>
        </ol>
        <p class="flow-note" *ngIf="!activeRun && !latestRun?.discovered_count">No direct job pages were found in this run.</p>
        <p class="run-outcome" *ngIf="!activeRun">{{ outcomeSummary() }}</p>
        <details class="rejection-details" *ngIf="rejectedEvents().length">
          <summary>Why {{ rejectedEvents().length }} pages were not imported</summary>
          <div class="rejection-row" *ngFor="let rejection of rejectedEvents()">
            <a [href]="rejection.url" target="_blank" rel="noopener noreferrer">{{ rejection.title }}</a>
            <span *ngIf="rejection.score !== null && rejection.score !== undefined">Fit {{ rejection.score }} / minimum {{ rejection.threshold }}</span>
            <p>{{ rejection.reason }}</p>
          </div>
        </details>
        <div class="candidate-list" *ngIf="candidateEvents().length"><div *ngFor="let candidate of candidateEvents()"><span>{{ candidate.rank }}</span><p>{{ candidate.title }}</p><b>{{ candidate.score }}</b></div></div>
        <div class="event-stream" *ngIf="(activeRun || latestRun)?.log?.length">
          <p *ngFor="let event of recentEvents()"><span>◌</span> {{ event.message }}</p>
        </div>
      </section>

      <p class="muted">{{ message }}</p>

      <section class="panel">
        <div class="panel-head"><div><h2>Run history</h2><p>Every sourcing pass, including the searches and evaluation stages.</p></div></div>
        <div class="list-row" *ngFor="let run of runs">
          <span class="document-icon">{{ run.status === 'failed' ? '!' : run.status === 'running' ? '◌' : '✓' }}</span>
          <div class="list-row-main"><strong>{{ run.source_name }}</strong><p>{{ runSummary(run) }} · {{ run.created_at | date:'medium' }}</p></div>
          <button class="btn-mini" type="button" (click)="viewRun(run)" [disabled]="!!activeRun">View</button>
        </div>
        <div class="empty-state small" *ngIf="!runs.length"><span class="empty-icon">⌁</span><h3>No runs yet</h3><p>Trigger a source manually or wait for its schedule.</p></div>
      </section>
    </section>
  `,
  styles: [`
    .brave-panel { margin-bottom: 1.25rem; }
    .button-row { display: flex; gap: .6rem; align-items: center; }
    .schedule-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; align-items: start; }
    .schedule-grid .wide { grid-column: 1 / -1; }
    .run-visual { margin-bottom: 1.25rem; overflow: hidden; }
    .run-outcome { padding:.8rem; background:#f6f8f5; border-radius:.6rem; font-size:.88rem; }.rejection-details { margin:1rem 0; font-size:.85rem; }.rejection-details summary { cursor:pointer; font-weight:600; }.rejection-row { padding:.75rem 0; border-bottom:1px solid #e2e9e4; }.rejection-row a { color:#285f4a; }.rejection-row span { margin-left:.7rem; color:#67786f; }.rejection-row p { margin:.3rem 0 0; color:#67786f; }
    .flow-status { display:flex; gap:.5rem; align-items:center; font-size:.85rem; color:#425f50; }.flow-note { font-size:.75rem; color:#67786f; margin:.65rem 0; }
    .threshold-control { display:flex; align-items:center; gap:.6rem; }.threshold-control input { flex:1; }.threshold-control output { min-width:2.3rem; font-weight:700; color:#2d6b57; }
    .flow-header { display:grid; grid-template-columns:repeat(4, 1fr); gap:.55rem; margin:1rem 0 .6rem; }.flow-header p { display:flex; flex-direction:column; gap:.12rem; margin:0; padding:.55rem .7rem; border:1px solid #e4ebe7; border-radius:.65rem; background:#fbfdfb; color:#62736c; font-size:.73rem; }.flow-header b { color:#1e6046; font-size:1.12rem; }
    .stage-progress { display:flex; gap:6px; padding:0; list-style:none; margin:16px 0; }.stage-progress li { flex:1; border-top:5px solid #dce4e0; padding-top:8px; color:#65756d; font-size:12px; }.stage-progress li.reached { border-color:#26836b; color:#185b48; }
    .candidate-list { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:.5rem; margin:.8rem 0; }.candidate-list div { display:grid; grid-template-columns:24px 1fr auto; align-items:center; gap:.45rem; padding:.45rem .55rem; border:1px solid #e3e8ed; border-radius:.45rem; }.candidate-list span { color:#2d6b57; font-weight:700; }.candidate-list p { margin:0; font-size:.78rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }.candidate-list b { color:#2d6b57; }
    .event-stream { border-left: 2px solid #dce8e2; padding-left: .85rem; max-height: 145px; overflow: auto; }
    .event-stream p { margin: .4rem 0; font-size: .88rem; }.event-stream span { color: #2d6b57; }
    @media (max-width: 650px) { .schedule-grid { grid-template-columns: 1fr; }.flow-header { grid-template-columns:repeat(2, 1fr); }  }
  `],
})
export class SourcesComponent implements OnInit, OnDestroy {
  sources: JobSource[] = [];
  runs: SourceRun[] = [];
  latestRun?: SourceRun;
  activeRun?: SourceRun;
  braveSource?: JobSource;
  scheduleMinutes = 360;
  braveCountry = 'CA';
  braveQueries = '';
  minimumFitScore = 45;
  maxCandidates = 20;
  message = '';
  saving = false;
  runningSourceIds = new Set<number>();
  private eventSub?: Subscription;
  private runPoll?: ReturnType<typeof setTimeout>;
  private destroyed = false;
  private destroy$ = new Subject<void>();
  private watchedRunId?: number;

  constructor(private api: ApiService, private realtime: RealtimeService) {}

  ngOnInit(): void {
    this.load();
    this.eventSub = this.realtime.events$.subscribe((event) => {
      if (event.type === 'source_run_progress') {
        if (this.activeRun?.id === Number(event.source_run_id)) {
          const log = this.activeRun.log || [];
          const sequence = Number(event.sequence || log.length + 1);
          if (sequence <= log.length) return;
          if (sequence !== log.length + 1) return; // The polling snapshot fills gaps.
          this.activeRun = { ...this.activeRun, ...(event.counts || {}), log: [...log, event.event] };
          this.latestRun = this.activeRun;
        }
      }
      if (event.type === 'source_run_finished') {
        this.runningSourceIds.delete(Number(event.source_id));
        this.runningSourceIds = new Set(this.runningSourceIds);
        this.message = `Source refresh finished: ${event.imported || 0} new, ${event.updated || 0} updated.`;
        if (this.activeRun) this.watchRun(this.activeRun.id);
      }
    });
  }


  ngOnDestroy(): void {
    this.destroyed = true; this.destroy$.next(); this.destroy$.complete(); this.eventSub?.unsubscribe();
    if (this.runPoll) clearTimeout(this.runPoll);
  }

  load(): void {
    this.api.sources().subscribe((page) => {
      this.sources = page.results;
      this.braveSource = this.sources.find((source) => source.kind === 'brave');
      if (this.braveSource) {
        this.scheduleMinutes = Number(this.braveSource.config?.schedule_minutes || 360);
        this.braveCountry = this.braveSource.config?.country || 'CA';
        this.braveQueries = (this.braveSource.config?.queries || []).join('\n');
        this.minimumFitScore = Number(this.braveSource.config?.min_triage_score || 45);
        this.maxCandidates = Math.max(1, Math.min(20, Number(this.braveSource.config?.max_candidates || 20)));
      }
    });
    this.api.sourceRuns().subscribe((page) => {
      this.runs = page.results;
      const running = this.runs.find((run) => ['queued', 'running'].includes(run.status));
      this.activeRun = running;
      // A manual run starts with zero counters. Always replace that optimistic
      // response with the server's newest persisted run after loading, or the
      // summary will keep displaying the queued zeroes after completion.
      if (this.runs.length) this.latestRun = this.runs[0];
      if (running && this.watchedRunId !== running.id) this.watchRun(running.id);
    });
  }

  createBrave(): void {
    if (!Number.isInteger(this.maxCandidates) || this.maxCandidates < 1 || this.maxCandidates > 20) { this.message = 'Choose between 1 and 20 jobs per run.'; return; }
    const config = { ...this.braveSource?.config, connector: 'brave', schedule_minutes: this.scheduleMinutes, country: this.braveCountry.trim().toUpperCase(), queries: this.braveQueries.split('\n').map((q) => q.trim()).filter(Boolean), results_per_query: 20, max_candidates: this.maxCandidates, min_triage_score: this.minimumFitScore };
    this.saving = true;
    const request = this.braveSource
      ? this.api.updateSource(this.braveSource.id, { config, enabled: true })
      : this.api.createSource({ name: 'Brave web discovery', kind: 'brave', config, enabled: true });
    request.subscribe({ next: () => { this.saving = false; this.message = 'Brave discovery schedule saved.'; this.load(); }, error: (error) => { this.saving = false; this.message = error?.error?.detail || 'Could not save the Brave schedule.'; } });
  }

  run(source: JobSource): void {
    if (this.isRunning(source)) return;
    this.runningSourceIds.add(source.id);
    this.runningSourceIds = new Set(this.runningSourceIds);
    source.last_status = 'queued';
    source.last_message = 'Discovery refresh queued.';
    this.api.runSource(source.id).subscribe({
      next: (run) => { this.activeRun = run; this.latestRun = run; this.message = `${source.name} is refreshing in the background. You can leave this page.`; this.watchRun(run.id); },
      error: () => { source.last_status = 'failed'; this.runningSourceIds.delete(source.id); this.runningSourceIds = new Set(this.runningSourceIds); this.message = `${source.name} could not be refreshed.`; },
    });
  }

  isRunning(source: JobSource): boolean { return this.runningSourceIds.has(source.id) || ['queued', 'running'].includes(source.last_status); }

  private watchRun(runId: number): void {
    if (this.destroyed) return;
    this.watchedRunId = runId;
    if (this.runPoll) clearTimeout(this.runPoll);
    this.api.sourceRun(runId).pipe(takeUntil(this.destroy$)).subscribe({
      next: (run) => {
        if (this.destroyed) return;
        if (this.activeRun?.id === runId && ['queued', 'running'].includes(run.status) && (run.log?.length || 0) < (this.activeRun.log?.length || 0)) {
          this.runPoll = setTimeout(() => this.watchRun(runId), 1500);
          return;
        }
        this.latestRun = run;
        if (['queued', 'running'].includes(run.status)) {
          this.activeRun = run;
          this.runPoll = setTimeout(() => this.watchRun(runId), 1500);
          return;
        }
        this.activeRun = undefined;
        this.watchedRunId = undefined;
        this.runningSourceIds.clear();
        this.runningSourceIds = new Set();
        this.message = `Source refresh finished: ${run.imported_count} new, ${run.updated_count} refreshed.`;
        this.load();
      },
      error: () => { this.runPoll = setTimeout(() => this.watchRun(runId), 3000); },
    });
  }

  hasStep(level: string): boolean { return Boolean((this.activeRun || this.latestRun)?.log?.some((event: any) => event.level === level)); }
  candidateEvents(): any[] { return ((this.activeRun || this.latestRun)?.log || []).filter((event: any) => event.level === 'candidate'); }
  searchCount(): number { return ((this.activeRun || this.latestRun)?.log || []).filter((event: any) => event.level === 'search').length; }
  shortlistedCount(): number {
    // Older runs predate per-candidate events. Their imported count is the most
    // faithful available proxy for the qualified stage.
    const run = this.activeRun || this.latestRun;
    const evaluated = [...(run?.log || [])].reverse().find(event => event.level === 'evaluate');
    return evaluated?.count ?? (this.candidateEvents().length || ((run?.imported_count || 0) + (run?.updated_count || 0)));
  }
  isComplete(): boolean { return ['succeeded', 'partial'].includes((this.activeRun || this.latestRun)?.status || ''); }

  recentEvents(): any[] { return [...((this.activeRun || this.latestRun)?.log || [])].slice(-6).reverse(); }
  rejectedEvents(): any[] { return ((this.activeRun || this.latestRun)?.log || []).filter(event => event.level === 'rejected'); }
  outcomeSummary(): string {
    const run = this.activeRun || this.latestRun;
    if (!run) return '';
    if (run.imported_count) return `${run.imported_count} new opportunities imported; ${run.updated_count} existing opportunities refreshed.`;
    if (run.updated_count) return `No new opportunities this time. ${run.updated_count} existing opportunities were refreshed.`;
    const notice = (run.log || []).find(event => event.level === 'notice');
    if (notice) return notice.message;
    if (run.status === 'failed') return 'Search failed. See the error in the activity log.';
    if (!run.discovered_count) return 'No direct job pages found. Empty queries are cooled down, and future runs try other role and website combinations.';
    const summary = (run.log || []).find(event => event.level === 'rejection_summary');
    return summary?.message || 'No pages passed this run’s checks. Older runs did not save individual rejection reasons.';
  }
  currentStep(): string { return this.recentEvents()[0]?.message || 'Waiting for search results…'; }
  viewRun(run: SourceRun): void { this.latestRun = run; }
  stages = ['Search', 'Check fit', 'Save', 'Finished'];
  stageIndex(): number {
    const run = this.activeRun || this.latestRun;
    if (!run || run.status === 'queued') return -1;
    if (['succeeded', 'partial'].includes(run.status)) return 3;
    const levels = (run.log || []).map(event => event.level);
    if (levels.includes('import') || levels.includes('candidate') || levels.includes('evaluate')) return 2;
    if (levels.includes('evaluating')) return 1;
    return 0;
  }
  runSummary(run: SourceRun): string { return `${run.status} · ${run.discovered_count} identified · ${run.imported_count} new · ${run.updated_count} refreshed`; }
}
