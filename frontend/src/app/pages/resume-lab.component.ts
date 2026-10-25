import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, OnInit, Output, ViewEncapsulation } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { FormsModule } from '@angular/forms';
import { ApiService, CoverLetter, JobPosting, Resume, ResumeContact } from '../services/api.service';

interface ResumeDesign {
  template: 'modern' | 'classic' | 'minimal';
  density: 'compact' | 'balanced' | 'spacious';
  accent: string;
  page_size: 'Letter' | 'A4';
  rationale: string;
  layout: 'single' | 'two_column';
  font: 'sans' | 'humanist' | 'serif';
  max_pages: number;
}

@Component({
  selector: 'app-job-documents',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  styleUrl: './resume-lab.component.css',
  encapsulation: ViewEncapsulation.None,
  template: `
    <section class="page resume-studio-page">
      <div class="page-head resume-studio-head" *ngIf="!embeddedJobId">
        <div>
          <p class="eyebrow">AI application materials</p>
          <h1>Document library</h1>
          <p class="page-intro">Browse your document versions and manage your source resume and contact details. Prepare new documents from a job workspace.</p>
        </div>
        <a class="btn-primary" routerLink="/matches">Choose a job to prepare</a>
      </div>

      <div class="tabs" role="tablist" aria-label="Document library sections" *ngIf="!embeddedJobId">
        <button type="button" role="tab" [class.active]="activeTab === 'create'" [attr.aria-selected]="activeTab === 'create'" (click)="activeTab = 'create'">Source resume</button>
        <button type="button" role="tab" [class.active]="activeTab === 'contact'" [attr.aria-selected]="activeTab === 'contact'" (click)="activeTab = 'contact'; loadContact()">Contact details</button>
        <button type="button" role="tab" [class.active]="activeTab === 'library'" [attr.aria-selected]="activeTab === 'library'" (click)="activeTab = 'library'">Review & download</button>
      </div>
      <p class="feedback-banner" role="status" *ngIf="message">{{ message }}</p>

      <section class="panel resume-contact-panel" *ngIf="activeTab === 'contact'">
        <div class="panel-head"><div><h2>Contact details on your resumes</h2><p>Choose how employers can reach you. Saved settings replace phone, email, and LinkedIn details from your source when generating a new resume, including application bundles. Regenerate an existing version to apply changes.</p></div></div>
        <p *ngIf="!contactLoaded && !contactLoadFailed" role="status">Loading contact settings…</p>
        <p *ngIf="contactLoadFailed" role="alert">Contact settings could not be loaded. <button class="btn-secondary" type="button" (click)="loadContact()">Retry</button></p>
        <form #contactForm="ngForm" (ngSubmit)="saveContact()" *ngIf="contactLoaded">
          <div class="resume-contact-field">
            <label>Phone number<input type="tel" autocomplete="tel" name="contactPhone" [(ngModel)]="contact.phone" maxlength="60" placeholder="+1 416 555 0123"></label>
            <label class="resume-contact-toggle"><input type="checkbox" name="includePhone" [(ngModel)]="contact.include_phone">Include phone on new resumes</label>
          </div>
          <div class="resume-contact-field">
            <label>Email address<input type="email" email autocomplete="email" name="contactEmail" [(ngModel)]="contact.email" maxlength="254" placeholder="you@example.com"></label>
            <label class="resume-contact-toggle"><input type="checkbox" name="includeEmail" [(ngModel)]="contact.include_email">Include email on new resumes</label>
          </div>
          <div class="resume-contact-field">
            <label>LinkedIn profile URL<input type="url" name="contactLinkedin" [(ngModel)]="contact.linkedin_url" maxlength="500" placeholder="https://www.linkedin.com/in/your-name/"></label>
            <label class="resume-contact-toggle"><input type="checkbox" name="includeLinkedin" [(ngModel)]="contact.include_linkedin">Include LinkedIn on new resumes</label>
          </div>
          <p class="field-hint">Empty fields are omitted. Unchecked details remain saved here but are left out of new resumes. Until you save settings, contacts from your source resume are preserved.</p>
          <p *ngIf="contactError" role="alert">{{ contactError }}</p>
          <div class="action-row form-actions"><button class="btn-primary" type="submit" [disabled]="savingContact || contactForm.invalid">{{ savingContact ? 'Saving…' : 'Save contact settings' }}</button></div>
        </form>
      </section>

      <section class="panel source-resume-panel" *ngIf="activeTab === 'create'">
        <div class="panel-head"><div><p class="eyebrow">Candidate source</p><h2>Add your master resume</h2><p>Upload your resume in Candidate Profile to extract career evidence and contact details, or paste a master copy here to use as the source for new drafts.</p></div></div>
        <p><a class="btn-secondary" routerLink="/profile" [queryParams]="{ tab: 'sources' }">Upload a resume & extract evidence →</a></p>
        <details *ngIf="sourceResumes.length"><summary>Saved source resumes ({{ sourceResumes.length }})</summary><p *ngFor="let source of sourceResumes">{{ source.title }} · {{ source.updated_at | date:'medium' }}</p></details>
        <label>Source name<input [(ngModel)]="newTitle" name="newTitle" placeholder="Master Resume"></label>
        <label>Resume text <span class="field-hint">Plain text or Markdown</span><textarea rows="18" [(ngModel)]="newMarkdown" name="newMarkdown" placeholder="Paste your existing resume here…"></textarea></label>
        <div class="action-row form-actions"><button class="btn-primary" type="button" (click)="createCanonical()" [disabled]="!newMarkdown.trim() || savingSource">{{ savingSource ? 'Saving…' : 'Save master copy' }}</button><button class="btn-secondary" type="button" (click)="activeTab = 'library'">Cancel</button></div>
      </section>

      <div class="resume-studio-grid" *ngIf="activeTab === 'library'">
        <aside class="panel material-library">
          <div class="panel-head"><div><h2>Generated materials</h2><p>{{ resumes.length }} resumes · {{ coverLetters.length }} letters</p></div><button class="icon-button" type="button" (click)="load()" aria-label="Refresh materials">↻</button></div>
          <label *ngIf="!embeddedJobId">Filter by opportunity<select [(ngModel)]="libraryJobId" (ngModelChange)="loadMaterials()"><option [ngValue]="null">All opportunities</option><option *ngFor="let job of jobs" [ngValue]="job.id">{{ job.title }} · {{ job.company }}</option></select></label>
          <div class="material-group-label">Resumes</div>
          <button class="job-row resume-version-row" type="button" *ngFor="let resume of resumes" [class.selected]="selected?.id === resume.id" (click)="selectResume(resume)">
            <span class="version-icon">{{ resume.kind === 'tailored' ? 'AI' : 'S' }}</span>
            <span><strong>{{ resume.title }}</strong><small>{{ resume.target_job_title }} · {{ resume.updated_at | date:'medium' }} · {{ resume.approved ? 'Reviewed' : 'Draft' }}</small></span>
            <span class="status-dot" [class.approved]="resume.approved" [attr.aria-label]="resume.approved ? 'Reviewed' : 'Draft'"></span>
          </button>
          <div class="empty-state small" *ngIf="!resumes.length && !embeddedJobId"><span class="empty-icon">▤</span><h3>No resumes yet</h3><p>Add a source resume, then let Forth generate the designed version.</p><button class="btn-primary" type="button" (click)="activeTab = 'create'">Add source resume</button></div>
          <p *ngIf="embeddedJobId && !coverLetters.length" class="field-hint">No cover letter yet. Use “Generate new document versions” in More actions above to create both documents.</p><ng-container *ngIf="coverLetters.length">
            <div class="material-group-label">Cover letters</div>
            <button class="job-row resume-version-row" type="button" *ngFor="let letter of coverLetters" [class.selected]="selectedLetter?.id === letter.id" (click)="selectLetter(letter)"><span class="version-icon letter">CL</span><span><strong>{{ letter.title }}</strong><small>Version {{ letter.version }} · {{ letter.target_job_title }} · {{ letter.approved ? 'Reviewed' : 'Draft' }}</small></span><span class="status-dot" [class.approved]="letter.approved"></span></button>
          </ng-container>
        </aside>

        <section class="resume-result" *ngIf="selected">
          <section class="result-toolbar">
            <div>
              <div class="result-title-line"><span class="ai-designed-badge">✦ AI designed</span><span class="status-chip" [class.good]="selected.approved">{{ selected.approved ? 'Reviewed' : 'Ready for review' }}</span></div>
              <h2>{{ selected.title }}</h2>
              <p>{{ selected.target_job_title || 'Canonical source' }} · Updated {{ selected.updated_at | date:'mediumDate' }}</p>
            </div>
            <div class="result-actions">
              <a class="btn-secondary" *ngIf="selected.target_job && !embeddedJobId" [routerLink]="['/jobs', selected.target_job]" [queryParams]="{tab: 'documents'}">Open job workspace</a>
              <button class="btn-secondary" type="button" (click)="downloadPdf(selected)" [disabled]="exportingPdfId === selected.id || designDirty || designLoading"><span class="spinner" *ngIf="exportingPdfId === selected.id" aria-hidden="true"></span>{{ exportingPdfId === selected.id ? 'Rendering PDF…' : '↓ Download PDF' }}</button>
            </div>
          </section>

          <details class="resume-designer" *ngIf="designDraft"><summary>Adjust document design</summary>
            <div class="panel-head"><div><h3>Resume designer</h3><p>Adjust this version without rewriting your experience. The preview uses the PDF renderer’s design and embedded fonts.</p></div></div>
            <div class="designer-controls">
              <label>Style<select [(ngModel)]="designDraft.template" (ngModelChange)="previewDesign()"><option value="modern">Modern</option><option value="minimal">Minimal</option><option value="classic">Classic</option></select></label>
              <label>Layout<select [(ngModel)]="designDraft.layout" (ngModelChange)="previewDesign()"><option value="single">Single column</option><option value="two_column">Balanced two columns</option></select></label>
              <label>Font<select [(ngModel)]="designDraft.font" (ngModelChange)="previewDesign()"><option value="sans">Clean sans · Helvetica-style</option><option value="humanist">Humanist sans · Calibri-style</option><option value="serif">Classic serif</option></select></label>
              <label>Spacing<select [(ngModel)]="designDraft.density" (ngModelChange)="previewDesign()"><option value="compact">Compact</option><option value="balanced">Balanced</option><option value="spacious">Spacious</option></select></label>
              <label>Accent color<input type="color" [(ngModel)]="designDraft.accent" (change)="previewDesign()"></label>
              <label>Paper<select [(ngModel)]="designDraft.page_size" (ngModelChange)="previewDesign()"><option value="Letter">Letter</option><option value="A4">A4</option></select></label>
              <label>Page limit<select [(ngModel)]="designDraft.max_pages" (ngModelChange)="previewDesign()"><option [ngValue]="0">Automatic</option><option [ngValue]="1">One page</option><option [ngValue]="2">Two pages</option><option [ngValue]="3">Three pages</option></select></label>
            </div>
            <p class="field-hint">Fonts are embedded for consistent downloads: Liberation Sans, Carlito, or Liberation Serif. Two columns keep selectable text; some application parsers work best with a single column.</p>
            <p class="field-hint">The preview shows continuous content. PDF export checks the page limit and may use compact spacing to fit. If it still exceeds the limit, Forth asks you to shorten it instead of cutting off content.</p>
            <div class="action-row"><button type="button" class="btn-secondary" (click)="previewDesign(true)" [disabled]="designLoading">Apply saved style instructions</button><button type="button" class="btn-primary" (click)="saveDesign()" [disabled]="!designDirty || designLoading">{{ designLoading ? 'Updating preview…' : 'Save design' }}</button></div>
            <p class="field-hint">Saved style instructions use this opportunity’s override, or your Settings defaults. Writing and emphasis changes require Regenerate. Save this design before downloading.</p>
          </details>
          <p class="field-hint" role="status" *ngIf="designLoading">Loading design preview…</p>
          <p role="alert" *ngIf="designError">{{ designError }} <button type="button" class="btn-secondary" (click)="loadDesign()">Retry preview</button></p>
          <section class="document-stage" *ngIf="designPreview">
            <iframe class="designed-resume-preview" title="Designed resume preview" sandbox="" [srcdoc]="designPreview"></iframe>
          </section>

          <section class="resume-review-grid">
            <div class="review-card"><span class="review-icon good">✓</span><div><strong>{{ supportedClaims(selected) }} supported claims</strong><p>Statements linked to candidate evidence.</p></div></div>
            <div class="review-card"><span class="review-icon" [class.warn]="unsupportedClaims(selected) > 0">{{ unsupportedClaims(selected) }}</span><div><strong>Claims need attention</strong><p>{{ unsupportedClaims(selected) ? 'Review these before approval.' : 'No unsupported claims detected.' }}</p></div></div>
            <div class="review-card"><span class="review-icon keyword">{{ keywordCount(selected) }}</span><div><strong>Relevant terms covered</strong><p>Language supported by your experience.</p></div></div>
          </section>

          <details class="generation-notes" *ngIf="(selected.validation?.summary_changes || []).length || (selected.validation?.risk_notes || []).length">
            <summary>Why Forth made these choices</summary>
            <div><p *ngFor="let note of selected.validation?.summary_changes || []"><span>✓</span>{{ note }}</p><p *ngFor="let note of selected.validation?.risk_notes || []"><span>!</span>{{ note }}</p></div>
          </details>

          <details class="generation-notes" *ngIf="unsupportedClaims(selected)"><summary>Review unsupported claims ({{ unsupportedClaims(selected) }})</summary><ul><li *ngFor="let claim of selected.validation?.unsupported_claims">{{ claim }}</li></ul></details>
          <p class="field-hint">Approval records your review of this version. Downloads are available for drafts; review their content before using them.</p>
          <label class="risk-accept" *ngIf="!selected.approved && unsupportedClaims(selected)"><input type="checkbox" [(ngModel)]="acceptResumeRisk" name="acceptResumeRisk"><span>I reviewed the unsupported claims and accept the risk for this version.</span></label>
          <div class="review-footer">
            <button class="btn-primary" type="button" (click)="approve(selected)" *ngIf="!selected.approved" [disabled]="approvingResumeId === selected.id || (unsupportedClaims(selected) && !acceptResumeRisk)"><span class="spinner" *ngIf="approvingResumeId === selected.id" aria-hidden="true"></span>{{ approvingResumeId === selected.id ? 'Saving review…' : 'Mark resume as reviewed' }}</button>
            <button class="btn-secondary quiet-action" type="button" (click)="downloadSource(selected)">Download source</button>
          </div>
        </section>

        <section class="resume-result" *ngIf="selectedLetter">
          <section class="result-toolbar"><div><div class="result-title-line"><span class="ai-designed-badge purple">✦ AI written</span><span class="status-chip" [class.good]="selectedLetter.approved">{{ selectedLetter.approved ? 'Reviewed' : 'Ready for review' }}</span></div><h2>{{ selectedLetter.title }}</h2><p>Cover letter · version {{ selectedLetter.version }}</p></div></section>
          <section class="document-stage cover-letter-stage"><div class="page-shadow"><article class="resume-paper cover-letter-paper" [class.template-classic]="design(selectedLetter).template === 'classic'" [class.template-minimal]="design(selectedLetter).template === 'minimal'" [class.density-compact]="design(selectedLetter).density === 'compact'" [class.density-spacious]="design(selectedLetter).density === 'spacious'" [style.--document-accent]="design(selectedLetter).accent" [innerHTML]="renderMarkdown(selectedLetter.content_markdown)"></article></div></section>
          <details class="generation-notes" *ngIf="selectedLetter.validation?.unsupported_claims?.length"><summary>Claims to review</summary><ul><li *ngFor="let claim of selectedLetter.validation.unsupported_claims">{{ claim }}</li></ul></details>
          <p class="field-hint" *ngFor="let note of selectedLetter.validation?.risk_notes || []">{{ note }}</p>
          <div class="action-row"><button class="btn-secondary" (click)="downloadLetter(selectedLetter, 'pdf')">Download PDF</button><button class="btn-secondary" (click)="downloadLetter(selectedLetter, 'markdown')">Download Markdown</button></div>
          <label class="risk-accept" *ngIf="!selectedLetter.approved && (selectedLetter.validation?.unsupported_claims || []).length"><input type="checkbox" [(ngModel)]="acceptLetterRisk" name="acceptLetterRisk"><span>I reviewed the unsupported claims and accept the risk for this version.</span></label>
          <div class="review-footer"><button class="btn-primary" type="button" (click)="approveLetter(selectedLetter)" *ngIf="!selectedLetter.approved" [disabled]="approvingLetterId === selectedLetter.id || ((selectedLetter.validation?.unsupported_claims || []).length && !acceptLetterRisk)"><span class="spinner" *ngIf="approvingLetterId === selectedLetter.id" aria-hidden="true"></span>{{ approvingLetterId === selectedLetter.id ? 'Saving review…' : 'Mark cover letter as reviewed' }}</button></div>
        </section>

        <section class="panel empty-result" *ngIf="!selected && !selectedLetter"><span>✦</span><h2>Choose a generated version</h2><p>The designed resume and its evidence review will appear here.</p></section>
      </div>
    </section>
  `,
})
export class ResumeLabComponent implements OnInit {
  @Input() embeddedJobId?: number;
  @Output() documentsChanged = new EventEmitter<void>();
  resumes: Resume[] = [];
  sourceResumes: Resume[] = [];
  libraryJobId: number | null = null;
  savingSource = false;
  coverLetters: CoverLetter[] = [];
  jobs: JobPosting[] = [];
  selected?: Resume;
  selectedLetter?: CoverLetter;
  newTitle = 'Master Resume';
  newMarkdown = '';
  message = '';
  exportingPdfId: number | null = null;
  approvingResumeId: number | null = null;
  approvingLetterId: number | null = null;
  acceptResumeRisk = false;
  acceptLetterRisk = false;
  activeTab: 'library' | 'create' | 'contact' = 'library';
  contact: ResumeContact = { phone: '', email: '', linkedin_url: '', include_phone: true, include_email: true, include_linkedin: true };
  contactLoaded = false;
  contactLoadFailed = false;
  savingContact = false;
  contactError = '';

  constructor(private api: ApiService, private route: ActivatedRoute, private sanitizer: DomSanitizer) {}

  ngOnInit(): void {
    const job = this.embeddedJobId || Number(this.route.snapshot.queryParamMap.get('job'));
    if (job > 0) { this.libraryJobId = job; }
    this.load(); this.loadContact();
  }

  loadContact(): void {
    this.contactLoadFailed = false;
    this.api.candidateProfile().subscribe({
      next: (profile) => { this.contact = { ...this.contact, ...profile.resume_contact }; this.contactLoaded = true; },
      error: () => { this.contactLoadFailed = true; },
    });
  }

  saveContact(): void {
    if (!this.contactLoaded || this.savingContact) return;
    this.savingContact = true;
    this.contactError = '';
    this.api.updateCandidateProfile({ resume_contact: { ...this.contact } }).subscribe({
      next: (profile) => {
        this.contact = { ...this.contact, ...profile.resume_contact };
        this.savingContact = false;
        this.message = 'Contact settings saved. Generate or regenerate a resume to use them.';
      },
      error: (error) => {
        this.savingContact = false;
        const fields = error?.error?.resume_contact;
        this.contactError = fields ? Object.values(fields).flat().join(' ') : 'Could not save contact settings. Please try again.';
      },
    });
  }

  load(): void {
    this.loadMaterials();
    this.api.resumes({ kind: 'canonical' }).subscribe((page) => this.sourceResumes = page.results);
    this.api.jobs().subscribe((page) => {
      this.jobs = page.results;
      if (this.libraryJobId && !this.jobs.some(job => job.id === this.libraryJobId)) {
        this.api.job(this.libraryJobId).subscribe(job => this.jobs = [job, ...this.jobs]);
      }
    });
  }

  loadMaterials(selectNewest = false): void {
    if (selectNewest) { this.selected = undefined; this.selectedLetter = undefined; }
    const params: Record<string, string> = this.libraryJobId ? { job: String(this.libraryJobId) } : {};
    const resumeId = this.selected?.id;
    const letterId = this.selectedLetter?.id;
    this.api.resumes({ ...params, kind: 'tailored' }).subscribe((page) => {
      this.resumes = page.results;
      this.selected = !letterId ? this.resumes.find(resume => resume.id === resumeId) || this.resumes[0] : undefined;
      if (this.selected) this.loadDesign();
    });
    this.api.coverLetters(params).subscribe((page) => {
      this.coverLetters = page.results;
      this.selectedLetter = this.coverLetters.find(letter => letter.id === letterId);
      if (letterId && !this.selectedLetter && this.resumes[0]) this.selectResume(this.resumes[0]);
    });
  }

  downloadLetter(letter: CoverLetter, format: 'pdf' | 'markdown'): void {
    const request = format === 'pdf' ? this.api.exportCoverLetterPdf(letter.id) : this.api.exportCoverLetterMarkdown(letter.id);
    request.subscribe({ next: blob => {
      const url = URL.createObjectURL(blob); const link = document.createElement('a');
      link.href = url; link.download = `${letter.title}.${blob.type.includes('html') ? 'html' : format === 'pdf' ? 'pdf' : 'md'}`;
      link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    }, error: () => this.message = 'Download failed. Please try again.' });
  }

  selectResume(resume: Resume): void { this.selected = resume; this.loadDesign(); this.selectedLetter = undefined; this.acceptResumeRisk = false; }
  selectLetter(letter: CoverLetter): void { this.selectedLetter = letter; this.selected = undefined; this.acceptLetterRisk = false; }

  createCanonical(): void {
    if (this.savingSource || !this.newMarkdown.trim()) return;
    this.savingSource = true;
    this.api.createResume({ kind: 'canonical', title: this.newTitle, content_markdown: this.newMarkdown, content_json: {} }).subscribe({
      next: () => {
        this.savingSource = false;
        this.message = 'Master copy saved. Check the extracted contact details before generating.';
        this.activeTab = 'contact'; this.loadContact(); this.load();
      },
      error: () => { this.savingSource = false; this.message = 'Could not save the master copy. Your text is still here.'; },
    });
  }

  approve(resume: Resume): void {
    this.approvingResumeId = resume.id;
    this.api.approveResume(resume.id, this.acceptResumeRisk).subscribe((updated) => {
      this.selected = updated; this.approvingResumeId = null; this.acceptResumeRisk = false; this.message = 'Resume review saved. This does not submit an application.'; this.load(); this.documentsChanged.emit();
    }, (error) => { this.approvingResumeId = null; this.message = error?.error?.detail || 'Could not approve this resume.'; });
  }

  approveLetter(letter: CoverLetter): void {
    this.approvingLetterId = letter.id;
    this.api.approveCoverLetter(letter.id, this.acceptLetterRisk).subscribe((updated) => {
      this.selectedLetter = updated; this.approvingLetterId = null; this.acceptLetterRisk = false; this.load(); this.documentsChanged.emit();
    }, (error) => { this.approvingLetterId = null; this.message = error?.error?.detail || 'Could not approve this cover letter.'; });
  }

  downloadPdf(resume: Resume): void {
    this.exportingPdfId = resume.id;
    this.message = 'Rendering the designed PDF…';
    this.api.exportResumePdf(resume.id).subscribe({
      next: (blob) => { this.saveBlob(blob, `${this.slug(resume.title)}.${blob.type.includes('html') ? 'html' : 'pdf'}`); this.exportingPdfId = null; this.message = blob.type.includes('html') ? 'PDF renderer unavailable. Downloaded an HTML preview.' : 'Designed PDF downloaded.'; },
      error: async error => { this.exportingPdfId = null; let detail = error?.error?.detail; if (error.error instanceof Blob) { try { detail = JSON.parse(await error.error.text()).detail; } catch {} } this.message = detail || 'The PDF could not be rendered. Please try again.'; },
    });
  }

  downloadSource(resume: Resume): void {
    this.api.exportResumeMarkdown(resume.id).subscribe((blob) => this.saveBlob(blob, `${this.slug(resume.title)}.md`));
  }

  designDraft?: ResumeDesign;
  designPreview?: SafeHtml;
  designDirty = false;
  designLoading = false;
  designError = '';
  private designRequest = 0;

  loadDesign(): void {
    if (!this.selected) return;
    this.designDraft = this.design(this.selected);
    this.designPreview = undefined;
    this.designDirty = false;
    this.requestDesign();
  }
  previewDesign(useInstructions = false): void {
    this.designDirty = true;
    this.requestDesign({design: this.designDraft, use_saved_instructions: useInstructions});
  }
  saveDesign(): void { this.requestDesign({design: this.designDraft, save: true}); }
  private requestDesign(payload?: any): void {
    if (!this.selected) return;
    const id = this.selected.id, request = ++this.designRequest;
    this.designLoading = true;
    this.designError = '';
    this.api.resumeDesign(id, payload).subscribe({next: result => {
      if (request !== this.designRequest || this.selected?.id !== id) return;
      this.designDraft = result.design;
      // Only our escaped Markdown + validated design renderer supplies this HTML.
      // The iframe sandbox prevents scripts and top-level navigation.
      this.designPreview = this.sanitizer.bypassSecurityTrustHtml(result.html);
      this.designLoading = false;
      if (payload?.save) {
        this.selected = result.resume;
        this.resumes = this.resumes.map(resume => resume.id === id ? result.resume : resume);
        this.designDirty = false;
        this.message = 'Design saved. Your next PDF uses these settings. Review before approving.';
        this.documentsChanged.emit();
      }
    }, error: error => {
      if (request !== this.designRequest || this.selected?.id !== id) return;
      this.designLoading = false;
      this.designError = error?.error?.detail || 'Could not update the design preview.';
    }});
  }

  design(resume: Resume | CoverLetter): ResumeDesign {
    const supplied = resume.content_json?.design || {};
    return {
      template: ['modern', 'classic', 'minimal'].includes(supplied.template) ? supplied.template : 'modern',
      density: ['compact', 'balanced', 'spacious'].includes(supplied.density) ? supplied.density : 'balanced',
      accent: /^#[0-9a-f]{6}$/i.test(supplied.accent || '') ? supplied.accent : '#177d69',
      page_size: supplied.page_size === 'A4' ? 'A4' : 'Letter',
      layout: supplied.layout === 'two_column' ? 'two_column' : 'single',
      font: ['sans', 'humanist', 'serif'].includes(supplied.font) ? supplied.font : supplied.template === 'classic' ? 'serif' : 'sans',
      max_pages: [1, 2, 3].includes(supplied.max_pages) ? supplied.max_pages : 0,
      rationale: supplied.rationale || 'A restrained, ATS-safe layout that keeps your strongest evidence easy to scan.',
    };
  }

  renderMarkdown(markdown: string): string {
    const escape = (value: string) => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
    const format = (value: string) => escape(value).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/(^|\W)\*(.+?)\*(?=\W|$)/g, '$1<em>$2</em>');
    const inline = (value: string) => value.split(/(\[[^\]\n]+\]\((?:https?:\/\/|mailto:)(?:[^\s<>()]|\([^()\s<>]*\))+\))/g).map((part) => {
      const link = part.match(/^\[([^\]\n]+)\]\(((?:https?:\/\/|mailto:)(?:[^\s<>()]|\([^()\s<>]*\))+)\)$/);
      return link ? `<a href="${escape(link[2])}">${format(link[1])}</a>` : format(part);
    }).join('');
    const html: string[] = [];
    let listOpen = false;
    for (const raw of (markdown || '').split('\n')) {
      const line = raw.trim();
      if (/^[-*] /.test(line)) {
        if (!listOpen) { html.push('<ul>'); listOpen = true; }
        html.push(`<li>${inline(line.slice(2))}</li>`);
        continue;
      }
      if (listOpen) { html.push('</ul>'); listOpen = false; }
      if (!line) continue;
      if (line.startsWith('### ')) html.push(`<h3>${inline(line.slice(4))}</h3>`);
      else if (line.startsWith('## ')) html.push(`<h2>${inline(line.slice(3))}</h2>`);
      else if (line.startsWith('# ')) html.push(`<h1>${inline(line.slice(2))}</h1>`);
      else if (line === '---') html.push('<hr>');
      else html.push(`<p>${inline(line)}</p>`);
    }
    if (listOpen) html.push('</ul>');
    return html.join('');
  }

  supportedClaims(resume: Resume): number { return Number(resume.validation?.supported_claim_count || 0); }
  unsupportedClaims(resume: Resume): number { return (resume.validation?.unsupported_claims || []).length; }
  keywordCount(resume: Resume): number { return (resume.validation?.keyword_coverage || []).length; }

  private slug(value: string): string { return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); }
  private saveBlob(blob: Blob, filename: string): void {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; anchor.click(); URL.revokeObjectURL(url);
  }
}
