import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { ApiService } from '../services/api.service';

@Component({
  selector: 'app-document-design', standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="document-design-layout">
      <section class="panel">
        <div class="panel-head"><div><p class="eyebrow">Your document defaults</p><h2>Set your style once</h2><p>Every new resume and cover letter will use your saved appearance, including documents prepared automatically.</p></div></div>
        <p *ngIf="loading" role="status">Loading your document settings…</p>
        <p *ngIf="loadError" role="alert">Could not load your settings. <button type="button" class="btn-secondary" (click)="load()">Try again</button></p>
        <form *ngIf="design" #form="ngForm" (ngSubmit)="save()">
          <fieldset [disabled]="saving">
            <legend class="sr-only">Document appearance</legend>
            <div class="edit-grid">
              <label>Style<select name="template" [(ngModel)]="design.template" (ngModelChange)="changed()"><option value="modern">Modern</option><option value="minimal">Minimal</option><option value="classic">Classic</option></select></label>
              <label>Resume layout<select name="layout" [(ngModel)]="design.layout" (ngModelChange)="changed()"><option value="single">Single column</option><option value="two_column">Two columns</option></select></label>
              <label>Font<select name="font" [(ngModel)]="design.font" (ngModelChange)="changed()"><option value="sans">Clean sans</option><option value="humanist">Humanist sans</option><option value="serif">Classic serif</option></select></label>
              <label>Spacing<select name="density" [(ngModel)]="design.density" (ngModelChange)="changed()"><option value="compact">Compact</option><option value="balanced">Balanced</option><option value="spacious">Spacious</option></select></label>
              <label>Accent color<span class="color-control"><input type="color" name="accent" [(ngModel)]="design.accent" (ngModelChange)="changed()"><span>{{ design.accent }}</span></span></label>
              <label>Paper size<select name="paper" [(ngModel)]="design.page_size" (ngModelChange)="changed()"><option value="Letter">Letter</option><option value="A4">A4</option></select></label>
              <label>Resume page limit<select name="pages" [(ngModel)]="design.max_pages" (ngModelChange)="changed()"><option [ngValue]="0">Automatic</option><option [ngValue]="1">One page</option><option [ngValue]="2">Two pages</option><option [ngValue]="3">Three pages</option></select></label>
            </div>
            <p class="field-hint">Cover letters use one column. Page limits apply to resumes; content is never cut off to fit.</p>
            <label>Default writing instructions<textarea name="instructions" rows="5" maxlength="6000" [(ngModel)]="instructions" (ngModelChange)="dirty = true; message = ''" placeholder="Use concise bullets and a warm, direct tone."></textarea></label>
            <p class="field-hint">Job-specific writing instructions can override this text. The appearance controls above always take priority.</p>
            <div class="action-row form-actions"><button class="btn-primary" type="submit" [disabled]="saving || form.invalid">{{ saving ? 'Saving…' : 'Save document defaults' }}</button><span class="field-hint" *ngIf="dirty">Unsaved changes</span></div>
          </fieldset>
          <p class="feedback-banner" *ngIf="message" role="status">{{ message }}</p>
          <p *ngIf="error" role="alert">{{ error }}</p>
          <p class="field-hint">Existing document versions keep their saved design. Prepare a new version to apply these defaults.</p>
        </form>
      </section>
      <section class="panel design-preview-panel" aria-label="Style preview">
        <div class="panel-head"><div><h2>Style preview</h2><p>Sample content · uses the same fonts and styling as your PDF.</p></div><span class="status-chip" *ngIf="previewing">Updating…</span></div>
        <p *ngIf="previewError" role="alert">Preview could not be loaded. <button class="btn-secondary" type="button" (click)="preview()">Retry preview</button></p>
        <iframe *ngIf="html" title="Document style preview" sandbox="" [srcdoc]="html"></iframe>
      </section>
    </div>
  `,
  styles: [`
    :host { display:block; } :host([hidden]) { display:none; } .document-design-layout { display:grid; grid-template-columns:minmax(320px, .9fr) minmax(0, 1.1fr); gap:24px; align-items:start; }
    .form-actions { margin:20px 0 16px; } fieldset { border:0; padding:0; margin:0; min-width:0; } legend { position:absolute; width:1px; height:1px; overflow:hidden; clip-path:inset(50%); }
    .color-control { display:flex; align-items:center; gap:12px; min-height:44px; font-weight:400; } input[type=color] { width:64px; height:44px; padding:4px; margin:0; }
    iframe { display:block; width:100%; height:760px; border:1px solid var(--line); border-radius:8px; background:white; } .design-preview-panel { overflow:hidden; }
    @media(max-width:1100px) { .document-design-layout { grid-template-columns:1fr; } }
  `],
})
export class DocumentDesignComponent implements OnInit, OnDestroy {
  design: any; instructions = ''; loading = false; loadError = false;
  saving = false; dirty = false; message = ''; error = '';
  html?: SafeHtml; previewing = false; previewError = false;
  private revision = 0; private timer?: ReturnType<typeof setTimeout>;
  constructor(private api: ApiService, private sanitizer: DomSanitizer) {}
  ngOnInit(): void { this.load(); }
  ngOnDestroy(): void { clearTimeout(this.timer); this.revision++; }
  load(): void {
    this.loading = true; this.loadError = false;
    this.api.accountSettings().subscribe({next: data => {
      this.design = data.document_design; this.instructions = data.generation_instructions;
      this.loading = false; this.preview();
    }, error: () => { this.loading = false; this.loadError = true; }});
  }
  changed(): void {
    this.dirty = true; this.message = ''; this.revision++;
    clearTimeout(this.timer); this.timer = setTimeout(() => this.preview(), 200);
  }
  preview(): void {
    if (!this.design) return;
    const revision = ++this.revision;
    this.previewing = true; this.previewError = false;
    this.api.previewDocumentDesign({...this.design}).subscribe({next: result => {
      if (revision !== this.revision) return;
      this.html = this.sanitizer.bypassSecurityTrustHtml(result.html); this.previewing = false;
    }, error: () => { if (revision === this.revision) { this.previewing = false; this.previewError = true; } }});
  }
  save(): void {
    if (!this.design || this.saving) return;
    this.saving = true; this.message = ''; this.error = '';
    this.api.saveAccountSettings({document_design: {...this.design}, generation_instructions: this.instructions}).subscribe({next: () => {
      this.saving = false; this.dirty = false; this.message = 'Saved. All future resumes and cover letters will use these defaults.';
    }, error: () => { this.saving = false; this.error = 'Could not save your defaults. Your changes are still here; please try again.'; }});
  }
}
