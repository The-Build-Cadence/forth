import { Injectable } from '@angular/core';
import { catchError, exhaustMap, map, of, shareReplay, timer, timeout } from 'rxjs';
import { ApiService } from './api.service';

@Injectable({ providedIn: 'root' })
export class UsageService {
  constructor(private api: ApiService) {}
  readonly state$ = timer(0, 15000).pipe(
    exhaustMap(() => this.api.usage().pipe(
      timeout(12000),
      map(data => ({ usage: data?.providers?.openai && data?.providers?.brave ? data : null, error: !data?.providers?.openai || !data?.providers?.brave })),
      catchError(() => of({ usage: null, error: true })),
    )),
    shareReplay({ bufferSize: 1, refCount: true }),
  );
}
