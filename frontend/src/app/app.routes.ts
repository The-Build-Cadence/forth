import { Routes } from '@angular/router';
import { LoginComponent } from './pages/login.component';
import { DashboardComponent } from './pages/dashboard.component';
import { ProfileComponent } from './pages/profile.component';
import { MatchesComponent } from './pages/matches.component';
import { ResumeLabComponent } from './pages/resume-lab.component';
import { PipelineComponent } from './pages/pipeline.component';
import { SourcesComponent } from './pages/sources.component';
import { ArtifactsComponent } from './pages/artifacts.component';
import { ConciergeComponent } from './pages/concierge.component';
import { authGuard } from './services/auth.guard';
import { SignupComponent } from './pages/signup.component';
import { guestGuard } from './services/guest.guard';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
  { path: 'login', component: LoginComponent, canActivate: [guestGuard] },
  { path: 'signup', component: SignupComponent, canActivate: [guestGuard] },
  { path: 'dashboard', component: DashboardComponent, canActivate: [authGuard] },
  { path: 'concierge', component: ConciergeComponent, canActivate: [authGuard] },
  { path: 'profile', component: ProfileComponent, canActivate: [authGuard] },
  { path: 'matches', component: MatchesComponent, canActivate: [authGuard] },
  { path: 'resume-lab', component: ResumeLabComponent, canActivate: [authGuard] },
  { path: 'pipeline', component: PipelineComponent, canActivate: [authGuard] },
  { path: 'sources', component: SourcesComponent, canActivate: [authGuard] },
  { path: 'strategy', redirectTo: 'profile', pathMatch: 'full' },
  { path: 'artifacts', component: ArtifactsComponent, canActivate: [authGuard] },
  { path: 'settings', redirectTo: 'profile', pathMatch: 'full' },
  { path: '**', redirectTo: 'dashboard' },
];
