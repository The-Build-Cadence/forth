import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiService } from '../services/api.service';
import { UsageIndicatorComponent } from '../usage-indicator.component';

@Component({
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, UsageIndicatorComponent],
  template: `
    <section class="page settings-page">
      <div class="page-head"><div><p class="eyebrow">Your account</p><h1>Settings</h1><p class="page-intro">Choose your AI, set writing defaults, and track your costs.</p></div></div>
      <app-usage-indicator [detailed]="true"></app-usage-indicator>
      <p class="feedback-banner" *ngIf="message" role="status">{{ message }}</p>
      <ng-container *ngIf="config; else loading">
        <section class="panel settings-panel"><h2>Account</h2><p>{{ config.name }} <span class="muted">· {{ config.email }}</span></p><a routerLink="/profile">Edit your career profile and search preferences →</a></section>
        <section class="panel settings-panel">
          <div class="panel-head"><div><h2>Your AI</h2><p>Use Forth’s default AI, or connect your OpenAI account and choose a text model.</p></div></div>
          <label class="toggle-row"><input type="checkbox" [(ngModel)]="config.use_personal_ai"> Use my OpenAI account</label>
          <p class="field-hint">When enabled, your key powers text generation and embeddings, including scheduled work and MCP actions. OpenAI bills your account directly. Embeddings stay on {{ config.embedding_model }} so existing matches remain compatible.</p>
          <div class="edit-grid">
            <label>OpenAI API key <input type="password" [(ngModel)]="apiKey" autocomplete="new-password" spellcheck="false" [placeholder]="config.has_openai_key ? 'Key saved — enter a replacement if needed' : 'sk-…'"><span class="field-hint">Encrypted on the server. The saved key is never returned to your browser.</span></label>
            <label>Text model <input [(ngModel)]="config.text_model" list="account-models" [disabled]="!config.use_personal_ai"><datalist id="account-models"><option *ngFor="let model of models" [value]="model"></option></datalist><span class="field-hint">Choose a text model supporting Responses and structured output. Default: {{ config.default_text_model }}.</span></label>
            <label>Reasoning effort <select [(ngModel)]="config.reasoning_effort" [disabled]="!config.use_personal_ai"><option value="">Model default</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select><span class="field-hint">Only set this for models that support reasoning. Higher effort can take longer and cost more.</span></label>
          </div>
          <div class="action-row"><button type="button" class="btn-secondary" (click)="loadModels()" [disabled]="!config.has_openai_key || busy || checking">{{ checking ? 'Checking…' : 'Verify saved key & list models' }}</button><button type="button" class="btn-secondary" (click)="removeKey()" [disabled]="!config.has_openai_key || busy">Remove saved key</button></div>
          <p class="field-hint" *ngIf="models.length">Key verified. {{ models.length }} model IDs found. Not every model supports the same features; you can also enter an exact model ID.</p>
        </section>
        <section class="panel settings-panel"><h2>Default material instructions</h2><p>Applied to new resumes, cover letters, and application answers. An opportunity can override these defaults.</p><label>Writing and design instructions<textarea rows="5" maxlength="6000" [(ngModel)]="config.generation_instructions" placeholder="Use a minimal layout, accent #177d69, concise bullets, and a warm, direct tone."></textarea></label><p class="field-hint">Styles: modern, classic, minimal. Layout: single or two columns. Fonts: Helvetica-style sans, Calibri-style sans, or serif. Paper: Letter or A4. Specify a hex accent and up to three pages. Saved instructions apply to new versions; use Resume Studio’s designer to restyle an existing resume.</p></section>
        <div class="action-row settings-save"><button class="btn-primary" type="button" (click)="save()" [disabled]="busy">{{ busy ? 'Saving…' : 'Save settings' }}</button></div>
      </ng-container>
      <ng-template #loading><p>{{ loadFailed ? 'Settings could not be loaded.' : 'Loading settings…' }}</p><button *ngIf="loadFailed" class="btn-secondary" (click)="load()">Try again</button></ng-template>
    </section>
  `,
  styles: [`
    .settings-panel { padding:24px; margin-bottom:20px; }
    .settings-panel h2 { margin-top:0; }
    .toggle-row { display:flex; align-items:center; gap:10px; }
    .toggle-row input { width:auto; }
    .settings-save { margin-bottom:28px; }
  `],
})
export class SettingsComponent implements OnInit {
  config: any;
  apiKey = '';
  models: string[] = [];
  message = '';
  busy = false;
  checking = false;
  loadFailed = false;
  constructor(private api: ApiService) {}
  ngOnInit(): void { this.load(); }
  load(): void { this.loadFailed = false; this.api.accountSettings().subscribe({next: data => this.config = data, error: () => this.loadFailed = true}); }
  save(): void {
    this.busy = true;
    const payload: any = { use_personal_ai: this.config.use_personal_ai, text_model: this.config.text_model, reasoning_effort: this.config.reasoning_effort, generation_instructions: this.config.generation_instructions };
    if (this.apiKey.trim()) payload.openai_api_key = this.apiKey.trim();
    this.api.saveAccountSettings(payload).subscribe({next: data => { this.config = data; this.apiKey = ''; this.busy = false; this.message = 'Settings saved. Future requests will use these choices.'; }, error: error => { this.apiKey = ''; this.busy = false; this.message = this.errorMessage(error, 'Could not save settings. Check your choices and try again.'); }});
  }
  removeKey(): void { this.busy = true; this.api.saveAccountSettings({remove_key: true}).subscribe({next: data => { this.config.has_openai_key = data.has_openai_key; this.config.use_personal_ai = false; this.apiKey = ''; this.models = []; this.busy = false; this.message = 'Key removed. Future requests use Forth’s AI.'; }, error: () => { this.busy = false; this.message = 'Could not remove the key. Try again.'; }}); }
  loadModels(): void { this.checking = true; this.api.accountModels().subscribe({next: data => { this.models = data.models; this.checking = false; this.message = 'Saved key verified; model list refreshed.'; }, error: error => { this.checking = false; this.message = error?.error?.detail || 'Could not verify the saved key.'; }}); }
  errorMessage(error: any, fallback: string): string { const detail = error?.error; return typeof detail?.detail === 'string' ? detail.detail : Array.isArray(detail?.non_field_errors) ? detail.non_field_errors.join(' ') : fallback; }
}
