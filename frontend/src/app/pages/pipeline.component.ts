import { CommonModule } from '@angular/common';
import { Component, HostListener, NgZone, OnDestroy, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { timeout } from 'rxjs';
import { ApiService, ApplicationRecord } from '../services/api.service';
import { applicationStage, applicationStages } from '../services/application-journey';

interface StatusDef {
  key: string;
  label: string;
}

@Component({
  standalone: true,
  imports: [CommonModule],
  template: `
    <section class="page">
      <div class="page-head">
        <div>
          <p class="eyebrow">My applications</p>
          <h1>Your saved jobs and applications.</h1>
          <p class="page-intro">Open a job to prepare documents, review them and track your next step. Saved jobs have not been submitted.</p>
        </div>
        <button class="btn-secondary" type="button" (click)="load()">↻ Refresh</button>
      </div>

      <div class="board-toolbar"><div><strong>{{ totalApplications }} opportunities</strong><span>Select a job to open its workspace · drag to update progress</span></div><span class="status-chip good">● Live pipeline</span></div>
      <section class="pipeline-board" [class.is-dragging]="draggedApplicationId !== null" aria-label="Application pipeline">
        <div class="pipeline-col" *ngFor="let status of statuses" [class.drop-target]="dropTargetStatus === status.key" [attr.data-pipeline-status]="status.key">
          <div class="pipeline-col-head"><h2>{{ status.label }}</h2><span>{{ byStatus(status.key).length }}</span></div>
          <button class="application-card" type="button" *ngFor="let app of byStatus(status.key); trackBy: applicationId" [class.selected]="selected?.id === app.id" [class.dragging]="draggedApplicationId === app.id" draggable="false" (dragstart)="$event.preventDefault()" (pointerdown)="startDrag($event, app)" (pointermove)="moveDrag($event)" (pointerup)="finishDrag($event)" (pointercancel)="cancelDrag()" (lostpointercapture)="cancelDrag()" (click)="select(app)" [disabled]="loadingApplicationId === app.id">
            <span class="card-drag-handle" aria-hidden="true" title="Drag to move this application">⠿</span>
            <strong>{{ app.job_detail.title }}</strong>
            <p>{{ app.job_detail.company || 'Unknown company' }} · {{ app.job_detail.location || app.job_detail.remote_policy }}</p>
            <div class="card-chip-row"><span class="status-chip" [class.good]="app.job_detail.match?.meets_profile_threshold">{{ app.job_detail.match?.normalized_score || 0 }} calibrated · {{ app.job_detail.match?.score || 0 }} raw</span><span class="status-chip" [class.good]="app.job_detail.match?.hard_filter_status === 'pass'">{{ app.job_detail.match?.hard_filter_status || 'unreviewed' }}</span></div>
            <p *ngIf="app.follow_up_at && isFollowUpDue(app)" class="status-chip warn">Follow-up due</p><div class="application-card-footer"><span>{{ app.resume_title ? 'Documents available' : 'Documents not created' }}</span><span>{{ app.artifact_count || 0 }} files · {{ app.updated_at | date:'MMM d' }} →</span></div>
          </button>
          <div class="column-empty" *ngIf="!byStatus(status.key).length">No applications</div>
        </div>
      </section>
      <div class="application-drag-preview" *ngIf="draggedApplicationId !== null" aria-hidden="true" [style.left.px]="dragX + 14" [style.top.px]="dragY + 14">{{ dragTitle }}<small>Release over a stage · Esc to cancel</small></div>
      <p class="board-status" role="status" aria-live="polite">{{ boardMessage }}</p>
      <nav class="pagination" *ngIf="pageCount > 1" aria-label="Application pages">
        <button class="btn-secondary" type="button" (click)="goToPage(currentPage - 1)" [disabled]="currentPage === 1">← Newer</button>
        <span>Page {{ currentPage }} of {{ pageCount }}</span>
        <button class="btn-secondary" type="button" (click)="goToPage(currentPage + 1)" [disabled]="currentPage === pageCount">Older →</button>
      </nav>

    </section>
  `,
})
export class PipelineComponent implements OnInit, OnDestroy {
  applications: ApplicationRecord[] = [];
  totalApplications = 0;
  currentPage = 1;
  readonly pageSize = 40;
  selected?: ApplicationRecord;
  loadingApplicationId: number | null = null;
  draggedApplicationId: number | null = null;
  dropTargetStatus: string | null = null;
  boardMessage = '';
  private ignoreNextCardClick = false;
  private clickReset?: ReturnType<typeof setTimeout>;
  private dragFrame?: number;
  private cancelledPointerId?: number;
  private pointerDrag?: { pointerId: number; application: ApplicationRecord; element: HTMLElement; startX: number; startY: number };
  dragX = 0;
  dragY = 0;
  dragTitle = '';

  applicationId(_index: number, app: ApplicationRecord): number { return app.id; }

  ngOnDestroy(): void { this.resetDrag(); clearTimeout(this.clickReset); }

  statuses: StatusDef[] = applicationStages;

  constructor(private api: ApiService, private route: ActivatedRoute, private zone: NgZone, private router: Router) {}

  ngOnInit(): void {
    this.load();
    this.route.queryParamMap.subscribe((params) => {
      const applicationId = Number(params.get('application'));
      if (applicationId) this.openApplication(applicationId);
    });
  }

  load(): void {
    this.api.applications({ page: String(this.currentPage) }).subscribe((page) => {
      this.applications = page.results;
      this.totalApplications = page.count;
    });
  }

  get pageCount(): number { return Math.max(1, Math.ceil(this.totalApplications / this.pageSize)); }

  goToPage(page: number): void {
    if (page < 1 || page > this.pageCount || page === this.currentPage) return;
    this.currentPage = page;
    this.selected = undefined;
    this.load();
  }

  byStatus(status: string): ApplicationRecord[] {
    return this.applications.filter((app) => applicationStage(app.status) === status);
  }

  select(application: ApplicationRecord): void {
    if (this.ignoreNextCardClick) {
      this.ignoreNextCardClick = false;
      return;
    }
    this.openApplication(application.id);
  }

  openApplication(applicationId: number): void {
    if (this.loadingApplicationId) return;
    this.loadingApplicationId = applicationId;
    this.api.application(applicationId).subscribe({
      next: detail => { this.loadingApplicationId = null; void this.router.navigate(['/jobs', detail.job]); },
      error: () => { this.boardMessage = 'Could not open this job. Please try again.'; this.loadingApplicationId = null; },
    });
  }

  isFollowUpDue(application: ApplicationRecord): boolean {
    return applicationStage(application.status) !== 'archived' && !!application.follow_up_at && Date.parse(application.follow_up_at) <= Date.now();
  }

  startDrag(event: PointerEvent, application: ApplicationRecord): void {
    if (!event.isPrimary || event.button !== 0 || this.loadingApplicationId || this.pointerDrag) return;
    // Touch users can still scroll the board from the card body.
    if (event.pointerType === 'touch' && !(event.target as Element).closest('.card-drag-handle')) return;
    this.cancelledPointerId = undefined;
    const element = event.currentTarget as HTMLElement;
    this.pointerDrag = { pointerId: event.pointerId, application, element, startX: event.clientX, startY: event.clientY };
    this.dragX = event.clientX;
    this.dragY = event.clientY;
    element.setPointerCapture(event.pointerId);
  }

  moveDrag(event: PointerEvent): void {
    const drag = this.pointerDrag;
    if (!drag || event.pointerId !== drag.pointerId) return;
    this.dragX = event.clientX;
    this.dragY = event.clientY;
    if (this.draggedApplicationId === null) {
      if (Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < 6) return;
      this.draggedApplicationId = drag.application.id;
      this.dragTitle = drag.application.job_detail.title;
      this.boardMessage = `Moving ${this.dragTitle}. Release over a stage, or press Escape to cancel.`;
      this.zone.runOutsideAngular(() => { this.dragFrame = requestAnimationFrame(() => this.scrollDuringDrag()); });
    }
    event.preventDefault();
    this.updateDropTarget();
  }

  private updateDropTarget(): void {
    const column = document.elementFromPoint(this.dragX, this.dragY)?.closest('[data-pipeline-status]');
    this.dropTargetStatus = column?.getAttribute('data-pipeline-status') || null;
  }

  private scrollDuringDrag(): void {
    if (this.draggedApplicationId === null) return;
    const edge = 70;
    const delta = this.dragY < edge ? -Math.min(18, (edge - this.dragY) / 3)
      : this.dragY > window.innerHeight - edge ? Math.min(18, (this.dragY - window.innerHeight + edge) / 3) : 0;
    if (delta) {
      const previousY = window.scrollY;
      window.scrollBy({ top: delta, behavior: 'instant' });
      if (window.scrollY !== previousY) this.zone.run(() => this.updateDropTarget());
    }
    this.dragFrame = requestAnimationFrame(() => this.scrollDuringDrag());
  }

  finishDrag(event: PointerEvent): void {
    if (event.pointerId === this.cancelledPointerId) {
      this.cancelledPointerId = undefined;
      this.suppressReleaseClick();
      return;
    }
    const drag = this.pointerDrag;
    if (!drag || event.pointerId !== drag.pointerId) return;
    const moved = this.draggedApplicationId !== null;
    this.dragX = event.clientX;
    this.dragY = event.clientY;
    this.updateDropTarget();
    const target = this.dropTargetStatus;
    this.resetDrag();
    if (!moved) return;
    event.preventDefault();
    this.suppressReleaseClick();
    if (!target || target === applicationStage(drag.application.status)) {
      this.boardMessage = 'Application stayed in its original stage.';
      return;
    }
    this.moveApplication(drag.application, target);
  }

  @HostListener('window:blur')
  @HostListener('document:keydown.escape')
  cancelDrag(): void {
    const moved = this.draggedApplicationId !== null;
    if (moved) this.cancelledPointerId = this.pointerDrag?.pointerId;
    this.resetDrag();
    if (moved) {
      this.suppressReleaseClick();
      this.boardMessage = 'Move cancelled. Application stayed in its original stage.';
    }
  }

  private suppressReleaseClick(): void {
    // Suppress only the click synthesized by this pointer release, not the next user click.
    this.ignoreNextCardClick = true;
    clearTimeout(this.clickReset);
    this.clickReset = setTimeout(() => { this.ignoreNextCardClick = false; }, 0);
  }

  private resetDrag(): void {
    const drag = this.pointerDrag;
    this.pointerDrag = undefined;
    this.draggedApplicationId = null;
    this.dropTargetStatus = null;
    if (this.dragFrame !== undefined) cancelAnimationFrame(this.dragFrame);
    this.dragFrame = undefined;
    if (drag?.element.hasPointerCapture(drag.pointerId)) drag.element.releasePointerCapture(drag.pointerId);
  }

  private moveApplication(application: ApplicationRecord, targetStatus: string): void {
    if (this.loadingApplicationId || !this.statuses.some(status => status.key === targetStatus)) return;
    if (targetStatus === 'applied' && !application.applied_at) {
      void this.router.navigate(['/jobs', application.job], {queryParams: {tab: 'tracking'}});
      this.boardMessage = 'Record the submission date in the job workspace.';
      return;
    }
    const previousStatus = application.status;
    application.status = targetStatus;
    this.loadingApplicationId = application.id;
    this.boardMessage = `Updating ${application.job_detail.title}…`;
    this.api.updateApplication(application.id, { status: targetStatus }).pipe(timeout(15000)).subscribe({
      next: (updated) => {
        Object.assign(application, updated, { artifact_count: application.artifact_count });
        if (this.selected?.id === application.id) this.selected.status = updated.status;
        this.loadingApplicationId = null;
        const label = this.statuses.find((status) => status.key === targetStatus)?.label || targetStatus;
        this.boardMessage = `${application.job_detail.title} moved to ${label}.`;
      },
      error: (error) => {
        application.status = previousStatus;
        this.loadingApplicationId = null;
        this.boardMessage = error?.name === 'TimeoutError' ? 'Saving took too long. Refresh the board to check the saved stage before retrying.'
          : error?.error?.status?.[0] || error?.error?.detail || 'Could not update the application status. Please try again.';
      },
    });
  }

}
