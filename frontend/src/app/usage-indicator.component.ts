import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, OnDestroy, OnInit, Output } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';
import { UsageSummary } from './services/api.service';
import { UsageService } from './services/usage.service';

@Component({
  selector: 'app-usage-indicator',
  standalone: true,
  imports: [CommonModule, RouterLink],
  template: `
    <a *ngIf="!detailed; else breakdown" class="usage-link" routerLink="/settings" fragment="api-costs" (click)="openDetails()"
      [title]="error ? 'Costs unavailable. Retrying automatically.' : 'All-time estimated costs in USD. View the breakdown in Settings.'">
      <span>API costs</span><strong>{{ usage ? money(total) : '—' }}</strong><span aria-hidden="true">↗</span>
    </a>
    <ng-template #breakdown>
      <section class="usage-panel panel" id="api-costs" aria-label="API cost breakdown">
        <header><div><h2>Your API costs</h2><p>All-time estimates · USD</p></div><strong class="grand-total">{{ usage ? money(total) : '—' }}</strong></header>
        <div class="cost-grid" *ngIf="usage as data">
          <div class="cost-item"><span>AI · OpenAI</span><strong>{{ money(data.providers.openai.cost_usd) }}</strong><small>{{ data.providers.openai.requests }} requests · {{ money(data.providers.openai.month_cost_usd) }} this month</small></div>
          <div class="cost-item"><span>Search · Brave</span><strong>{{ money(data.providers.brave.cost_usd) }}</strong><small>{{ data.providers.brave.requests }} requests · {{ money(data.providers.brave.month_cost_usd) }} this month</small></div>
          <div class="cost-item"><span>This month · UTC</span><strong>{{ money(monthTotal) }}</strong><small>{{ data.providers.openai.month_requests + data.providers.brave.month_requests }} requests</small></div>
        </div>
        <p *ngIf="error" role="status">Costs unavailable. Retrying automatically.</p>
        <p *ngIf="!usage && !error" role="status">Loading costs…</p>
        <p *ngIf="unknown" class="cost-notice">{{ unknown }} requests have pending or unknown costs and are excluded from these totals.</p>
        <footer *ngIf="usage">Includes generation, embeddings, and background tasks. Before provider credits and taxes. Earlier usage before tracking is unavailable.</footer>
      </section>
    </ng-template>
  `,
  styles: [`
    :host { display: block; }
    .usage-link { display: flex; align-items: center; gap: 8px; margin: 12px 14px; padding: 6px 0; font-size: 12px; color: inherit; text-decoration: none; }
    .usage-link strong { margin-left: auto; font-variant-numeric: tabular-nums; }
    .usage-link:hover { color: #c9f45a; }
    .usage-link:focus-visible { outline: 2px solid currentColor; outline-offset: 4px; }
    .usage-panel { padding: 22px; margin-bottom: 24px; scroll-margin-top: 80px; }
    header { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
    h2 { margin: 0; font-size: 18px; }
    header p { margin: 4px 0 0; font-size: 12px; color: #60747c; }
    .grand-total { font-size: 26px; font-variant-numeric: tabular-nums; }
    .cost-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px; margin: 20px 0 16px; }
    .cost-item { display: flex; flex-direction: column; gap: 5px; font-size: 13px; }
    .cost-item strong { font-size: 20px; font-variant-numeric: tabular-nums; }
    .cost-item small, footer { color: #60747c; font-size: 12px; line-height: 1.5; }
    .cost-notice { color: #8b4b13; font-size: 12px; }
    @media (max-width: 600px) { .cost-grid { grid-template-columns: 1fr; gap: 14px; } .usage-panel { padding: 18px; } }
  `],
})
export class UsageIndicatorComponent implements OnInit, OnDestroy {
  @Input() detailed = false;
  @Output() selected = new EventEmitter<void>();
  usage: UsageSummary | null = null;
  error = false;
  private subscription?: Subscription;
  constructor(private costs: UsageService) {}
  ngOnInit(): void {
    this.subscription = this.costs.state$.subscribe(state => { this.usage = state.usage; this.error = state.error; });
  }
  openDetails(): void {
    this.selected.emit();
    document.getElementById('api-costs')?.scrollIntoView({ block: 'start' });
  }
  ngOnDestroy(): void { this.subscription?.unsubscribe(); }
  get total(): number { return Number(this.usage?.providers.openai.cost_usd || 0) + Number(this.usage?.providers.brave.cost_usd || 0); }
  get monthTotal(): number { return Number(this.usage?.providers.openai.month_cost_usd || 0) + Number(this.usage?.providers.brave.month_cost_usd || 0); }
  get unknown(): number { return (this.usage?.providers.openai.unknown_cost_requests || 0) + (this.usage?.providers.brave.unknown_cost_requests || 0); }
  money(value: string | number): string {
    const number = Number(value);
    return number > 0 && number < 0.0001 ? '<$0.0001' : '$' + number.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  }
}
