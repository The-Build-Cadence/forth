import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '../services/auth.service';

@Component({
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  styleUrl: './signup.component.css',
  template: `
    <main class="auth-page signup-page">
      <section class="auth-story signup-story">
        <div class="auth-brand"><img class="brand-mark" src="/brand-mark.svg" alt="" width="40" height="40"><strong>Forth</strong></div>
        <div class="signup-story-copy">
          <p class="eyebrow">A better job search starts with context</p>
          <h1>Build the career profile your search deserves.</h1>
          <p>Create your private workspace, then your Profile Steward will turn your experience, ambitions, and boundaries into an actionable candidate profile.</p>
          <div class="signup-journey" aria-label="Account setup journey">
            <div class="active"><span>1</span><p><strong>Create your workspace</strong><small>Email and a secure password</small></p></div>
            <i></i>
            <div><span>2</span><p><strong>Meet your Profile Steward</strong><small>Upload a resume or answer from scratch</small></p></div>
            <i></i>
            <div><span>3</span><p><strong>Activate your search</strong><small>Start with a profile ready for sourcing and matching</small></p></div>
          </div>
        </div>
        <p class="auth-footnote">Instant access · Your workspace is ready immediately</p>
      </section>

      <section class="auth-panel signup-panel">
        <div class="mobile-auth-brand"><img class="brand-mark" src="/brand-mark.svg" alt="" width="40" height="40"><strong>Forth</strong></div>
        <div class="signup-step"><span>1 of 2</span><i><b></b></i></div>
        <p class="eyebrow">Create your workspace</p>
        <h2>Let’s get your search moving</h2>
        <p class="auth-subtitle">Next, your Profile Steward will build your candidate profile with you.</p>

        <form (ngSubmit)="signup()" novalidate>
          <label>
            Email address
            <input name="email" type="email" [(ngModel)]="email" autocomplete="email" inputmode="email" placeholder="you@example.com" required (blur)="emailTouched = true">
            <small class="field-error" *ngIf="emailTouched && !validEmail">Enter a valid email address.</small>
          </label>
          <div class="signup-field">
            <label for="signup-password">Password</label>
            <span class="password-field"><input id="signup-password" name="password" [type]="showPassword ? 'text' : 'password'" [(ngModel)]="password" autocomplete="new-password" placeholder="Create a secure password" required><button type="button" (click)="showPassword = !showPassword" [attr.aria-label]="showPassword ? 'Hide password' : 'Show password'">{{ showPassword ? 'Hide' : 'Show' }}</button></span>
          </div>
          <div class="password-strength" *ngIf="password">
            <i><b [style.width.%]="strength"></b></i><span>{{ strengthLabel }}</span>
          </div>
          <div class="password-rules">
            <span [class.met]="password.length >= 12">{{ password.length >= 12 ? '✓' : '·' }} 12+ characters</span>
            <span [class.met]="hasLetterAndNumber">{{ hasLetterAndNumber ? '✓' : '·' }} Letters and numbers</span>
            <span [class.met]="passwordsMatch && !!confirmation">{{ passwordsMatch && confirmation ? '✓' : '·' }} Passwords match</span>
          </div>
          <label>
            Confirm password
            <input name="confirmation" type="password" [(ngModel)]="confirmation" autocomplete="new-password" placeholder="Type it again" required>
          </label>
          <button class="btn-primary auth-submit signup-submit" type="submit" [disabled]="loading || !canSubmit"><span class="spinner" *ngIf="loading"></span>{{ loading ? 'Creating your workspace…' : 'Create workspace & continue →' }}</button>
          <p class="signup-privacy">Private by design. You control the career information you share.</p>
          <p class="error signup-error" role="alert" *ngIf="error">{{ error }}</p>
        </form>
        <p class="auth-switch">Already have a workspace? <a routerLink="/login">Sign in</a></p>
      </section>
    </main>
  `,
})
export class SignupComponent {
  email = '';
  password = '';
  confirmation = '';
  emailTouched = false;
  showPassword = false;
  loading = false;
  error = '';

  constructor(private auth: AuthService, private router: Router) {}

  get validEmail(): boolean { return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(this.email.trim()); }
  get hasLetterAndNumber(): boolean { return /[A-Za-z]/.test(this.password) && /\d/.test(this.password); }
  get passwordsMatch(): boolean { return this.password === this.confirmation; }
  get canSubmit(): boolean { return this.validEmail && this.password.length >= 12 && this.hasLetterAndNumber && this.passwordsMatch; }
  get strength(): number {
    let score = 0;
    if (this.password.length >= 12) score += 30;
    if (this.password.length >= 16) score += 15;
    if (/[a-z]/.test(this.password) && /[A-Z]/.test(this.password)) score += 20;
    if (/\d/.test(this.password)) score += 15;
    if (/[^A-Za-z0-9]/.test(this.password)) score += 20;
    return Math.min(100, score);
  }
  get strengthLabel(): string { return this.strength >= 80 ? 'Strong password' : this.strength >= 55 ? 'Good start' : 'Keep strengthening it'; }

  signup(): void {
    this.emailTouched = true;
    if (!this.canSubmit || this.loading) return;
    this.loading = true;
    this.error = '';
    this.auth.signup(this.email.trim().toLowerCase(), this.password).subscribe({
      next: () => { this.loading = false; this.router.navigate(['/dashboard']); },
      error: (response) => {
        this.loading = false;
        const detail = response?.error?.email?.[0] || response?.error?.password?.[0] || response?.error?.detail;
        this.error = detail || 'We could not create your workspace. Please try again.';
      },
    });
  }
}
