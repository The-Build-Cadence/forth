import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, switchMap, throwError, map } from 'rxjs';
import { AuthService } from './auth.service';

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const session = auth.getRefreshToken();
  const token = localStorage.getItem('forth_access') || '';
  const isAuthRequest = req.url.includes('/auth/login/') || req.url.includes('/auth/signup/') || req.url.includes('/auth/refresh/');
  const guardSession = map((event: any) => {
    if (!isAuthRequest && auth.getRefreshToken() !== session) throw new Error('Session changed during request.');
    return event;
  });
  const recover = (error: any) => {
    if (!isAuthRequest && auth.getRefreshToken() !== session) return throwError(() => error);
    if (error.status !== 401 || isAuthRequest || !auth.getRefreshToken()) {
      if (error.status === 401 && !isAuthRequest) {
        auth.logout();
        router.navigate(['/login']);
      }
      return throwError(() => error);
    }
    return auth.refresh().pipe(
      switchMap(({ access }) => next(req.clone({
        setHeaders: { Authorization: `Bearer ${access}` },
      }))),
      catchError((refreshError) => {
        if (auth.getRefreshToken() === session) {
          auth.logout();
          router.navigate(['/login']);
        }
        return throwError(() => refreshError);
      }),
    ).pipe(guardSession);
  };
  if (!token) {
    return next(req).pipe(guardSession, catchError(recover));
  }
  const authedRequest = req.clone({
    setHeaders: {
      Authorization: `Bearer ${token}`,
    },
  });
  return next(authedRequest).pipe(guardSession, catchError(recover));
};
