// The board preserves stored statuses; the workspace may group them into a journey.
export const applicationBoardStatuses = [
  { key: 'discovered', label: 'Discovered' },
  { key: 'review', label: 'Review' },
  { key: 'saved', label: 'Saved' },
  { key: 'approved', label: 'Approved to prepare' },
  { key: 'preparing', label: 'Preparing' },
  { key: 'resume_ready', label: 'Resume ready' },
  { key: 'materials_ready', label: 'Materials ready' },
  { key: 'applied', label: 'Applied' },
  { key: 'follow_up_due', label: 'Follow-up due' },
  { key: 'recruiter_screen', label: 'Recruiter screen' },
  { key: 'technical_screen', label: 'Technical screen' },
  { key: 'onsite_final', label: 'Onsite / final' },
  { key: 'offer', label: 'Offer' },
  { key: 'rejected', label: 'Rejected' },
  { key: 'archived', label: 'Archived' },
];

export function applicationsInStatus<T extends { status: string }>(applications: T[], status: string): T[] {
  return applications.filter(application => application.status === status);
}

export function applicationAge(application: {
  status: string; status_entered_at?: string; status_age_estimated?: boolean; follow_up_at?: string | null;
}, now = Date.now()) {
  const entered = Date.parse(application.status_entered_at || '');
  const elapsed = Math.max(0, now - entered);
  const days = Math.floor(elapsed / 86400000);
  const hours = Math.floor(elapsed / 3600000);
  const known = Number.isFinite(entered);
  const age = !known ? 'Age unavailable' : hours < 1 ? 'Just entered' : days < 1 ? `${hours}h in stage` : `${days}d in stage`;
  const terminal = ['rejected', 'archived'].includes(application.status);
  const reminder = Date.parse(application.follow_up_at || '');
  let action = '';
  if (!terminal) {
    if (application.status === 'follow_up_due' || reminder <= now) action = 'Follow-up due';
    else if (application.status === 'offer') action = 'Review offer';
    else if (known && ['saved', 'review', 'discovered', 'approved'].includes(application.status) && days >= 3) action = 'Review next step';
    else if (known && ['resume_ready', 'materials_ready'].includes(application.status) && days >= 2) action = 'Review and apply';
    else if (known && application.status === 'preparing' && hours >= 1) action = 'Check preparation';
    else if (known && application.status === 'applied' && days >= 7 && !Number.isFinite(reminder)) action = 'Consider follow-up';
    else if (known && ['recruiter_screen', 'technical_screen', 'onsite_final'].includes(application.status) && days >= 7 && !Number.isFinite(reminder)) action = 'Check next steps';
  }
  const label = (known && application.status_age_estimated ? '~' : '') + age;
  const title = !known ? 'No stage-entry date is available.' : application.status_age_estimated
    ? `Estimated from the last recorded activity on ${new Date(entered).toLocaleString()}. Earlier stage changes were not consistently tracked.`
    : `Entered this stage on ${new Date(entered).toLocaleString()}.`;
  return {label, title, action};
}
