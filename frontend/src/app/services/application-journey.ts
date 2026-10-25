export const applicationStages = [
  { key: 'saved', label: 'Saved' },
  { key: 'preparing', label: 'Preparing' },
  { key: 'applied', label: 'Applied' },
  { key: 'recruiter_screen', label: 'Interviewing' },
  { key: 'offer', label: 'Offer' },
  { key: 'archived', label: 'Closed' },
];

export function applicationStage(status: string): string {
  if (['review', 'discovered', 'saved'].includes(status)) return 'saved';
  if (['approved', 'preparing', 'materials_ready', 'resume_ready'].includes(status)) return 'preparing';
  if (['applied', 'follow_up_due'].includes(status)) return 'applied';
  if (['recruiter_screen', 'technical_screen', 'onsite_final'].includes(status)) return 'recruiter_screen';
  if (['rejected', 'archived'].includes(status)) return 'archived';
  return status;
}

export function applicationStageLabel(status: string): string {
  return applicationStages.find(stage => stage.key === applicationStage(status))?.label || 'Saved';
}

export function localDateTime(value: string | null): string {
  if (!value) return '';
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}
