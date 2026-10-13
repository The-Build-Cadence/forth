import { CommonModule } from '@angular/common';
import { Component, Input, OnChanges } from '@angular/core';
import { MatchSignal } from '../services/api.service';

interface RadarAxis {
  signal: MatchSignal;
  label: string;
  x: number;
  y: number;
  labelX: number;
  labelY: number;
  pointX: number;
  pointY: number;
  anchor: 'start' | 'middle' | 'end';
}

const DIMENSIONS = ['skills', 'evidence', 'semantic', 'direction', 'domain', 'logistics'];
const LABELS: Record<string, string> = {
  skills: 'Skills', evidence: 'Evidence', semantic: 'Profile fit',
  direction: 'Direction', domain: 'Domain', logistics: 'Logistics',
};

@Component({
  selector: 'app-match-radar',
  standalone: true,
  imports: [CommonModule],
  template: `
    <figure class="match-radar">
      <figcaption>
        <strong>Match dimensions</strong>
        <p>Each axis runs from 0 to 100. Weights affect the overall match score, not the shape.</p>
      </figcaption>
      <ng-container *ngIf="axes.length >= 3; else unavailable">
        <svg viewBox="0 0 360 320" role="group" [attr.aria-label]="'Match dimension spider chart for ' + jobTitle">
          <title>Match dimensions for {{ jobTitle }}</title>
          <desc>{{ accessibleSummary }}. Select an axis for its explanation and weight.</desc>
          <g aria-hidden="true">
            <polygon *ngFor="let ring of rings" [attr.points]="ring" class="radar-grid" />
            <line *ngFor="let axis of axes" x1="180" y1="156" [attr.x2]="axis.x" [attr.y2]="axis.y" class="radar-spoke" />
            <text *ngFor="let level of levels" x="184" [attr.y]="156 - radius * level / 100 - 3" class="radar-scale">{{ level }}</text>
            <polygon [attr.points]="polygon" class="radar-area" />
          </g>
          <g *ngFor="let axis of axes; let i = index" class="radar-axis" [class.active]="activeIndex === i"
             tabindex="0" role="button" [attr.aria-pressed]="activeIndex === i"
             [attr.aria-label]="axis.signal.label + ': ' + axis.signal.score + ' out of 100, ' + axis.signal.weight + '% weight'"
             (mouseenter)="activeIndex = i" (focus)="activeIndex = i" (click)="activeIndex = i"
             (keydown.enter)="activeIndex = i" (keydown.space)="$event.preventDefault(); activeIndex = i">
            <title>{{ axis.signal.label }}: {{ axis.signal.score }}/100 · {{ axis.signal.weight }}% weight</title>
            <circle [attr.cx]="axis.pointX" [attr.cy]="axis.pointY" r="4" class="radar-point" />
            <rect [attr.x]="axis.labelX - (axis.anchor === 'end' ? 74 : axis.anchor === 'middle' ? 37 : 0) - 5"
                  [attr.y]="axis.labelY - 15" width="84" height="43" rx="7" class="radar-hit" />
            <text [attr.x]="axis.labelX" [attr.y]="axis.labelY" [attr.text-anchor]="axis.anchor" class="radar-label">
              {{ axis.label }}
              <tspan [attr.x]="axis.labelX" dy="16" class="radar-value">{{ axis.signal.score }}</tspan>
            </text>
          </g>
        </svg>
        <p class="radar-hint">Hover, tap, or focus an axis to explore.</p>
        <div class="radar-detail" *ngIf="axes[activeIndex] as active" aria-live="polite" aria-atomic="true">
          <div><strong>{{ active.signal.label }}</strong><span>{{ active.signal.score }}/100 · {{ active.signal.weight }}% weight</span></div>
          <p>{{ active.signal.explanation || 'No explanation is available for this dimension yet.' }}</p>
        </div>
      </ng-container>
      <ng-template #unavailable><p class="radar-empty">At least three scored dimensions are needed for the spider chart. Recompute this match to load its analysis.</p></ng-template>
      <p class="radar-missing" *ngIf="omittedCount">{{ omittedCount }} unavailable {{ omittedCount === 1 ? 'dimension is' : 'dimensions are' }} omitted, not scored as zero.</p>
    </figure>
  `,
  styles: [`
    :host { display: block; min-width: 0; }
    .match-radar { margin: 0 0 22px; padding: 18px; border: 1px solid var(--line); border-radius: 14px; background: #f7faf8; }
    figcaption strong { font-size: .9rem; }
    figcaption p, .radar-empty, .radar-missing { margin: 5px 0 0; color: var(--muted); font-size: .76rem; line-height: 1.5; }
    svg { display: block; width: 100%; max-width: 440px; margin: 8px auto 0; overflow: visible; }
    .radar-grid { fill: none; stroke: #cddcd5; stroke-width: 1; }
    .radar-spoke { stroke: #dbe5df; stroke-width: 1; }
    .radar-scale { fill: #61746b; font: 9px sans-serif; }
    .radar-area { fill: #177d6929; stroke: #177d69; stroke-width: 2; stroke-linejoin: round; }
    .radar-point { fill: #177d69; stroke: #fff; stroke-width: 1.5; }
    .radar-axis { cursor: pointer; outline: none; }
    .radar-hit { fill: transparent; stroke: transparent; }
    .radar-axis:focus-visible .radar-hit { fill: #e4f3ed; stroke: #177d69; stroke-width: 2; }
    .radar-axis.active .radar-point { fill: #0c4d40; stroke-width: 2; r: 5px; }
    .radar-label { fill: #354c43; font: 12px sans-serif; }
    .radar-value { fill: #116650; font-weight: 700; }
    .radar-hint { margin: 0 0 12px; text-align: center; color: var(--muted); font-size: .7rem; }
    .radar-detail { padding: 12px 14px; border: 1px solid #d6e5dd; border-radius: 9px; background: #fff; }
    .radar-detail > div { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 5px 14px; font-size: .78rem; }
    .radar-detail span { color: #116650; white-space: nowrap; }
    .radar-detail p { margin: 6px 0 0; color: var(--muted); font-size: .76rem; line-height: 1.5; }
    .radar-missing { margin-top: 10px; }
    @media (max-width: 500px) { .match-radar { padding: 12px; } }
  `],
})
export class MatchRadarComponent implements OnChanges {
  @Input() signals: MatchSignal[] | null | undefined = [];
  @Input() jobTitle = 'selected opportunity';
  readonly radius = 88;
  readonly levels = [25, 50, 75, 100];
  axes: RadarAxis[] = [];
  rings: string[] = [];
  polygon = '';
  accessibleSummary = '';
  activeIndex = 0;
  omittedCount = 0;

  ngOnChanges(): void {
    const supplied = this.signals || [];
    const valid = supplied.filter(signal => typeof signal.score === 'number' && Number.isFinite(signal.score) && signal.score >= 0 && signal.score <= 100);
    const order = (kind: string) => DIMENSIONS.includes(kind) ? DIMENSIONS.indexOf(kind) : DIMENSIONS.length;
    const sorted = [...valid].sort((a, b) => order(a.kind) - order(b.kind) || a.kind.localeCompare(b.kind));
    this.omittedCount = DIMENSIONS.filter(kind => !valid.some(signal => signal.kind === kind)).length
      + supplied.filter(signal => !DIMENSIONS.includes(signal.kind) && !valid.includes(signal)).length;
    this.activeIndex = 0;
    this.axes = sorted.map((signal, index) => {
      const angle = -Math.PI / 2 + index * 2 * Math.PI / sorted.length;
      const cos = Math.cos(angle), sin = Math.sin(angle);
      return {
        signal, label: LABELS[signal.kind] || (signal.label.length > 12 ? signal.label.slice(0, 11) + '…' : signal.label),
        x: 180 + this.radius * cos, y: 156 + this.radius * sin,
        labelX: Math.max(84, Math.min(276, 180 + 116 * cos)), labelY: 156 + 116 * sin - 4,
        pointX: 180 + this.radius * signal.score / 100 * cos,
        pointY: 156 + this.radius * signal.score / 100 * sin,
        anchor: cos > .2 ? 'start' : cos < -.2 ? 'end' : 'middle',
      };
    });
    this.rings = this.levels.map(level => this.axes.map(axis => `${180 + (axis.x - 180) * level / 100},${156 + (axis.y - 156) * level / 100}`).join(' '));
    this.polygon = this.axes.map(axis => `${axis.pointX},${axis.pointY}`).join(' ');
    this.accessibleSummary = this.axes.map(axis => `${axis.signal.label}: ${axis.signal.score} out of 100`).join('; ');
  }
}
