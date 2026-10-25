import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { environment } from '../../environments/environment';
@Component({standalone: true, imports: [CommonModule, FormsModule, RouterLink], template: `
<main class="page privacy-page"><a routerLink="/login">← Sign in</a><section class="panel setup-card"><p class="eyebrow">Account recovery</p><h1>{{ reset ? 'Choose a new password' : 'Forgot your password?' }}</h1><p>{{ reset ? 'Use a unique password you haven’t used elsewhere.' : 'Enter your account email and we’ll send you a reset link.' }}</p><form (ngSubmit)="submit()" *ngIf="!done"><label *ngIf="!reset">Email address<input name="email" type="email" [(ngModel)]="email" required autocomplete="email"></label><ng-container *ngIf="reset"><label>New password<input name="password" type="password" [(ngModel)]="password" required minlength="12" autocomplete="new-password"></label><label>Confirm password<input name="confirmation" type="password" [(ngModel)]="confirmation" required autocomplete="new-password"></label></ng-container><button class="btn-primary" [disabled]="busy || (reset ? password.length < 12 || password !== confirmation : !email.trim())">{{ busy ? 'Please wait…' : reset ? 'Save new password' : 'Send reset link' }}</button></form><p class="feedback-banner" role="status" *ngIf="message">{{ message }}</p><a *ngIf="done" class="text-link" routerLink="/login">Return to sign in →</a></section></main>`})
export class RecoveryComponent {
  email = ''; password = ''; confirmation = ''; busy = false; done = false; message = ''; reset: boolean;
  constructor(private http: HttpClient, private route: ActivatedRoute) { this.reset = route.snapshot.routeConfig?.path === 'reset-password'; }
  submit(): void {
    if (this.busy) return; this.busy = true; this.message = '';
    const payload = this.reset ? {uid: this.route.snapshot.queryParamMap.get('uid'), token: this.route.snapshot.queryParamMap.get('token'), password: this.password, confirmation: this.confirmation} : {email: this.email.trim()};
    this.http.post<any>(`${environment.apiBaseUrl}/auth/${this.reset ? 'reset' : 'recovery'}/`, payload).subscribe({next: data => { this.busy = false; this.done = true; this.password = ''; this.confirmation = ''; this.message = data.detail; }, error: error => { this.busy = false; this.message = error?.error?.detail || 'Could not complete this request. Please try again.'; }});
  }
}
