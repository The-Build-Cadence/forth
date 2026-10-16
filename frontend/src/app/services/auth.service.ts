import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject, finalize, Observable, shareReplay, tap, map } from 'rxjs';
import { environment } from '../../environments/environment';

interface TokenResponse {
  access: string;
  refresh: string;
}

interface RegistrationResponse extends TokenResponse {
  user: { id: number; email: string };
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly accessKey = 'forth_access';
  private readonly refreshKey = 'forth_refresh';
  private readonly authedSubject = new BehaviorSubject<boolean>(this.hasSession());
  private refreshRequest$?: Observable<{ access: string }>;
  authed$ = this.authedSubject.asObservable();

  constructor(private http: HttpClient) {
    // A different tab may switch accounts while this tab still displays private data.
    window.addEventListener('storage', (event) => {
      if (event.key === this.refreshKey || event.key === null) window.location.reload();
    });
  }

  login(username: string, password: string): Observable<TokenResponse> {
    const identity = username.trim();
    const normalizedIdentity = identity.includes('@') ? identity.toLowerCase() : identity;
    return this.http.post<TokenResponse>(`${environment.apiBaseUrl}/auth/login/`, { username: normalizedIdentity, password }).pipe(
      tap((tokens) => {
        sessionStorage.removeItem('forth_onboarding_dismissed');
        localStorage.setItem(this.accessKey, tokens.access);
        localStorage.setItem(this.refreshKey, tokens.refresh);
        this.authedSubject.next(true);
      }),
    );
  }

  signup(email: string, password: string): Observable<RegistrationResponse> {
    return this.http.post<RegistrationResponse>(`${environment.apiBaseUrl}/auth/signup/`, { email, password }).pipe(
      tap((tokens) => {
        sessionStorage.removeItem('forth_onboarding_dismissed');
        localStorage.setItem(this.accessKey, tokens.access);
        localStorage.setItem(this.refreshKey, tokens.refresh);
        this.authedSubject.next(true);
      }),
    );
  }

  refresh(): Observable<{ access: string }> {
    if (this.refreshRequest$) {
      return this.refreshRequest$;
    }
    const refreshToken = this.getRefreshToken();
    this.refreshRequest$ = this.http.post<{ access: string }>(`${environment.apiBaseUrl}/auth/refresh/`, {
      refresh: refreshToken,
    }).pipe(
      map((tokens) => {
        if (this.getRefreshToken() !== refreshToken) throw new Error('Session changed during refresh.');
        return tokens;
      }),
      tap((tokens) => {
        localStorage.setItem(this.accessKey, tokens.access);
        this.authedSubject.next(true);
      }),
      finalize(() => { if (this.getRefreshToken() === refreshToken) this.refreshRequest$ = undefined; }),
      shareReplay(1),
    );
    return this.refreshRequest$;
  }

  logout(): void {
    this.refreshRequest$ = undefined;
    localStorage.removeItem(this.accessKey);
    localStorage.removeItem(this.refreshKey);
    sessionStorage.removeItem('forth_onboarding_dismissed');
    this.authedSubject.next(false);
  }

  hasSession(): boolean {
    return Boolean(this.getAccessToken() || this.getRefreshToken());
  }

  getAccessToken(): string {
    return localStorage.getItem(this.accessKey) || '';
  }

  getRefreshToken(): string {
    return localStorage.getItem(this.refreshKey) || '';
  }
}
