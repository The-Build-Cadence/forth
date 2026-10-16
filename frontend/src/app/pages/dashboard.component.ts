import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ApiService } from '../services/api.service';

@Component({
  standalone: true,
  imports: [CommonModule, RouterLink],
  template: `
    <section class="page today-page">
      <div class="today-hero">
        <div>
          <p class="eyebrow">{{ todayLabel }} · Your daily briefing</p>
          <h1>Good morning.<br><span>Three decisions can move your search forward.</span></h1>
          <p>{{ data?.greeting }}</p>
        </div>
        <a class="concierge-cta" routerLink="/concierge"><span>✦</span><div><strong>Ask your concierge</strong><small>Delegate or clarify anything</small></div><i>→</i></a>
      </div>

      <div class="signal-strip">
        <a routerLink="/matches"><span class="signal-icon lime">◇</span><div><small>Roles to review</small><strong>{{ data?.review_count || 0 }}</strong></div><i>Fresh, ranked opportunities</i></a>
        <a routerLink="/concierge"><span class="signal-icon coral">!</span><div><small>Decisions waiting</small><strong>{{ data?.pending_approvals || 0 }}</strong></div><i>Your approval is required</i></a>
        <a routerLink="/pipeline"><span class="signal-icon cyan">↗</span><div><small>Follow-ups due</small><strong>{{ data?.followups_due || 0 }}</strong></div><i>Keep conversations moving</i></a>
        <a routerLink="/profile"><span class="signal-icon violet">◎</span><div><small>Profile confidence</small><strong>{{ data?.profile_health?.completeness || 0 }}%</strong></div><i>{{ data?.profile_health?.unverified_count || 0 }} facts to verify</i></a>
      </div>

      <div class="today-grid">
        <section class="panel focus-panel">
          <div class="panel-head"><div><p class="eyebrow">Priority queue</p><h2>The roles worth your attention</h2><p>Already filtered for fit, freshness, and your stated constraints.</p></div><a class="text-link" routerLink="/matches">Review all →</a></div>
          <a class="focus-job" *ngFor="let job of data?.review_queue; let first = first" routerLink="/matches" [class.lead-job]="first">
            <div class="company-mark">{{ initials(job.company) }}</div>
            <div class="focus-main"><div><strong>{{ job.title }}</strong><span>{{ job.company || 'Unknown company' }} · {{ job.location || job.remote_policy }}</span></div><p>{{ job.summary }}</p><div><span class="status-chip" title="Checks your saved must-have conditions, such as work authorization, location and work mode. Open the opportunity for reasons; this is not an employer rejection." [class.good]="job.eligibility === 'pass'">{{ job.eligibility === 'pass' ? 'Meets required conditions' : job.eligibility === 'fail' ? 'Required condition mismatch' : 'Needs confirmation' }}</span><span class="status-chip">{{ job.confidence }} confidence</span></div></div>
            <div class="focus-score"><strong>{{ job.score }}</strong><small>fit</small><span>→</span></div>
          </a>
          <div class="quiet-state" *ngIf="!data?.review_queue?.length"><span>◇</span><strong>Your opportunity queue is empty</strong><p>Run a configured source or import a job description to start ranking roles.</p><a class="btn-primary" routerLink="/sources">Open sources</a></div>
        </section>

        <aside class="today-rail">
          <section class="panel profile-pulse">
            <div class="panel-head"><div><p class="eyebrow">Candidate intelligence</p><h2>Profile pulse</h2></div><strong class="ring" [style.--progress]="data?.profile_health?.completeness || 0">{{ data?.profile_health?.completeness || 0 }}%</strong></div>
            <div class="profile-question" *ngFor="let question of data?.profile_health?.questions"><span>?</span><p><small>High-value question</small><strong>{{ question }}</strong></p></div>
            <a class="text-link" routerLink="/profile">Strengthen your profile →</a>
          </section>

          <section class="panel action-due">
            <div class="panel-head"><div><p class="eyebrow">Keep momentum</p><h2>Due actions</h2></div></div>
            <a class="due-row" *ngFor="let action of data?.due_actions" routerLink="/pipeline"><span>↗</span><div><strong>{{ action.title }}</strong><small>{{ action.detail }} · {{ action.due_at | date:'MMM d' }}</small></div></a>
            <div class="quiet-state compact" *ngIf="!data?.due_actions?.length"><span>✓</span><strong>Nothing overdue</strong><p>Your pipeline is current.</p></div>
          </section>
        </aside>
      </div>
    </section>
  `,
})
export class DashboardComponent implements OnInit {
  data: any;
  todayLabel = new Intl.DateTimeFormat(undefined, { weekday: 'long' }).format(new Date());
  constructor(private api: ApiService) {}
  ngOnInit(): void { this.api.today().subscribe((data) => this.data = data); }
  initials(company: string): string { return (company || 'F').split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase(); }
}
