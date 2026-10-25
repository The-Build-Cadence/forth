import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterOutlet } from '@angular/router';
import { filter, Subscription } from 'rxjs';
import { AuthService } from './services/auth.service';
import { RealtimeService, RealtimeStatus } from './services/realtime.service';
import { ApiService } from './services/api.service';
import { UsageIndicatorComponent } from './usage-indicator.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, RouterOutlet, RouterLink, UsageIndicatorComponent],
  template: `
    <div class="app-shell" *ngIf="auth.hasSession(); else authOnly">
      <header class="mobile-header">
        <a class="mobile-brand" routerLink="/dashboard" (click)="closeNav()">
          <img class="brand-mark" src="/brand-mark.svg" alt="" width="40" height="40">
          <span>Forth</span>
        </a>
        <button class="menu-toggle" type="button" (click)="navOpen = !navOpen" [attr.aria-expanded]="navOpen" aria-label="Toggle navigation">
          <span></span><span></span><span></span>
        </button>
      </header>

      <button class="nav-backdrop" type="button" *ngIf="navOpen" (click)="closeNav()" aria-label="Close navigation"></button>

      <aside class="side-nav" [class.open]="navOpen">
        <div class="side-nav-head">
          <a class="brand" routerLink="/dashboard" (click)="closeNav()">
            <img class="brand-mark" src="/brand-mark.svg" alt="" width="40" height="40">
            <span class="brand-copy"><strong>Forth</strong><small>Your next move</small></span>
          </a>
          <button class="nav-close" type="button" (click)="closeNav()" aria-label="Close navigation">×</button>
        </div>

        <nav class="side-nav-main" aria-label="Primary">
          <span class="nav-section-label">Your search</span>
          <a routerLink="/dashboard" [class.active]="active('/dashboard')" [attr.aria-current]="active('/dashboard') ? 'page' : null" (click)="closeNav()"><span class="nav-icon" aria-hidden="true">⌂</span>Today</a>
          <a routerLink="/matches" [class.active]="active('/matches')" [attr.aria-current]="active('/matches') ? 'page' : null" (click)="closeNav()"><span class="nav-icon" aria-hidden="true">◇</span>Jobs</a>
          <a routerLink="/pipeline" [class.active]="active('/pipeline')" [attr.aria-current]="active('/pipeline') ? 'page' : null" (click)="closeNav()"><span class="nav-icon" aria-hidden="true">▦</span>Applications</a>

          <a routerLink="/profile" [class.active]="active('/profile')" [attr.aria-current]="active('/profile') ? 'page' : null" (click)="closeNav()"><span class="nav-icon" aria-hidden="true">◎</span>My Profile</a>
          <span class="nav-section-label nav-section-spaced">Tools</span>
          <a routerLink="/concierge" [class.active]="active('/concierge')" [attr.aria-current]="active('/concierge') ? 'page' : null" (click)="closeNav()"><span class="nav-icon" aria-hidden="true">✦</span>Ask Forth</a>
          <a routerLink="/resume-lab" [class.active]="active('/resume-lab')" [attr.aria-current]="active('/resume-lab') ? 'page' : null" (click)="closeNav()"><span class="nav-icon" aria-hidden="true">▤</span>Documents</a>
          <a routerLink="/sources" [class.active]="active('/sources')" [attr.aria-current]="active('/sources') ? 'page' : null" (click)="closeNav()"><span class="nav-icon" aria-hidden="true">⌁</span>Job search settings</a>
          <span class="nav-section-label nav-section-spaced">Account</span>
          <a routerLink="/settings" [class.active]="active('/settings')" [attr.aria-current]="active('/settings') ? 'page' : null" (click)="closeNav()"><span class="nav-icon" aria-hidden="true">⚙</span>Settings</a>
        </nav>

        <app-usage-indicator (selected)="closeNav()"></app-usage-indicator>

        <div class="side-nav-context">
          <div class="connection-row">
            <span class="socket-status" [class.connected]="socketStatus === 'connected'" [title]="socketStatus"><span></span></span>
            <div><strong>{{ socketStatus === 'connected' ? 'Live updates on' : socketStatus === 'connecting' ? 'Connecting' : 'Live updates off' }}</strong><small>{{ latestEvent }}</small></div>
          </div>
        </div>

        <button class="btn-secondary side-nav-logout" type="button" (click)="logout()"><span>↪</span> Sign out</button>
      </aside>

      <a class="skip-link" href="#main-content">Skip to content</a>
      <main class="app-main" id="main-content">
        <router-outlet></router-outlet>
      </main>

      <div class="global-work" *ngIf="activeWork.length" role="status" aria-live="polite">
        <span class="spinner" aria-hidden="true"></span>
        <div><strong>{{ activeWork[0] }}</strong><small>{{ activeWork.length > 1 ? (activeWork.length - 1) + ' more background task' + (activeWork.length > 2 ? 's' : '') + ' running' : 'You can keep using Forth while this finishes.' }}</small></div>
      </div>
    </div>

    <ng-template #authOnly>
      <router-outlet></router-outlet>
    </ng-template>
  `,
})
export class AppComponent implements OnInit, OnDestroy {
  currentPath = '/dashboard';
  socketStatus: RealtimeStatus = 'disconnected';
  latestEvent = 'No events yet';
  navOpen = false;
  activeWork: string[] = [];
  private work = new Map<string, string>();
  private navSub?: Subscription;
  private authSub?: Subscription;
  private statusSub?: Subscription;
  private eventsSub?: Subscription;

  constructor(
    public auth: AuthService,
    private router: Router,
    private realtime: RealtimeService,
    private api: ApiService,
  ) {}

  ngOnInit(): void {
    this.currentPath = this.router.url.split(/[?#]/)[0];
    this.authSub = this.auth.authed$.subscribe((authenticated) => {
      if (authenticated) {
        this.realtime.reconnect();
        this.checkOnboarding();
      } else {
        this.realtime.disconnect();
        this.work.clear();
        this.activeWork = [];
        this.latestEvent = '';
      }
    });
    this.navSub = this.router.events.pipe(filter((event) => event instanceof NavigationEnd)).subscribe((event) => {
      const nav = event as NavigationEnd;
      this.currentPath = (nav.urlAfterRedirects || nav.url).split(/[?#]/)[0];
      this.closeNav();
      if (this.auth.hasSession()) {
        this.realtime.connect();
      }
    });
    this.statusSub = this.realtime.status$.subscribe((status) => {
      this.socketStatus = status;
    });
    this.eventsSub = this.realtime.events$.subscribe((event) => {
      this.latestEvent = String(event.type || 'event').replaceAll('_', ' ');
      this.trackWork(event);
    });
  }

  ngOnDestroy(): void {
    this.navSub?.unsubscribe();
    this.authSub?.unsubscribe();
    this.statusSub?.unsubscribe();
    this.eventsSub?.unsubscribe();
  }

  active(path: string): boolean {
    if (path === '/matches' && this.currentPath.startsWith('/jobs/')) return true;
    return this.currentPath === path || this.currentPath.startsWith(`${path}/`);
  }

  closeNav(): void {
    this.navOpen = false;
  }

  logout(): void {
    this.auth.logout();
    this.realtime.disconnect();
    this.router.navigate(['/login']);
  }

  private checkOnboarding(): void {
    if (sessionStorage.getItem('forth_onboarding_dismissed') === '1') return;
    const session = this.auth.getRefreshToken();
    this.api.searchSetup().subscribe({
      next: (snapshot) => {
        if (this.auth.getRefreshToken() !== session) return;
        // Setup is a page, so users can leave, return and use browser navigation.
        // Existing users keep their current destination.
        if (!snapshot.profile) return;
        if (!snapshot.profile.onboarding_completed_at && !snapshot.profile.onboarding_state?.quick_start && !snapshot.profile.onboarding_state?.setup_draft && !snapshot.document && this.router.url === '/dashboard') this.router.navigate(['/start']);
      },
      error: () => { /* Dashboard offers a retry without blocking navigation. */ },
    });
  }

  private trackWork(event: any): void {
    const type = String(event.type || '');
    const data = event.data || event.payload || event;
    const definitions: Record<string, { key: string; label?: string; done?: boolean }> = {
      profile_ingestion_queued: { key: `profile:${data.document_id}`, label: 'Reading your profile source…' },
      profile_ingestion_started: { key: `profile:${data.document_id}`, label: 'Extracting candidate facts…' },
      profile_ingestion_finished: { key: `profile:${data.document_id}`, done: true },
      source_run_queued: { key: `source:${data.source_id}`, label: 'Refreshing a job source…' },
      source_run_started: { key: `source:${data.source_id}`, label: 'Finding and ranking fresh jobs…' },
      source_run_finished: { key: `source:${data.source_id}`, done: true },
      match_recompute_queued: { key: `match:${data.job_id}`, label: 'Queueing a new fit analysis…' },
      match_recompute_started: { key: `match:${data.job_id}`, label: 'Recomputing job fit…' },
      match_recomputed: { key: `match:${data.job_id}`, done: true },
      match_recompute_failed: { key: `match:${data.job_id}`, done: true },
      materials_regeneration_queued: { key: `materials:${data.job_id}`, label: 'Queueing fresh application materials…' },
      materials_regeneration_started: { key: `materials:${data.job_id}`, label: 'Regenerating resume and cover letter…' },
      materials_regenerated: { key: `materials:${data.job_id}`, done: true },
      materials_regeneration_failed: { key: `materials:${data.job_id}`, done: true },
      agent_run_queued: { key: `agent:${data.run_id}`, label: 'A specialist is queued…' },
      agent_run_started: { key: `agent:${data.run_id}`, label: 'A specialist is working…' },
    };
    const definition = definitions[type];
    if (definition) {
      if (definition.done) this.work.delete(definition.key);
      else this.work.set(definition.key, definition.label || 'Working…');
    }
    if (type === 'agent_run_updated' && ['succeeded', 'failed', 'cancelled', 'waiting_approval'].includes(String(data.status))) {
      this.work.delete(`agent:${data.run_id}`);
    }
    this.activeWork = Array.from(this.work.values());
  }
}
