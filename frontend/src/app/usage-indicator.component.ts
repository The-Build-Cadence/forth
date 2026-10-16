import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { EMPTY, Subscription, catchError, exhaustMap, timer, timeout } from 'rxjs';
import { ApiService, UsageSummary } from './services/api.service';

@Component({
  selector: 'app-usage-indicator',
  standalone: true,
  imports: [CommonModule],
  template: `
    <section class="usage-monitor" aria-label="Your API costs"
      [title]="error ? 'Costs unavailable. Retrying automatically.' : 'All-time estimated costs in USD. Excludes requests with unknown costs.'">
      <span class="usage-row"><span>AI</span><strong>{{ usage ? money(usage.providers.openai.cost_usd) : '—' }}</strong></span>
      <span class="usage-row"><span>Search</span><strong>{{ usage ? money(usage.providers.brave.cost_usd) : '—' }}</strong></span>
    </section>
  `,
  styles: [`
    :host { display: block; }
    .usage-monitor { margin: 12px 14px; font-size: 12px; }
    .usage-row { display: flex; justify-content: space-between; gap: 8px; margin: 6px 0; }
    .usage-row strong { font-variant-numeric: tabular-nums; }
  `],
})
export class UsageIndicatorComponent implements OnInit, OnDestroy {
  usage: UsageSummary | null = null;
  error = false;
  private subscription?: Subscription;
  constructor(private api: ApiService) {}
  ngOnInit(): void {
    this.subscription = timer(0, 15000).pipe(
      exhaustMap(() => this.api.usage().pipe(timeout(12000), catchError(() => {
        this.error = true;
        this.usage = null;
        return EMPTY;
      }))),
    ).subscribe(data => { this.usage = data?.providers?.openai && data?.providers?.brave ? data : null; this.error = !this.usage; });
  }
  ngOnDestroy(): void { this.subscription?.unsubscribe(); }
  money(value: string): string {
    const number = Number(value);
    return number > 0 && number < 0.0001 ? '<$0.0001' : '$' + number.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  }
}
