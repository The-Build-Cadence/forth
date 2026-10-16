import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '../services/auth.service';

@Component({
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  template: `
    <main class="auth-page">
      <section class="auth-story">
        <div class="auth-brand"><img class="brand-mark" src="/brand-mark.svg" alt="" width="40" height="40"><strong>Forth</strong></div>
        <div class="auth-story-copy">
          <p class="eyebrow">Your career, moving forward</p>
          <h1>Your next move, fully staffed.</h1>
          <p>Forth organizes your career story, finds stronger matches, and helps you create focused applications in one private workspace.</p>
          <div class="auth-benefits">
            <div><span>✓</span><p><strong>Evidence-first profile</strong><small>Keep every claim grounded in your real experience.</small></p></div>
            <div><span>✓</span><p><strong>Clear fit signals</strong><small>Understand strengths and gaps before you apply.</small></p></div>
            <div><span>✓</span><p><strong>One organized pipeline</strong><small>Stay on top of applications and follow-ups.</small></p></div>
          </div>
        </div>
        <p class="auth-footnote">Private by design · Your data stays in your workspace</p>
      </section>
      <section class="auth-panel">
        <div class="mobile-auth-brand"><img class="brand-mark" src="/brand-mark.svg" alt="" width="40" height="40"><strong>Forth</strong></div>
        <p class="eyebrow">Welcome back</p>
        <h2>Sign in to your workspace</h2>
        <p class="auth-subtitle">Pick up where you left off.</p>
        <form (ngSubmit)="login()">
          <label>
            Email or username
            <input name="username" [(ngModel)]="username" autocomplete="username" placeholder="you@example.com">
          </label>
          <label>
            Password
            <input name="password" type="password" [(ngModel)]="password" autocomplete="current-password" placeholder="Your password">
          </label>
          <button class="btn-primary auth-submit" type="submit" [disabled]="loading">{{ loading ? 'Signing in…' : 'Sign in' }}</button>
          <p class="error" *ngIf="error">{{ error }}</p>
        </form>
        <p class="auth-switch">New to Forth? <a routerLink="/signup">Create your workspace</a></p>
      </section>
    </main>
  `,
})
export class LoginComponent {
  username = '';
  password = '';
  loading = false;
  error = '';

  constructor(private auth: AuthService, private router: Router) {}

  login(): void {
    this.loading = true;
    this.error = '';
    this.auth.login(this.username, this.password).subscribe({
      next: () => {
        this.loading = false;
        this.router.navigate(['/dashboard']);
      },
      error: () => {
        this.loading = false;
        this.error = 'Login failed. Check your email or username and password.';
      },
    });
  }
}
